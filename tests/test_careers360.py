import pytest

from src.retrieve.careers360 import Careers360Adapter

BASE = "https://www.careers360.com/courses/"

FIXTURE_INDEX = {
    "Mechanical Engineering": BASE + "mechanical-engineering-course",
    "Civil Engineering": BASE + "civil-engineering-course",
    "Computer Science": BASE + "computer-science-course",
    "Electrical Engineering": BASE + "electrical-engineering-course",
    "Electronics and Communication": BASE + "electronics-and-communication-engineering-course",
    "Aerospace Engineering": BASE + "aerospace-engineering-course",
    "Aeronautical Engineering": BASE + "aeronautical-engineering-course",
    "Robotics Engineering": BASE + "robotics-engineering-course",
    "Chemical Engineering": BASE + "chemical-engineering-course",
}

PILOT_EXPECTED = [
    ("Mechanical Engineering", "mechanical-engineering-course"),
    ("Civil Engineering", "civil-engineering-course"),
    ("Computer Science Engineering", "computer-science-course"),
    ("Electrical Engineering", "electrical-engineering-course"),
    ("Aerospace Engineering", "aerospace-engineering-course"),
]


@pytest.fixture
def adapter():
    return Careers360Adapter()


@pytest.mark.parametrize("course_name, expected_slug", PILOT_EXPECTED)
def test_pilot_courses_match_expected_page(adapter, course_name, expected_slug):
    result = adapter.match(course_name, FIXTURE_INDEX)
    assert result is not None
    assert result.matched_url.endswith(expected_slug)
    assert result.confidence >= 0.85


def test_aerospace_does_not_match_aeronautical(adapter):
    result = adapter.match("Aerospace Engineering", FIXTURE_INDEX)
    assert result.matched_name == "Aerospace Engineering"


def test_empty_index_returns_none(adapter):
    assert adapter.match("Mechanical Engineering", {}) is None


def test_confidence_is_normalized(adapter):
    result = adapter.match("Mechanical Engineering", FIXTURE_INDEX)
    assert 0.0 <= result.confidence <= 1.0
