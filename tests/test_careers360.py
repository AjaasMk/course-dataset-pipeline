import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.retrieve.careers360 import Careers360Adapter
from src.schema import SourceType

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


HTML_BYTES = b"<html><body>Mechanical Engineering course page</body></html>"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.manifest.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.careers360.RAW_DIR", tmp_path / "raw")


def _mock_response(content=HTML_BYTES, status_code=200, content_type="text/html; charset=utf-8"):
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.careers360.requests.get")
def test_download_writes_html_file_and_manifest_entry(mock_get, adapter):
    mock_get.return_value = _mock_response()
    match = adapter.match("Mechanical Engineering", FIXTURE_INDEX)

    entry = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert entry.source_type == SourceType.AGGREGATOR_WEBPAGE
    assert entry.http_status == 200
    assert entry.content_type == "text/html; charset=utf-8"
    assert entry.content_length == len(HTML_BYTES)
    assert entry.file_hash == hashlib.sha256(HTML_BYTES).hexdigest()
    assert Path(entry.local_path).read_bytes() == HTML_BYTES
    assert Path(entry.local_path).suffix == ".html"


@patch("src.retrieve.careers360.requests.get")
def test_second_download_for_same_course_and_url_skips_http_call(mock_get, adapter):
    mock_get.return_value = _mock_response()
    match = adapter.match("Mechanical Engineering", FIXTURE_INDEX)

    first = adapter.download(match, tier="engineering")
    second = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert second == first


@patch("src.retrieve.careers360.requests.get")
def test_http_failure_propagates_and_writes_no_manifest_entry(mock_get, adapter):
    match = adapter.match("Mechanical Engineering", FIXTURE_INDEX)
    response = _mock_response(status_code=403)
    response.raise_for_status.side_effect = Exception("403 Client Error")
    mock_get.return_value = response

    with pytest.raises(Exception, match="403 Client Error"):
        adapter.download(match, tier="engineering")

    from src.retrieve import manifest

    assert manifest.get_entry(match.course_name, match.matched_url) is None
