from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, utils

from src.retrieve.base import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    document_type_of,
    fetch_and_store,
)
from src.retrieve.models import (
    DiscoveredDocument,
    DocumentRecord,
    MatchType,
    RetrievalIntent,
    SourceTier,
)

LISTING_PAGE = "https://www.aicte.gov.in/education/model-syllabus"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 5

_EXACT_SCORE = 99


class AICTEAdapter:
    source_id = "AICTE"
    tiers = [SourceTier.A]

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
            href = link["href"]
            text = link.get_text(strip=True)
            if not href.lower().endswith(".pdf"):
                continue
            if "model curriculum" not in text.lower():
                continue
            index[text] = urljoin(self.listing_page, href)
        return index

    def _ensure_index(self) -> dict[str, str]:
        if self._index is None:
            self._index = self.build_index()
        return self._index

    def resolve(self, intent: RetrievalIntent) -> list[DiscoveredDocument]:
        index = self._ensure_index()
        if not index:
            return []

        wanted = set(intent.required_document_type)
        scored: list[tuple[float, int, str]] = []
        for title, url in index.items():
            if document_type_of(url) not in wanted:
                continue
            # token_set_ratio does not penalise a candidate for carrying extra
            # words beyond the query, so a specialisation variant scores the same
            # as the plain branch it derives from. Break ties toward the title
            # closest in length to the query -- the less-qualified document.
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
            extension="pdf",
        )
