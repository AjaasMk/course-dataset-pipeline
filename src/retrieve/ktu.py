import re
import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

RAW_DIR = Path("data/raw")
SOURCE_ID = "KTU"
SCHEME_URL = "https://ktu.edu.in/academics/scheme"

# KTU's portal is a React SPA whose data comes from api.ktu.edu.in, and every
# API call carries an x-token that is a reCAPTCHA v3 token -- confirmed by
# POSTing anon/get?key=v3, which returns Google's reCAPTCHA site key and loader
# script, and by replaying a captured token, which is rejected with "Invalid
# token format". Harvesting and replaying that token would be defeating a bot
# challenge, which this project does not do (Decision 5's hard line, the same
# one that leaves Shiksha blocked).
#
# So this adapter drives the real UI in a real browser instead: the site issues
# its own token as it normally would, and we read what it renders and use its
# own download control. Slower than an API call, and correct.
#
# The flow is NOT reachable by deep-linking. Loading /academics/branch directly
# posts branchAccordingToScheme with id:null and gets HTTP 500 -- verified
# repeatedly, 0 rows rendered. The scheme id is only set by navigating through
# the nav: Regulations & Syllabus -> programme -> that scheme's Branch link.
PAGE_SETTLE_MS = 9_000
LIST_SETTLE_MS = 11_000
NAV_TIMEOUT_MS = 90_000


class KTUSyllabus(BaseModel):
    branch_name: str
    scheme_name: str
    programme: str
    academic_year: Optional[str] = None
    filename: str
    local_path: str


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def scheme_matches(scheme_name: str, year: str) -> bool:
    """Whether a scheme belongs to the requested year.

    KTU names a scheme "B.Tech Full Time 2024 Scheme" and also runs a separate
    "B. Tech Working Professional 2024 scheme" for the same year, so the year
    alone does not identify one scheme -- the caller picks among the matches.
    """
    return year in (scheme_name or "")


def branch_index(syllabi: list[KTUSyllabus]) -> dict[str, str]:
    """Branch name -> local syllabus path, for the shared fuzzy matcher.

    Mirrors every other adapter's build_index() contract so course-to-branch
    matching reuses the same scorer and per-source threshold rather than
    inventing a second matching path.
    """
    return {s.branch_name: s.local_path for s in syllabi if s.branch_name and s.local_path}


_SYLLABUS_LABEL = "syllabus"
_BRANCH_LABEL = "branch"

_PICK_SCHEME_BRANCH_JS = """
(schemeText) => {
  const leaves = [...document.querySelectorAll('*')].filter(
    e => e.children.length === 0 &&
         (e.textContent || '').toUpperCase().includes(schemeText.toUpperCase()));
  if (!leaves.length) return false;
  let node = leaves[0];
  for (let i = 0; i < 8 && node; i++) {
    const link = [...node.querySelectorAll('a,button')]
      .find(a => (a.textContent || '').trim().toLowerCase() === 'branch');
    if (link) { link.click(); return true; }
    node = node.parentElement;
  }
  return false;
}
"""

_COUNT_SYLLABUS_JS = """
() => [...document.querySelectorAll('a,button')]
        .filter(a => (a.textContent || '').trim().toLowerCase() === 'syllabus').length
"""

_CLICK_NTH_SYLLABUS_JS = """
(n) => {
  const links = [...document.querySelectorAll('a,button')]
    .filter(a => (a.textContent || '').trim().toLowerCase() === 'syllabus');
  if (n >= links.length) return false;
  links[n].click();
  return true;
}
"""

_CLICK_LAST_SYLLABUS_JS = """
() => {
  const links = [...document.querySelectorAll('a,button')]
    .filter(a => (a.textContent || '').trim().toLowerCase() === 'syllabus');
  if (!links.length) return false;
  links[links.length - 1].click();
  return true;
}
"""


def harvest_syllabi(
    programme: str = "B.Tech",
    scheme_year: str = "2024",
    scheme_contains: str = "FULL TIME 2024 SCHEME",
    raw_dir: Path = RAW_DIR,
    limit: Optional[int] = None,
) -> list[KTUSyllabus]:
    """Drive the real KTU UI once and save every branch's syllabus PDF.

    One browser session for the whole scheme rather than one per course: the
    navigation cost dominates, and a course-by-course drive would repeat the
    same four-step flow 750 times for data that does not vary by course.
    """
    from playwright.sync_api import sync_playwright

    out_dir = raw_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    harvested: list[KTUSyllabus] = []

    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1500, "height": 1400}, accept_downloads=True
        )
        page = context.new_page()
        try:
            if not _open_branch_list(page, programme, scheme_contains):
                return []
            total = page.evaluate(_COUNT_SYLLABUS_JS) or 0
            count = min(total, limit) if limit else total

            for index in range(count):
                # Re-navigate per branch. Opening a syllabus REPLACES the branch
                # list in place (50 links become 2) and there is no back control;
                # page.go_back() returns to /academics/branch with the SPA's
                # scheme id lost, which posts id:null and renders nothing --
                # confirmed live, the first branch downloaded and the rest found
                # an empty list. Replaying the four-step flow is slower and is
                # the only thing that actually works.
                if index and not _open_branch_list(page, programme, scheme_contains):
                    break
                branch = _branch_name_at(page, index)
                if not page.evaluate(_CLICK_NTH_SYLLABUS_JS, index):
                    continue
                page.wait_for_timeout(6_000)
                saved = _download_open_syllabus(page, out_dir)
                if saved is not None:
                    harvested.append(
                        KTUSyllabus(
                            branch_name=branch,
                            scheme_name=scheme_contains,
                            programme=programme,
                            academic_year=f"{scheme_year} - {int(scheme_year) + 1}",
                            filename=saved.name,
                            local_path=str(saved),
                        )
                    )
        finally:
            browser.close()

    return harvested


def _open_branch_list(page, programme: str, scheme_contains: str) -> bool:
    """Walk the nav to a scheme's branch list, the only route that works.

    Deep-linking /academics/branch is not equivalent: it posts
    branchAccordingToScheme with id:null and returns HTTP 500, rendering zero
    rows. The scheme id only reaches the SPA by clicking that scheme's own
    Branch link.
    """
    page.goto(SCHEME_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(PAGE_SETTLE_MS)

    page.click('button:has-text("Regulations & Syllabus")', force=True)
    page.wait_for_timeout(2_000)

    links = [
        e
        for e in page.query_selector_all("a,button,li,span")
        if (e.inner_text() or "").strip() == programme
    ]
    if not links:
        return False
    links[0].click(force=True)
    page.wait_for_timeout(PAGE_SETTLE_MS)

    if not page.evaluate(_PICK_SCHEME_BRANCH_JS, scheme_contains):
        return False
    page.wait_for_timeout(LIST_SETTLE_MS)
    return True


def _branch_name_at(page, index: int) -> str:
    names = page.evaluate(
        """() => [...document.querySelectorAll('a,button')]
              .filter(a => (a.textContent||'').trim().toLowerCase() === 'syllabus')
              .map(a => {
                 let n = a, label = '';
                 for (let i = 0; i < 6 && n; i++) {
                   const t = (n.innerText || '').trim();
                   if (t && t.toLowerCase() !== 'syllabus') { label = t.split('\\n')[0]; break; }
                   n = n.parentElement;
                 }
                 return label;
              })"""
    )
    return names[index] if index < len(names) else ""


def _download_open_syllabus(page, out_dir: Path) -> Optional[Path]:
    try:
        with page.expect_download(timeout=60_000) as pending:
            page.evaluate(_CLICK_LAST_SYLLABUS_JS)
        download = pending.value
    except Exception:
        return None

    destination = out_dir / download.suggested_filename
    shutil.copy(download.path(), destination)
    return destination
