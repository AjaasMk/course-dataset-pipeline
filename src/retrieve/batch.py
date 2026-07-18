import re
from typing import Literal, Optional

from pydantic import BaseModel

from src.schema import SourceType


def normalize_course_name(raw_name: str) -> str:
    """Normalize course name by stripping trailing parentheses and taking segment before slash.

    Args:
        raw_name: The raw course name to normalize

    Returns:
        The normalized course name
    """
    name = re.sub(r"\s*\([^)]*\)\s*$", "", raw_name).strip()
    if "/" in name:
        name = name.split("/")[0].strip()
    return name


_SOURCE_TYPE_TO_CATEGORY = {
    SourceType.REGULATOR_PDF: "regulatory_primary",
    SourceType.REGULATOR_WEBPAGE: "regulatory_primary",
    SourceType.AGGREGATOR_WEBPAGE: "fact_supplement_independent_writing_required",
}


def infer_source_category(source_type: SourceType) -> str:
    """Infer source category from source type.

    Args:
        source_type: The SourceType enum value

    Returns:
        The inferred source category string
    """
    return _SOURCE_TYPE_TO_CATEGORY.get(source_type, "unknown")


class CourseResult(BaseModel):
    """Result of processing a single course."""
    raw_name: str
    course_name: str
    category: str
    tier_group: str
    outcome: Literal["matched", "no_source_found", "errored"]
    source_category: Optional[str] = None
    error: Optional[str] = None


class TierSummary(BaseModel):
    """Summary statistics for a single tier."""
    matched_by_source: dict[str, int]
    no_source_found: int
    errored: int


class BatchReport(BaseModel):
    """Complete batch processing report."""
    results: list[CourseResult]
    summary_by_tier: dict[str, TierSummary]
