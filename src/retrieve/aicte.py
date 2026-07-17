import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, utils

from src.retrieve import manifest
from src.retrieve.base import SourceMatch
from src.schema import ManifestEntry, SourceType

LISTING_PAGE = "https://www.aicte.gov.in/education/model-syllabus"
USER_AGENT = "course-dataset-pipeline/0.1 (educational course dataset project)"
REQUEST_TIMEOUT = 15
RAW_DIR = Path("data/raw")


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class AICTEAdapter:
    SOURCE_TYPE = SourceType.REGULATOR_PDF

    def __init__(self, listing_page: str = LISTING_PAGE):
        self.listing_page = listing_page

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

    def match(self, course_name: str, index: dict[str, str]) -> SourceMatch | None:
        if not index:
            return None

        # token_set_ratio finds candidates whose title contains the query's
        # words (AICTE titles are full sentences, e.g. "Revised Model
        # Curriculum for UG Degree Course in Mechanical Engineering"), but it
        # doesn't penalize a candidate for having *extra* words beyond the
        # query — so a specialization variant (e.g. "...Computer Science and
        # Engineering Artificial Intelligence and Data Science(AI&DS)") scores
        # identically to the plain branch it's a variant of. Break ties by
        # preferring the candidate closest in length to the query — the more
        # specific, less-qualified document.
        scored = [
            (
                fuzz.token_set_ratio(course_name, name, processor=utils.default_process),
                -abs(len(name) - len(course_name)),
                name,
            )
            for name in index
        ]
        _, _, matched_name = max(scored)
        score = fuzz.token_set_ratio(course_name, matched_name, processor=utils.default_process)

        return SourceMatch(
            course_name=course_name,
            matched_name=matched_name,
            matched_url=index[matched_name],
            confidence=score / 100,
        )

    def download(self, match: SourceMatch, tier: str) -> ManifestEntry:
        existing = manifest.get_entry(match.course_name, match.matched_url)
        if existing is not None:
            return existing

        response = requests.get(
            match.matched_url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        local_path = RAW_DIR / tier / self.SOURCE_TYPE.value / f"{_slugify(match.course_name)}.pdf"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(response.content)

        content_length_header = response.headers.get("Content-Length")

        entry = ManifestEntry(
            course_name=match.course_name,
            tier=tier,
            source_type=self.SOURCE_TYPE,
            matched_url=match.matched_url,
            local_path=str(local_path),
            file_hash=hashlib.sha256(response.content).hexdigest(),
            match_confidence=match.confidence,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            content_type=response.headers.get("Content-Type"),
            content_length=int(content_length_header) if content_length_header is not None else None,
            http_status=response.status_code,
        )
        manifest.insert_entry(entry)
        return entry


if __name__ == "__main__":
    TEST_COURSES = [
        "Mechanical Engineering",
        "Civil Engineering",
        "Computer Science Engineering",
        "Electrical Engineering",
        "Aerospace Engineering",
    ]

    adapter = AICTEAdapter()
    print(f"Crawling {LISTING_PAGE} ...")
    index = adapter.build_index()
    print(f"Index built: {len(index)} candidate documents\n")

    for course in TEST_COURSES:
        result = adapter.match(course, index)
        print(f"{course!r}")
        if result is None:
            print("  -> NO MATCH (empty index)")
        else:
            print(f"  -> matched: {result.matched_name!r}")
            print(f"     url:        {result.matched_url}")
            print(f"     confidence: {result.confidence:.2f}")
        print()
