import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

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

HOMEPAGE = "https://www.nta.ac.in/"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 3

_EXAM_HOST = re.compile(r"\.nta\.nic\.in", re.I)
_EXACT_SCORE = 99

# NTA gives each examination its own portal, but the link labels are the formal
# expansions ("National Eligibility Cum Entrance Test"), not the names a course
# is described by. These aliases carry the discipline and acronym vocabulary the
# planner's query_terms actually use.
_EXAM_ALIASES = {
    "jeemain": ["jee", "jee main", "engineering", "btech", "b.e.", "technology", "architecture"],
    "neet": ["neet", "medical", "medicine", "mbbs", "bds", "dental", "nursing", "ayush"],
    "cuet": ["cuet", "university", "arts", "science", "humanities", "commerce", "psychology"],
    "cmat": ["cmat", "management", "mba", "bba", "business administration"],
    "ugcnet": ["ugc net", "lectureship", "assistant professor", "research fellowship"],
    "csirnet": ["csir", "science research", "junior research fellowship"],
    "icar": ["icar", "agriculture", "agricultural", "horticulture", "veterinary"],
    "nchm-jee": ["hotel management", "hospitality", "culinary", "catering", "nchm"],
    "swayam": ["swayam", "online course", "mooc"],
}


def _exam_key(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.endswith("exams.nta.nic.in"):
        segments = [s for s in parsed.path.split("/") if s]
        return segments[0].lower() if segments else ""
    return host.split(".")[0].lower()


class NTAAdapter:
    source_id = "NTA"
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
            url = urljoin(self.homepage, link["href"])
            if not _EXAM_HOST.search(urlparse(url).hostname or ""):
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue
            index.setdefault(title, url)
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
        for title, url in index.items():
            vocabulary = _EXAM_ALIASES.get(_exam_key(url), []) + [title]
            best = max(
                fuzz.token_set_ratio(term, word, processor=utils.default_process)
                for term in intent.query_terms
                for word in vocabulary
            )
            scored.append((best, title))

        scored.sort(reverse=True)
        return [
            DiscoveredDocument(
                document_url=index[title],
                document_title=title,
                match_confidence=score / 100,
                match_type=MatchType.EXACT if score >= _EXACT_SCORE else MatchType.SEMANTIC,
            )
            for score, title in scored[:MAX_CANDIDATES]
        ]

    def download(self, document: DiscoveredDocument) -> DocumentRecord:
        return fetch_and_store(
            document,
            source_id=self.source_id,
            source_tier=self.tiers[0],
            raw_dir=RAW_DIR,
            extension="html",
        )
