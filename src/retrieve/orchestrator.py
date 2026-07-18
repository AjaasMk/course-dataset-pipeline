import logging
from pathlib import Path

import yaml

from src.retrieve.base import SourceAdapter
from src.schema import ManifestEntry, SourceCategory

DEFAULT_CONFIG_PATH = Path("config/sources.yaml")

logger = logging.getLogger(__name__)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_indices(adapters: list[SourceAdapter]) -> dict[SourceAdapter, dict[str, str]]:
    return {adapter: adapter.build_index() for adapter in adapters}


def retrieve_course(
    course_name: str,
    category: str,
    tier_group: str,
    retrieval_order: dict[str, list[str]],
    indices: dict[SourceAdapter, dict[str, str]],
    registry: dict[SourceCategory, dict[str, SourceAdapter]],
    threshold: float,
) -> ManifestEntry | None:
    order = retrieval_order[tier_group]

    for entry in order:
        source_category = SourceCategory(entry)
        category_map = registry.get(source_category, {})
        adapter = category_map.get(category) or category_map.get("*")

        if adapter is None:
            logger.info("No adapter registered for %s (category=%s) — skipping", entry, category)
            continue

        logger.info("Trying %s for %r...", entry, course_name)
        index = indices[adapter]
        match = adapter.match(course_name, index)

        if match is not None and match.confidence >= threshold:
            logger.info("Matched %s at confidence %.2f — downloading", entry, match.confidence)
            return adapter.download(match, tier=category)

        confidence_display = f"{match.confidence:.2f}" if match is not None else "n/a"
        logger.info(
            "No match / confidence %s below threshold %.2f for %s — falling through",
            confidence_display, threshold, entry,
        )

    logger.info("Exhausted retrieval_order for %s — no source found for %r", tier_group, course_name)
    return None


def default_registry(
    aicte_adapter: SourceAdapter, careers360_adapter: SourceAdapter
) -> dict[SourceCategory, dict[str, SourceAdapter]]:
    return {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
    }


if __name__ == "__main__":
    from src.retrieve.aicte import AICTEAdapter
    from src.retrieve.careers360 import Careers360Adapter

    TEST_COURSES = [
        "Mechanical Engineering",
        "Civil Engineering",
        "Computer Science Engineering",
        "Electrical Engineering",
        "Aerospace Engineering",
    ]

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = load_config()
    retrieval_order = config["retrieval_order"]
    threshold = config["matching"]["threshold"]

    aicte_adapter = AICTEAdapter()
    careers360_adapter = Careers360Adapter()

    registry = default_registry(aicte_adapter, careers360_adapter)

    print("Building indices...")
    indices = build_indices([aicte_adapter, careers360_adapter])
    print(f"AICTE index: {len(indices[aicte_adapter])} entries")
    print(f"Careers360 index: {len(indices[careers360_adapter])} entries\n")

    for course in TEST_COURSES:
        print(f"--- {course} ---")
        result = retrieve_course(
            course_name=course,
            category="engineering",
            tier_group="strong_tier",
            retrieval_order=retrieval_order,
            indices=indices,
            registry=registry,
            threshold=threshold,
        )
        if result is None:
            print("  -> NO SOURCE FOUND\n")
        else:
            print(f"  -> source_type: {result.source_type.value}")
            print(f"     local_path:  {result.local_path}")
            print(f"     confidence:  {result.match_confidence:.2f}\n")
