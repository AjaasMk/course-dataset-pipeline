from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from coursegen.durations import (
    DurationRegistry,
    DurationRegistryError,
    academic_years_from_duration,
    normalize_course_name,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_TABLE = PROJECT_ROOT / "config" / "durations.json"


def write(tmp_path: Path, table: dict) -> Path:
    path = tmp_path / "durations.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    return path


def test_a_missing_table_resolves_nothing(tmp_path: Path) -> None:
    registry = DurationRegistry.load(tmp_path / "absent.json")
    assert registry.resolve("MBBS") is None


def test_exact_match_wins_over_pattern(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "exact": {"b.ed": {"min_years": 2, "max_years": 2, "academic_years": 2}},
            "patterns": [{"match": r"^b\.", "min_years": 4, "max_years": 4, "academic_years": 4}],
        },
    )
    assert DurationRegistry.load(path).resolve("B.Ed").academic_years == 2


def test_patterns_are_tried_in_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "patterns": [
                {"match": r"^b\.?\s?tech", "min_years": 4, "max_years": 4, "academic_years": 4},
                {"match": r"^b", "min_years": 3, "max_years": 3, "academic_years": 3},
            ]
        },
    )
    assert DurationRegistry.load(path).resolve("B.Tech Civil").academic_years == 4


def test_names_are_matched_case_and_space_insensitively(tmp_path: Path) -> None:
    path = write(tmp_path, {"exact": {"b.ed": {"min_years": 2, "max_years": 2}}})
    registry = DurationRegistry.load(path)
    assert registry.resolve("  B.ED  ") is not None
    assert registry.resolve("B.Ed\tHonours") is None


def test_academic_years_defaults_to_the_span(tmp_path: Path) -> None:
    path = write(tmp_path, {"exact": {"x": {"min_years": 3, "max_years": 4}}})
    assert DurationRegistry.load(path).resolve("x").academic_years == 4


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"min_years": "three", "max_years": 4}, "numeric"),
        ({"min_years": 4, "max_years": 2}, "impossible span"),
        ({"min_years": 0, "max_years": 2}, "impossible span"),
        ({"min_years": 4, "max_years": 4, "academic_years": 0}, "must be an integer"),
        ({"min_years": 4, "max_years": 4, "academic_years": 9}, "must be an integer"),
        ({"min_years": 4, "max_years": 4, "academic_years": 5}, "taught years"),
    ],
)
def test_a_broken_entry_is_rejected_loudly(tmp_path: Path, entry: dict, message: str) -> None:
    path = write(tmp_path, {"exact": {"x": entry}})
    with pytest.raises(DurationRegistryError, match=message):
        DurationRegistry.load(path)


def test_a_pattern_that_is_not_a_regex_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, {"patterns": [{"match": "([unclosed", "min_years": 4, "max_years": 4}]})
    with pytest.raises(DurationRegistryError, match="not a valid expression"):
        DurationRegistry.load(path)


def test_a_control_character_in_a_pattern_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, {"patterns": [{"match": "^bpt\b", "min_years": 4, "max_years": 4}]})
    with pytest.raises(DurationRegistryError, match="control character"):
        DurationRegistry.load(path)


def test_invalid_json_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "durations.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DurationRegistryError, match="not valid JSON"):
        DurationRegistry.load(path)


def test_default_matches_the_old_curriculum_length_formula() -> None:
    assert academic_years_from_duration(3, 3) == 3
    assert academic_years_from_duration(3, 4) == 4
    assert academic_years_from_duration(4, 4.5) == 5
    assert academic_years_from_duration(5.5, 5.5) == 5


def test_normalize_collapses_whitespace() -> None:
    assert normalize_course_name("  B.Tech   Civil  ") == "b.tech civil"
    assert normalize_course_name(None) == ""


def test_the_shipped_table_has_no_escaping_damage() -> None:
    raw = json.loads(LIVE_TABLE.read_text(encoding="utf-8"))
    for rule in raw["patterns"]:
        expression = rule["match"]
        assert not any(ord(c) < 32 for c in expression), f"control character in {expression!r}"
        assert "\\\\" not in expression, f"double-escaped backslash in {expression!r}"
        re.compile(expression)


def test_the_shipped_table_loads() -> None:
    registry = DurationRegistry.load(LIVE_TABLE)
    assert registry.exact and registry.patterns


@pytest.mark.parametrize(
    ("course", "min_years", "max_years", "academic_years"),
    [
        ("MBBS", 5.5, 5.5, 4),
        ("BDS", 5, 5, 4),
        ("BAMS", 5.5, 5.5, 4),
        ("B.Ed", 2, 2, 2),
        ("B.Arch", 5, 5, 5),
        ("B.Tech Computer Science & Engineering", 4, 4, 4),
        ("B.E. Mechanical Engineering", 4, 4, 4),
        ("Bachelor of Physiotherapy", 4.5, 4.5, 4),
        ("Bachelor of Occupational Therapy", 4.5, 4.5, 4),
        ("B.Sc Agriculture", 4, 4, 4),
        ("B.Sc Nursing", 4, 4, 4),
        ("BA English", 3, 4, 4),
        ("B.Com", 3, 4, 4),
        ("BCA", 3, 4, 4),
        ("BA LLB", 5, 5, 5),
        ("LLB", 3, 3, 3),
    ],
)
def test_the_shipped_table_resolves_real_courses(
    course: str, min_years: float, max_years: float, academic_years: int
) -> None:
    found = DurationRegistry.load(LIVE_TABLE).resolve(course)
    assert found is not None, f"{course} should resolve"
    assert (found.min_years, found.max_years) == (min_years, max_years)
    assert found.academic_years == academic_years


def test_courses_with_a_genuinely_variable_length_stay_unpinned() -> None:
    registry = DurationRegistry.load(LIVE_TABLE)
    for course in ("Bachelor of Medical Laboratory Technology", "B.P.Ed"):
        assert registry.resolve(course) is None, f"{course} varies too much to pin"


def test_every_professional_course_shows_fewer_tabs_than_its_length() -> None:
    registry = DurationRegistry.load(LIVE_TABLE)
    for course in ("MBBS", "BDS", "BAMS", "BHMS", "Bachelor of Physiotherapy"):
        found = registry.resolve(course)
        assert found.academic_years < found.max_years, (
            f"{course} ends in an internship, so its taught years must be fewer than its length"
        )


def test_the_shipped_table_covers_most_of_the_client_course_list() -> None:
    from coursegen.courselist import load_course_list

    workbook = PROJECT_ROOT / "docs" / "indian_ug_courses_171.xlsx"
    if not workbook.exists():
        pytest.skip("course list not present")
    registry = DurationRegistry.load(LIVE_TABLE)
    entries = load_course_list(workbook)
    unpinned = [e.course_name for e in entries if registry.resolve(e.course_name) is None]
    assert len(unpinned) / len(entries) < 0.10, f"too many courses unpinned: {unpinned}"


def test_no_pattern_shadows_a_more_specific_one() -> None:
    registry = DurationRegistry.load(LIVE_TABLE)
    specific = {
        "B.Tech Civil Engineering": 4,
        "B.Sc Agriculture": 4,
        "BA LLB": 5,
        "Bachelor of Physiotherapy": 4,
        "Bachelor of Architecture": 5,
    }
    for course, taught in specific.items():
        found = registry.resolve(course)
        assert found is not None and found.academic_years == taught, (
            f"{course} resolved to {found}; an earlier broad pattern is shadowing it"
        )
