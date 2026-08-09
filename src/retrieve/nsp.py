import re
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

SCHEMES_PAGE = "https://scholarships.gov.in/All-Scholarships"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 5
ANCESTOR_DEPTH = 4

_SPEC_LABEL = "specifications"
_OPEN_MARKER = re.compile(r"\s*Scheme\s*Open from.*$|\s*Open from.*$", re.I | re.S)
# A scheme not yet open for the current cycle uses a different status
# template than "Scheme Open from : <date>" -- confirmed live 2026-08-09,
# this was leaking straight into the index and polluting several real
# scheme titles (e.g. "National Scholarship For Post Graduate Studies")
# with ~200 chars of "X : NOT YET OPENED" boilerplate.
_NOT_YET_OPENED_MARKER = re.compile(r"\s*Scheme\s*:\s*NOT YET OPENED.*$", re.I | re.S)
_TRAILING_SCHEME = re.compile(r"\s+Scheme\s*$", re.I)
_MIN_BLOCK_CHARS = 40
_EXACT_SCORE = 99


def scheme_name_from_block(text: str) -> str:
    name = " ".join(text.split())
    name = _OPEN_MARKER.sub("", name)
    name = _NOT_YET_OPENED_MARKER.sub("", name)
    return _TRAILING_SCHEME.sub("", name).strip()


class NSPAdapter:
    source_id = "NSP"
    tiers = [SourceTier.A]

    def __init__(self, schemes_page: str = SCHEMES_PAGE):
        self.schemes_page = schemes_page
        self._index: Optional[dict[str, str]] = None

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def build_index(self) -> dict[str, str]:
        response = requests.get(
            self.schemes_page, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        index: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            if link.get_text(" ", strip=True).lower() != _SPEC_LABEL:
                continue
            # NSP labels every scheme document "Specifications"; the scheme name
            # lives in an ancestor block alongside its open/close dates.
            node = link
            for _ in range(ANCESTOR_DEPTH):
                node = node.parent
                if node is None:
                    break
                block = node.get_text(" ", strip=True)
                if len(block) >= _MIN_BLOCK_CHARS:
                    name = scheme_name_from_block(block)
                    if name:
                        index.setdefault(name, urljoin(self.schemes_page, link["href"]))
                    break
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
        for name in index:
            best = max(
                fuzz.token_set_ratio(term, name, processor=utils.default_process)
                for term in intent.query_terms
            )
            scored.append((best, name))

        scored.sort(reverse=True)
        return [
            DiscoveredDocument(
                document_url=index[name],
                document_title=name,
                match_confidence=score / 100,
                match_type=MatchType.EXACT if score >= _EXACT_SCORE else MatchType.FUZZY,
            )
            for score, name in scored[:MAX_CANDIDATES]
        ]

    def download(self, document: DiscoveredDocument) -> DocumentRecord:
        return fetch_and_store(
            document,
            source_id=self.source_id,
            source_tier=self.tiers[0],
            raw_dir=RAW_DIR,
            extension="pdf",
        )
