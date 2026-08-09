import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin

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

REGULATIONS_PAGE = "https://www.ugc.gov.in/regulations"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 5

_UPLOAD_PREFIX = re.compile(r"^\d+[_-]")
_SEPARATORS = re.compile(r"[-_]+")
_HASH_NAME = re.compile(r"^[0-9a-f]{16,}$", re.I)
_EXACT_SCORE = 99


def is_meaningful_title(title: str) -> bool:
    return bool(title) and not _HASH_NAME.match(title.replace(" ", ""))


def title_from_filename(filename: str) -> str:
    name = unquote(filename).rsplit("/", 1)[-1]
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    name = _UPLOAD_PREFIX.sub("", name)
    return _SEPARATORS.sub(" ", name).strip()


class UGCAdapter:
    source_id = "UGC"
    tiers = [SourceTier.A]

    def __init__(self, regulations_page: str = REGULATIONS_PAGE):
        self.regulations_page = regulations_page
        self._index: Optional[dict[str, str]] = None

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def build_index(self) -> dict[str, str]:
        response = requests.get(
            self.regulations_page,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        index: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.lower().split("?")[0].endswith(".pdf"):
                continue
            # UGC labels almost every regulation link "View"; the document name
            # only exists in the uploaded filename, behind a numeric upload id.
            title = title_from_filename(href)
            if not is_meaningful_title(title):
                continue
            index.setdefault(title, urljoin(self.regulations_page, href))
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
            extension="pdf",
        )
