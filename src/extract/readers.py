import re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.extract.models import PageText, Section

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_MIN_REPEATED_PAGE_COUNT = 3

# Real, non-Wikipedia (Careers360-style) pages don't wrap article content in a
# scoped container the way MediaWiki does, so the h1-based filter above only
# discards content BEFORE the title — nothing discards footer/forum noise
# AFTER it. Verified against the real downloaded Chemical Engineering page.
#
# First attempt classified noise by heading CSS class during the extraction
# loop (mirroring the h1-before-title filter) — reverted because classes here
# are reused across noise AND real content: individual FAQ questions use
# class="blockHeading" too (<h3 class="blockHeading"><strong>Question:</strong>
# ...), the exact class the forum/footer noise headings use. Classifying by
# class wrongly excluded the FAQs.
#
# Correct approach (matches the Wikipedia widget/sidebar removal above):
# anchor on the SPECIFIC noise heading found by text match, then decompose
# THAT heading's own ancestor container — not a blind class-wide search
# (verified those classes, e.g. "cardBlk", are shared with the FAQ section's
# own container too).
_QNA_FORUM_CONTAINER_ID = "qna"  # "Questions related to X" — stable, unique id
_SIGNIN_MODAL_ID = "commonSignin"  # sign-in/sign-up popup dialog
_NOISE_CONTAINER_CLASSES = (
    "new-fat-footer-bg-container",  # "download our app" promo banner
    "right-sidebar",  # "Popular Degrees" sidebar widget
)
_NOISE_HEADING_PATTERNS = (
    re.compile(r"popular\s.+\scolleges\sin\sindia", re.IGNORECASE),  # college directory cards
    re.compile(r"explore\s.+\scolleges\sin\sother\spopular\slocations", re.IGNORECASE),  # footer link directory
)


def _strip_noise_containers(soup: BeautifulSoup) -> None:
    # The real bottom-of-page site footer (Top Exams, College, Predictors &
    # Ebooks, Resources, ...) lives in a semantic <footer> tag — the most
    # reliable signal available, verified against the real downloaded page.
    footer = soup.find("footer")
    if footer is not None:
        footer.decompose()

    modal = soup.find(id=_SIGNIN_MODAL_ID)
    if modal is not None:
        modal.decompose()

    for class_name in _NOISE_CONTAINER_CLASSES:
        for container in soup.find_all(class_=class_name):
            container.decompose()

    qna = soup.find(id=_QNA_FORUM_CONTAINER_ID)
    if qna is not None:
        qna.decompose()

    for pattern in _NOISE_HEADING_PATTERNS:
        heading = soup.find(
            lambda tag: tag.name in _HEADING_TAGS and pattern.search(tag.get_text(strip=True))
        )
        if heading is not None:
            container = heading.find_parent("div") or heading
            container.decompose()


_RELATED_COURSES_HEADING_PATTERN = re.compile(r"courses\ssimilar\sto\s", re.IGNORECASE)


def _extract_related_courses_section(soup: BeautifulSoup) -> Section | None:
    # "Courses Similar to X" wraps each related course name in its own
    # <h3 class="heading-h3"><a>Name</a></h3> instead of a <li> — since h3 is
    # in _HEADING_TAGS, the main extraction loop below would otherwise treat
    # each course name as its own top-level heading with no content (dropped
    # by flush()'s empty-paragraph check), losing this data for
    # CourseDetail.related_courses entirely. Verified against the real
    # downloaded Chemical Engineering page. Extracted here as its own
    # Section, and the container is decomposed so the main loop doesn't
    # double-pick-up (or drop) these nested headings.
    heading = soup.find(
        lambda tag: tag.name in _HEADING_TAGS
        and _RELATED_COURSES_HEADING_PATTERN.search(tag.get_text(strip=True))
    )
    if heading is None:
        return None

    container = heading.find_next_sibling("div")
    if container is None:
        return None

    names = [a.get_text(strip=True) for a in container.find_all("a") if a.get_text(strip=True)]
    heading_title = heading.get_text(strip=True)
    container.decompose()
    # Decompose the heading too, not just its content div — otherwise the
    # main loop below still finds this heading (only its sibling div is
    # gone), starts a new section under the same title, and wrongly
    # accumulates whatever unrelated p/li content comes next in the
    # document. Confirmed live: this produced a duplicate "Courses Similar
    # to X" section full of unrelated modal/report-dialog text.
    heading.decompose()

    if not names:
        return None
    return Section(heading_title=heading_title, paragraphs=names)


def read_pdf(path: Path) -> list[PageText]:
    reader = PdfReader(path)
    raw_pages = [page.extract_text() for page in reader.pages]
    cleaned_pages = _strip_repeated_lines(raw_pages)
    return [PageText(page_number=i + 1, text=text) for i, text in enumerate(cleaned_pages)]


def _strip_repeated_lines(pages: list[str]) -> list[str]:
    page_lines = [[line.strip() for line in page.split("\n")] for page in pages]

    line_counts: Counter = Counter()
    for lines in page_lines:
        for line in set(lines):
            if line:
                line_counts[line] += 1

    repeated = {line for line, count in line_counts.items() if count >= _MIN_REPEATED_PAGE_COUNT}

    return ["\n".join(line for line in lines if line not in repeated) for lines in page_lines]


def read_html(path: Path) -> list[Section]:
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    # Wikipedia's language-switcher widget (id="p-lang-btn", MediaWiki's standard
    # "portlet: language" convention) sits right after <h1> and contains 200+ <li>
    # language names with no real content — verified against the real Marketing
    # page. The h1-based filter below only discards content BEFORE the h1, so
    # this needs its own removal.
    # Both are stable MediaWiki (Wikipedia) conventions verified against the
    # real Marketing page: the language-switcher widget and the table-of-
    # contents sidebar (which duplicates every section title as a link,
    # producing dozens of near-duplicate "paragraphs" with no real content).
    for widget_id in ("p-lang-btn", "mw-panel-toc"):
        for widget in soup.find_all(id=widget_id):
            widget.decompose()

    # Wikipedia embeds "sidebar" navbox templates (e.g. "Part of a series on
    # Marketing") inline within the real article body — these are navigation
    # aids, not prose, and aren't caught by the content-container scoping
    # above since they live inside mw-parser-output. Verified against the
    # real Marketing page.
    for sidebar in soup.find_all(class_="sidebar"):
        sidebar.decompose()

    _strip_noise_containers(soup)
    related_courses_section = _extract_related_courses_section(soup)

    # MediaWiki (Wikipedia) pages wrap the real article body in
    # id="mw-content-text", with zero nav/tools chrome inside it — and
    # notably no <h1> inside it either (the page title lives outside, in the
    # page header). Verified against the real Marketing page. When present,
    # scope entirely to this container and skip the h1-based filter below
    # (there's no h1 inside it to filter around).
    mediawiki_content = soup.find(id="mw-content-text")
    scope = mediawiki_content if mediawiki_content is not None else soup

    # Stage 1 retrieves table-based sources too -- NIRF rankings and seat
    # matrices carry all their content in <tr>, so a reader collecting only
    # p/li/headings returns nothing for them.
    elements = scope.find_all(list(_HEADING_TAGS.keys()) + ["p", "li", "tr"])

    if mediawiki_content is not None:
        seen_h1 = True
    else:
        # Real pages (Careers360) put navigation/share-widget headings (e.g.
        # "Popular Searches", "Share this via") before the real <h1> title —
        # verified against the actual downloaded Mechanical Engineering page.
        # Discard everything before the first <h1>. If there's no <h1> at
        # all, keep everything rather than discarding the whole document.
        has_h1 = any(el.name == "h1" for el in elements)
        seen_h1 = not has_h1

    sections: list[Section] = []
    current_heading = None
    current_paragraphs: list[str] = []

    def flush():
        if current_paragraphs:
            sections.append(Section(heading_title=current_heading, paragraphs=list(current_paragraphs)))

    for el in elements:
        if el.name == "h1":
            seen_h1 = True
        if not seen_h1:
            continue

        if el.name in _HEADING_TAGS:
            flush()
            current_paragraphs = []
            current_heading = el.get_text(strip=True)
        elif el.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in el.find_all(["td", "th"])]
            row = " | ".join(c for c in cells if c)
            if row:
                current_paragraphs.append(row)
        else:
            text = el.get_text(strip=True)
            if text:
                current_paragraphs.append(text)

    flush()
    if related_courses_section is not None:
        sections.append(related_courses_section)
    return sections
