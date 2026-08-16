from __future__ import annotations

from pathlib import Path

import pytest

from coursegen.courselist import (
    CourseListError,
    categories,
    iter_entries,
    load_course_list,
    slugify,
)
from coursegen.domains import DomainRegistry

WORKBOOK = Path(__file__).resolve().parents[1] / "docs" / "indian_ug_courses_171.xlsx"
DOMAINS = Path(__file__).resolve().parents[1] / "config" / "domains.json"

pytestmark = pytest.mark.skipif(not WORKBOOK.exists(), reason="course list workbook not present")


@pytest.fixture(scope="module")
def entries():
    return load_course_list(WORKBOOK)


def test_loads_every_distinct_course(entries) -> None:
    assert len(entries) == 166
    assert len(categories(entries)) == 16


def test_ids_and_slugs_are_unique_and_within_schema_bounds(entries) -> None:
    ids = [e.course_id for e in entries]
    slugs = [e.slug for e in entries]
    assert len(set(ids)) == len(ids)
    assert len(set(slugs)) == len(slugs)
    for entry in entries:
        assert 1 <= len(entry.course_id) <= 64
        assert 3 <= len(entry.slug) <= 80
        assert entry.slug == slugify(entry.slug)


def test_course_names_satisfy_the_schema(entries) -> None:
    for entry in entries:
        assert 3 <= len(entry.course_name) <= 90
        assert entry.course_name == entry.course_name.strip()
        assert "\n" not in entry.course_name
        assert all(ord(ch) < 128 for ch in entry.course_name), entry.course_name


def test_multi_category_courses_collapse_to_one_entry(entries) -> None:
    multi = {e.course_name: e for e in entries if len(e.categories) > 1}
    assert set(multi) == {
        "B.Tech Agricultural Engineering",
        "BA Journalism & Mass Communication",
        "B.Sc Computer Science",
        "B.Sc Data Science",
        "BBA Finance",
    }
    for entry in multi.values():
        assert entry.category == entry.categories[0]
        assert len(set(entry.categories)) == len(entry.categories)


def test_every_category_has_a_domain_entry(entries) -> None:
    declared = set(DomainRegistry.load(DOMAINS).disciplines())
    missing = sorted({e.discipline for e in entries} - declared)
    assert missing == [], f"categories with no config/domains.json entry: {missing}"


def test_filtering_by_discipline_matches_any_of_its_categories(entries) -> None:
    agri = list(iter_entries(entries, discipline="Agriculture & Veterinary"))
    names = {e.course_name for e in agri}
    assert "B.Tech Agricultural Engineering" in names
    assert len(agri) == 9


def test_limit_is_respected(entries) -> None:
    assert len(list(iter_entries(entries, limit=5))) == 5


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CourseListError, match="not found"):
        load_course_list(tmp_path / "nope.xlsx")


def test_wrong_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "courses.csv"
    path.write_text("Category,Course Name\n", encoding="utf-8")
    with pytest.raises(CourseListError, match="expected an .xlsx"):
        load_course_list(path)


def test_missing_headers_raise(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "bad.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Stream", "Programme"])
    workbook.active.append(["Science", "B.Sc Physics"])
    workbook.save(path)
    with pytest.raises(CourseListError, match="must have"):
        load_course_list(path)


def test_dashes_and_whitespace_are_normalised(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "dashes.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Category", "Course Name"])
    workbook.active.append(["Hotel  Management", "BTTM — Bachelor of  Travel"])
    workbook.save(path)
    entry = load_course_list(path)[0]
    assert entry.course_name == "BTTM - Bachelor of Travel"
    assert entry.category == "Hotel Management"
