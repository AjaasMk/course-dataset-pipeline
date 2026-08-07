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

BASE_URL = "https://www.nirfindia.org/"
RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 3

_YEAR_HREF = re.compile(r"/Rankings/(\d{4})/Ranking", re.I)
_CATEGORY_HREF = re.compile(r"([A-Za-z]+)Ranking\.html$", re.I)
_EXACT_SCORE = 99

# NIRF publishes one ranking table per discipline, but its category labels are not
# the words a course is described with -- nothing in "Mechanical Engineering"
# matches "Engineering" more strongly than it matches "Management" under a plain
# token ratio. These aliases carry the discipline vocabulary the planner's
# query_terms actually use.
_CATEGORY_ALIASES = {
    "Overall": ["overall", "general"],
    "University": ["university", "arts", "science", "humanities", "commerce"],
    "College": ["college", "undergraduate"],
    "Research": ["research", "doctoral", "phd"],
    "Engineering": ["engineering", "technology", "btech", "be", "computing", "mechanical"],
    "Management": ["management", "business", "mba", "bba", "commerce", "finance"],
    "Pharmacy": ["pharmacy", "pharmaceutical", "pharm"],
    "Medical": ["medical", "medicine", "mbbs", "surgery", "clinical"],
    "Dental": ["dental", "dentistry", "bds"],
    "Law": ["law", "legal", "llb", "juridical"],
    "Architecture": ["architecture", "planning", "barch"],
    "Agriculture": ["agriculture", "agricultural", "farming", "horticulture"],
    "Innovation": ["innovation", "entrepreneurship"],
    "OPENUNIVERSITY": ["open university", "distance"],
    "SKILLUNIVERSITY": ["skill", "vocational"],
    "STATEPUBLICUNIVERSITY": ["state public university"],
    "SDGInstitutions": ["sustainability", "sdg"],
}


def _prettify(category: str) -> str:
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", category)
    return spaced if spaced.isupper() or " " in spaced else spaced.title()


class NIRFAdapter:
    source_id = "NIRF"
    tiers = [SourceTier.A]

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self._index: Optional[tuple[str, dict[str, str]]] = None

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def _get_soup(self, url: str) -> BeautifulSoup:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    def latest_year_url(self) -> tuple[str, str]:
        soup = self._get_soup(self.base_url)
        years: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            found = _YEAR_HREF.search(link["href"])
            if found:
                years.setdefault(found.group(1), urljoin(self.base_url, link["href"]))
        if not years:
            return "", ""
        latest = max(years)
        return latest, years[latest]

    def build_index(self) -> tuple[str, dict[str, str]]:
        year, year_url = self.latest_year_url()
        if not year_url:
            return "", {}

        soup = self._get_soup(year_url)
        categories: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            found = _CATEGORY_HREF.search(link["href"])
            if found:
                categories.setdefault(found.group(1), urljoin(year_url, link["href"]))
        return year, categories

    def _ensure_index(self) -> tuple[str, dict[str, str]]:
        if self._index is None:
            self._index = self.build_index()
        return self._index

    def resolve(self, intent: RetrievalIntent) -> list[DiscoveredDocument]:
        year, categories = self._ensure_index()
        if not categories:
            return []

        scored: list[tuple[int, str]] = []
        for category, url in categories.items():
            vocabulary = _CATEGORY_ALIASES.get(category, []) + [category]
            best = max(
                fuzz.token_set_ratio(term, word, processor=utils.default_process)
                for term in intent.query_terms
                for word in vocabulary
            )
            scored.append((best, category))

        scored.sort(reverse=True)
        return [
            DiscoveredDocument(
                document_url=categories[category],
                document_title=f"NIRF {year} {_prettify(category)} Ranking",
                match_confidence=score / 100,
                match_type=MatchType.EXACT if score >= _EXACT_SCORE else MatchType.SEMANTIC,
                academic_year=year,
            )
            for score, category in scored[:MAX_CANDIDATES]
        ]

    def download(self, document: DiscoveredDocument) -> DocumentRecord:
        return fetch_and_store(
            document,
            source_id=self.source_id,
            source_tier=self.tiers[0],
            raw_dir=RAW_DIR,
            extension="html",
        )
