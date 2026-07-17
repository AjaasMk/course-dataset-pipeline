from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, utils

from src.retrieve.base import SourceMatch
from src.schema import SourceCategory

LISTING_PAGE = "https://www.careers360.com/courses"
USER_AGENT = "course-dataset-pipeline/0.1 (educational course dataset project)"
REQUEST_TIMEOUT = 15

CATEGORY = SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED


def _is_course_page(url: str) -> bool:
    segments = [s for s in urlparse(url).path.split("/") if s]
    return len(segments) == 2 and segments[0] == "courses"


class Careers360Adapter:
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
            text = link.get_text(strip=True)
            if not text:
                continue
            url = urljoin(self.listing_page, link["href"])
            if not _is_course_page(url):
                continue
            index.setdefault(text, url)
        return index

    def match(self, course_name: str, index: dict[str, str]) -> SourceMatch | None:
        if not index:
            return None

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

    def download(self, match: SourceMatch):
        raise NotImplementedError


if __name__ == "__main__":
    TEST_COURSES = [
        "Mechanical Engineering",
        "Civil Engineering",
        "Computer Science Engineering",
        "Electrical Engineering",
        "Aerospace Engineering",
    ]

    adapter = Careers360Adapter()
    print(f"Crawling {LISTING_PAGE} ...")
    index = adapter.build_index()
    print(f"Index built: {len(index)} candidate courses\n")

    for course in TEST_COURSES:
        result = adapter.match(course, index)
        print(f"{course!r}")
        if result is None:
            print("  -> NO MATCH (empty index)")
        else:
            print(f"  -> matched:    {result.matched_name!r}")
            print(f"     url:        {result.matched_url}")
            print(f"     confidence: {result.confidence:.2f}")
        print()
