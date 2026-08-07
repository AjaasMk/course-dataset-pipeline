from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, utils

from src.retrieve.base import USER_AGENT, REQUEST_TIMEOUT, fetch_and_store
from src.retrieve.models import (
    DiscoveredDocument,
    DocumentRecord,
    MatchType,
    RetrievalIntent,
    SourceTier,
)

LISTING_PAGE = "https://www.careers360.com/courses"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 5

_EXACT_SCORE = 99


def _is_course_page(url: str) -> bool:
    segments = [s for s in urlparse(url).path.split("/") if s]
    return len(segments) == 2 and segments[0] == "courses"


class Careers360Adapter:
    source_id = "CAREERS360"
    tiers = [SourceTier.D]

    def __init__(self, listing_page: str = LISTING_PAGE):
        self.listing_page = listing_page
        self._index: Optional[dict[str, str]] = None

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def build_index(self) -> dict[str, str]:
        response = requests.get(
            self.listing_page,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        index: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if not text:
                continue
            url = urljoin(self.listing_page, link["href"])
            if not _is_course_page(url):
                continue
            index.setdefault(text, url)
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
        )
