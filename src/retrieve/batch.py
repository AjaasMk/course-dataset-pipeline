import logging
import re
import time
from typing import Literal, Optional

from pydantic import BaseModel

from src.retrieve.base import SourceAdapter
from src.retrieve.orchestrator import retrieve_course
from src.schema import SourceCategory, SourceType

logger = logging.getLogger(__name__)


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
    SourceType.GENERAL_BACKGROUND_WEBPAGE: "general_background",
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


def run_batch(
    courses: list[dict],
    categories: dict[str, str],
    retrieval_order: dict[str, list[str]],
    indices: dict[SourceAdapter, dict[str, str]],
    registry: dict[SourceCategory, dict[str, SourceAdapter]],
    threshold: float,
    delay_seconds: float = 1.0,
) -> BatchReport:
    """Run retrieval for a batch of courses, isolating per-course failures.

    Each course is processed independently: an exception raised by
    `retrieve_course()` is caught, logged, and recorded as an "errored"
    outcome — the loop always continues to the next course rather than
    aborting the batch. A fixed delay is applied after every course
    (matched, no_source_found, or errored) for rate limiting.

    Args:
        courses: list of {"raw_name": str, "category": str} dicts.
        categories: maps a course's `category` to its tier group (e.g.
            "engineering" -> "strong_tier").
        retrieval_order: per-tier-group ordered list of source categories
            to try, passed through to `retrieve_course()`.
        indices: per-adapter {branch_name: doc_url} indices, passed through
            to `retrieve_course()`.
        registry: maps source category -> {course category: adapter},
            passed through to `retrieve_course()`.
        threshold: minimum match confidence to accept, passed through to
            `retrieve_course()`.
        delay_seconds: fixed delay (seconds) applied after each course.

    Returns:
        A BatchReport with one CourseResult per course and a summary
        stratified by tier group.
    """
    results: list[CourseResult] = []

    for course in courses:
        raw_name = course["raw_name"]
        category = course["category"]
        tier_group = categories[category]
        course_name = normalize_course_name(raw_name)

        try:
            entry = retrieve_course(
                course_name=course_name,
                category=category,
                tier_group=tier_group,
                retrieval_order=retrieval_order,
                indices=indices,
                registry=registry,
                threshold=threshold,
            )
        except Exception as exc:
            logger.info("Course %r errored: %s", raw_name, exc)
            results.append(
                CourseResult(
                    raw_name=raw_name,
                    course_name=course_name,
                    category=category,
                    tier_group=tier_group,
                    outcome="errored",
                    error=str(exc),
                )
            )
            time.sleep(delay_seconds)
            continue

        if entry is None:
            results.append(
                CourseResult(
                    raw_name=raw_name,
                    course_name=course_name,
                    category=category,
                    tier_group=tier_group,
                    outcome="no_source_found",
                )
            )
        else:
            results.append(
                CourseResult(
                    raw_name=raw_name,
                    course_name=course_name,
                    category=category,
                    tier_group=tier_group,
                    outcome="matched",
                    source_category=infer_source_category(entry.source_type),
                )
            )

        time.sleep(delay_seconds)

    return BatchReport(results=results, summary_by_tier=_summarize(results))


def _summarize(results: list[CourseResult]) -> dict[str, TierSummary]:
    """Aggregate per-course results into a TierSummary per tier group."""
    summary: dict[str, TierSummary] = {}
    for result in results:
        tier_summary = summary.setdefault(
            result.tier_group,
            TierSummary(matched_by_source={}, no_source_found=0, errored=0),
        )
        if result.outcome == "matched":
            key = result.source_category or "unknown"
            tier_summary.matched_by_source[key] = tier_summary.matched_by_source.get(key, 0) + 1
        elif result.outcome == "no_source_found":
            tier_summary.no_source_found += 1
        elif result.outcome == "errored":
            tier_summary.errored += 1
    return summary


if __name__ == "__main__":
    from pathlib import Path

    from src.retrieve.aicte import AICTEAdapter
    from src.retrieve.careers360 import Careers360Adapter
    from src.retrieve.orchestrator import build_indices, default_registry, load_config
    from src.retrieve.wikipedia import WikipediaAdapter

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = load_config()
    retrieval_order = config["retrieval_order"]
    threshold = config["matching"]["threshold"]
    categories = config["categories"]

    pilot_config = load_config(path=Path("config/pilot_courses.yaml"))
    courses = pilot_config["courses"]

    aicte_adapter = AICTEAdapter()
    careers360_adapter = Careers360Adapter()
    wikipedia_adapter = WikipediaAdapter()
    registry = default_registry(aicte_adapter, careers360_adapter, wikipedia_adapter)

    print("Building indices...")
    indices = build_indices([aicte_adapter, careers360_adapter, wikipedia_adapter])
    print(f"AICTE index: {len(indices[aicte_adapter])} entries")
    print(f"Careers360 index: {len(indices[careers360_adapter])} entries")
    print(f"Wikipedia index: {len(indices[wikipedia_adapter])} entries (always empty — no listing page)\n")

    print(f"Running batch for {len(courses)} courses (this will take a few minutes)...\n")
    report = run_batch(
        courses=courses,
        categories=categories,
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=threshold,
    )

    report_path = Path("data/pilot_run_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nReport written to {report_path}\n")

    print("=== Summary by tier ===")
    for tier_group, summary in report.summary_by_tier.items():
        print(f"{tier_group}:")
        for source, count in summary.matched_by_source.items():
            print(f"  matched via {source}: {count}")
        print(f"  no_source_found: {summary.no_source_found}")
        print(f"  errored: {summary.errored}")
