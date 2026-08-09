from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, utils

from src.retrieve.base import REQUEST_TIMEOUT, fetch_and_store
from src.retrieve.models import (
    DiscoveredDocument,
    DocumentRecord,
    MatchType,
    RetrievalIntent,
    SourceTier,
)

LISTING_PAGE = "https://collegedunia.com/courses"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 5

_EXACT_SCORE = 99
_CATEGORY_SUFFIX = "-colleges"

# CollegeDunia's default identifying UA (base.USER_AGENT) is edge-blocked
# outright (Akamai/CloudFront "Access Denied", confirmed live 2026-08-09,
# not a CAPTCHA/JS challenge) -- a realistic browser header set gets a real
# 200 with real server-rendered fee content. This is Decision 5's step 1
# ("re-verify with realistic headers... no new dependency") from this
# project's escalation policy, already an approved practice here, not a new
# line crossed. Shiksha.com stayed blocked even with these headers (likely
# TLS-fingerprint-based, not header-based) -- deferred, not built, since
# CollegeDunia alone already gives Fees non-zero Tier D corroboration.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def _is_category_page(url: str) -> bool:
    # Confirmed live 2026-08-09: real course-category pages are exactly one
    # path segment ending in "-colleges" (/bsc-colleges, /btech-colleges).
    # Every other href on the /courses page -- nav, footer, /courses itself,
    # per-institution pages under /college/... -- fails one of these checks.
    segments = [s for s in urlparse(url).path.split("/") if s]
    return len(segments) == 1 and segments[0].endswith(_CATEGORY_SUFFIX)


class CollegeDuniaAdapter:
    source_id = "COLLEGEDUNIA"
    tiers = [SourceTier.D]

    def __init__(self, listing_page: str = LISTING_PAGE):
        self.listing_page = listing_page
        self._index: Optional[dict[str, str]] = None

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def build_index(self) -> dict[str, str]:
        response = requests.get(self.listing_page, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Dedup by URL, not by (text, url): the same category page is
        # linked twice with different casing in real nav markup (a
        # title-case primary-nav entry and a lowercase footer entry,
        # confirmed live) -- keep whichever text appeared first.
        index: dict[str, str] = {}
        seen_urls: set[str] = set()
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if not text:
                continue
            url = urljoin(self.listing_page, link["href"])
            if not _is_category_page(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            index[text] = url
        return index

    def _ensure_index(self) -> dict[str, str]:
        if self._index is None:
            self._index = self.build_index()
        return self._index

    def resolve(self, intent: RetrievalIntent) -> list[DiscoveredDocument]:
        index = self._ensure_index()
        if not index:
            return []

        scored: list[tuple[int, int, str]] = []
        for title in index:
            best = max(
                fuzz.token_set_ratio(term, title, processor=utils.default_process)
                for term in intent.query_terms
            )
            closest = -min(abs(len(title) - len(term)) for term in intent.query_terms)
            scored.append((best, closest, title))

        scored.sort(reverse=True)
        return [
            DiscoveredDocument(
                document_url=index[title],
                document_title=title,
                match_confidence=score / 100,
                match_type=MatchType.EXACT if score >= _EXACT_SCORE else MatchType.FUZZY,
            )
            for score, _, title in scored[:MAX_CANDIDATES]
        ]

    def download(self, document: DiscoveredDocument) -> DocumentRecord:
        return fetch_and_store(
            document,
            source_id=self.source_id,
            source_tier=self.tiers[0],
            raw_dir=RAW_DIR,
            extension="html",
            headers=_HEADERS,
        )
