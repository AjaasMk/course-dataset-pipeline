import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from rapidfuzz import fuzz, utils

from src.retrieve import manifest
from src.retrieve.base import SourceMatch
from src.schema import ManifestEntry, SourceType

SEARCH_API = "https://en.wikipedia.org/w/rest.php/v1/search/page"
ARTICLE_BASE_URL = "https://en.wikipedia.org/wiki/"
USER_AGENT = "course-dataset-pipeline/0.1 (educational course dataset project)"
REQUEST_TIMEOUT = 15
SEARCH_LIMIT = 5

RAW_DIR = Path("data/raw")

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class WikipediaAdapter:
    SOURCE_TYPE = SourceType.GENERAL_BACKGROUND_WEBPAGE

    def build_index(self) -> dict[str, str]:
        return {}

    def match(self, course_name: str, index: dict[str, str]) -> SourceMatch | None:
        response = requests.get(
            SEARCH_API,
            params={"q": course_name, "limit": SEARCH_LIMIT},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        pages = response.json().get("pages", [])

        if not pages:
            return None

        scored = []
        for page in pages:
            title = page["title"]
            excerpt = _strip_html(page.get("excerpt", ""))
            title_score = fuzz.token_set_ratio(course_name, title, processor=utils.default_process)
            excerpt_score = fuzz.token_set_ratio(course_name, excerpt, processor=utils.default_process)
            scored.append((max(title_score, excerpt_score), page))

        best_score, best_page = max(scored, key=lambda item: item[0])

        return SourceMatch(
            course_name=course_name,
            matched_name=best_page["title"],
            matched_url=ARTICLE_BASE_URL + best_page["key"],
            confidence=best_score / 100,
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

        local_path = RAW_DIR / tier / self.SOURCE_TYPE.value / f"{_slugify(match.course_name)}.html"
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
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    TEST_COURSES = [
        "Marketing",
        "Accounting",
        "Cybersecurity",
        "Software Engineering",
        "Marine Engineering",
    ]

    adapter = WikipediaAdapter()
    print("WikipediaAdapter has no listing page to crawl — build_index() is a no-op:")
    print(f"  build_index() -> {adapter.build_index()!r}\n")

    for course in TEST_COURSES:
        print(f"--- {course} ---")
        match = adapter.match(course, {})
        if match is None:
            print("  -> NO MATCH (search API returned zero results)\n")
            continue
        print(f"  -> matched: {match.matched_name!r}")
        print(f"     url:        {match.matched_url}")
        print(f"     confidence: {match.confidence:.2f}")
        if match.confidence >= 0.80:
            entry = adapter.download(match, tier="engineering")
            print(f"     downloaded: {entry.local_path}")
            print(f"     hash:       {entry.file_hash}")
        else:
            print("     (below 0.80 threshold — retrieve_course() would fall through, not download this)")
        print()
