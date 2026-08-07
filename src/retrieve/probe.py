from enum import Enum
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel

MIN_TEXT_CHARS = 500
BLOCKED_STATUSES = (401, 403, 405, 406, 429)

_SPA_MARKERS = {
    'id="root"': "react-root",
    "id='root'": "react-root",
    'id="app"': "vue-app",
    "ng-app": "angular",
    "ng-version": "angular",
    "__NEXT_DATA__": "nextjs",
    "__NUXT__": "nuxt",
    "data-svelte": "svelte",
    "__sveltekit": "sveltekit",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
}


class ProbeVerdict(str, Enum):
    SERVER_RENDERED = "server_rendered"
    JS_REQUIRED = "js_required"
    BLOCKED = "blocked"
    ERROR = "error"


class ProbeResult(BaseModel):
    source_id: Optional[str] = None
    url: Optional[str] = None
    http_status: Optional[int] = None
    bytes: int = 0
    text_chars: int = 0
    link_count: int = 0
    pdf_link_count: int = 0
    spa_markers: list[str] = []
    verdict: ProbeVerdict
    note: str = ""


def classify(status: Optional[int], html: str) -> ProbeResult:
    if status is None:
        return ProbeResult(verdict=ProbeVerdict.ERROR, note="no response")
    if status in BLOCKED_STATUSES:
        return ProbeResult(
            http_status=status,
            verdict=ProbeVerdict.BLOCKED,
            note=f"HTTP {status} to a scripted client",
        )
    if status >= 400:
        return ProbeResult(http_status=status, verdict=ProbeVerdict.ERROR, note=f"HTTP {status}")

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text_chars = len(soup.get_text(" ", strip=True))
    links = [a["href"] for a in soup.find_all("a", href=True)]
    markers = sorted({name for token, name in _SPA_MARKERS.items() if token in html})

    verdict = (
        ProbeVerdict.SERVER_RENDERED if text_chars >= MIN_TEXT_CHARS else ProbeVerdict.JS_REQUIRED
    )
    note = (
        f"{text_chars} chars of visible text"
        if verdict is ProbeVerdict.SERVER_RENDERED
        else f"only {text_chars} chars of visible text; needs a rendering client"
    )

    return ProbeResult(
        http_status=status,
        bytes=len(html),
        text_chars=text_chars,
        link_count=len(links),
        pdf_link_count=sum(1 for href in links if href.lower().split("?")[0].endswith(".pdf")),
        spa_markers=markers,
        verdict=verdict,
        note=note,
    )
