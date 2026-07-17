from typing import Protocol

from pydantic import BaseModel

from src.schema import ManifestEntry


class SourceMatch(BaseModel):
    course_name: str  # the input we matched against
    matched_name: str  # the branch/programme name found in the index
    matched_url: str
    confidence: float  # 0.0-1.0, normalized from rapidfuzz's 0-100 scale


class SourceAdapter(Protocol):
    def build_index(self) -> dict[str, str]:
        """Crawl the regulator listing page. Returns {branch_name: doc_url}."""
        ...

    def match(self, course_name: str, index: dict[str, str]) -> SourceMatch | None:
        """Fuzzy-match course_name against index.

        Returns None only if index is empty. Otherwise always returns the
        best candidate found, however low-confidence — accepting or
        rejecting that confidence is the caller's decision, not the
        adapter's.
        """
        ...

    def download(self, match: SourceMatch) -> ManifestEntry:
        """Not implemented yet."""
        ...
