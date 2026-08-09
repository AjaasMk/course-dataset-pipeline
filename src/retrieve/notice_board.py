import re
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urljoin, urlparse

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
from src.retrieve.tls import verify_arg

RAW_DIR = Path("data/raw")
MAX_CANDIDATES = 5
DOCUMENT_SUFFIXES = (".pdf",)

_SEPARATORS = re.compile(r"[-_]+")
_OPAQUE_NAME = re.compile(r"^\d[\d\s]*$")
_EXACT_SCORE = 99


def title_from_filename(href: str) -> str:
    name = unquote(href).rsplit("/", 1)[-1]
    name = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    return _SEPARATORS.sub(" ", name).strip()


def is_usable_title(title: str) -> bool:
    # Uploads are named with a timestamp on these sites, so a filename-derived
    # title that is only digits carries nothing to match against.
    return bool(title) and not _OPAQUE_NAME.match(title)


class NoticeBoardAdapter:
    """Adapter for official notice-board sites that publish documents as a flat
    list of links, where the anchor text is the label and the uploaded filename
    is an opaque id. Confirmed live for CUET, JoSAA and CSAB, which share this
    shape exactly. Contrast UGC, where the anchor says "View" and the filename
    holds the name -- that inversion is why this is a separate adapter rather
    than a generalisation of the existing one.
    """

    def __init__(
        self,
        source_id: str,
        tiers: list[SourceTier],
        listing_page: str,
        document_suffixes: tuple[str, ...] = DOCUMENT_SUFFIXES,
        fetch_html: Optional[Callable[[str], str]] = None,
        exclude_url_patterns: Optional[list[str]] = None,
    ):
        self.source_id = source_id
        self.tiers = tiers
        self.listing_page = listing_page
        self.document_suffixes = document_suffixes
        # Sources whose documents only exist after JavaScript runs share this
        # logic entirely; only the fetch differs, so it is injected rather than
        # duplicated into a parallel adapter.
        self.fetch_html = fetch_html
        # Some notice boards mix genuine regulatory content with unrelated
        # material under a distinct URL path -- COA's real site puts
        # continuing-education webinar/FDP posters under /event/ alongside
        # actual circulars under /notification/, and the posters' topical
        # titles ("Symphonies in Architecture") fuzzy-match course names
        # despite being unrelated to any course's curriculum or eligibility.
        # Optional and empty by default -- every other source using this
        # class is unaffected unless explicitly configured otherwise.
        self.exclude_url_patterns = exclude_url_patterns or []
        self._index: Optional[dict[str, str]] = None

    def _get_html(self) -> str:
        if self.fetch_html is not None:
            return self.fetch_html(self.listing_page)

        host = urlparse(self.listing_page).hostname or ""
        response = requests.get(
            self.listing_page,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            verify=verify_arg(host),
        )
        response.raise_for_status()
        return response.text

    def supports(self, intent: RetrievalIntent) -> bool:
        return intent.source_id == self.source_id

    def build_index(self) -> dict[str, str]:
        soup = BeautifulSoup(self._get_html(), "html.parser")

        index: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.lower().split("?")[0].endswith(self.document_suffixes):
                continue
            if any(pattern in href for pattern in self.exclude_url_patterns):
                continue
            title = link.get_text(" ", strip=True) or title_from_filename(href)
            if not is_usable_title(title):
                continue
            index.setdefault(title, urljoin(self.listing_page, href))
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
        # Confirmed live 2026-08-09: _get_html() above already repairs an
        # incomplete TLS chain via verify_arg() for the listing-page fetch,
        # but this download path never did -- so a source's homepage
        # loaded fine (CEE_KERALA) while every real document download from
        # the same host failed with the exact same certificate error.
        host = urlparse(document.document_url).hostname or ""
        return fetch_and_store(
            document,
            source_id=self.source_id,
            source_tier=self.tiers[0],
            raw_dir=RAW_DIR,
            extension="pdf",
            verify=verify_arg(host),
        )
