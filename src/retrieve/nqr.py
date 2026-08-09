from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, utils

from src.retrieve.base import REQUEST_TIMEOUT, USER_AGENT, fetch_and_store
from src.retrieve.models import (
    DiscoveredDocument,
    DocumentRecord,
    MatchType,
    RetrievalIntent,
    SourceTier,
)

HOMEPAGE = "https://www.nqr.gov.in/"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 3

_SECTOR_PATH = "qualifications-search"
_EXACT_SCORE = 99


class NQRAdapter:
    source_id = "NQR"
    tiers = [SourceTier.A]

    def __init__(self, homepage: str = HOMEPAGE):
        self.homepage = homepage
        self._index: Optional[dict[str, str]] = None

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def build_index(self) -> dict[str, str]:
        response = requests.get(
            self.homepage, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        index: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            if _SECTOR_PATH not in link["href"]:
                continue
            sector = link.get_text(" ", strip=True)
            if sector:
                index.setdefault(sector, urljoin(self.homepage, link["href"]))
        return index

    def _ensure_index(self) -> dict[str, str]:
        if self._index is None:
            self._index = self.build_index()
        return self._index

    def resolve(self, intent: RetrievalIntent) -> list[DiscoveredDocument]:
        index = self._ensure_index()
        if not index:
            return []

        scored: list[tuple[int, str]] = []
        for sector in index:
            best = max(
                fuzz.token_set_ratio(term, sector, processor=utils.default_process)
                for term in intent.query_terms
            )
            scored.append((best, sector))

        scored.sort(reverse=True)
        return [
            DiscoveredDocument(
                document_url=index[sector],
                document_title=sector,
                match_confidence=score / 100,
                match_type=MatchType.EXACT if score >= _EXACT_SCORE else MatchType.SEMANTIC,
            )
            for score, sector in scored[:MAX_CANDIDATES]
        ]

    def download(self, document: DiscoveredDocument) -> DocumentRecord:
        return fetch_and_store(
            document,
            source_id=self.source_id,
            source_tier=self.tiers[0],
            raw_dir=RAW_DIR,
            extension="html",
        )
