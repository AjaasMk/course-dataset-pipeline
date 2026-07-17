import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.retrieve.aicte import AICTEAdapter
from src.retrieve.base import SourceMatch
from src.schema import SourceType

PDF_BYTES = b"%PDF-1.4 fake pdf bytes"


@pytest.fixture
def adapter():
    return AICTEAdapter()


@pytest.fixture
def match():
    return SourceMatch(
        course_name="Mechanical Engineering",
        matched_name="Revised Model Curriculum for UG Degree Course in Mechanical Engineering",
        matched_url="https://www.aicte.gov.in/sites/default/files/mechanical.pdf",
        confidence=0.92,
    )


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.manifest.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.aicte.RAW_DIR", tmp_path / "raw")


def _mock_response(content=PDF_BYTES, status_code=200, content_type="application/pdf"):
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.aicte.requests.get")
def test_download_writes_file_and_manifest_entry(mock_get, adapter, match):
    mock_get.return_value = _mock_response()

    entry = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert entry.course_name == "Mechanical Engineering"
    assert entry.tier == "engineering"
    assert entry.source_type == SourceType.REGULATOR_PDF
    assert entry.http_status == 200
    assert entry.content_type == "application/pdf"
    assert entry.content_length == len(PDF_BYTES)
    assert entry.file_hash == hashlib.sha256(PDF_BYTES).hexdigest()
    assert Path(entry.local_path).read_bytes() == PDF_BYTES
    assert Path(entry.local_path).name == "mechanical_engineering.pdf"


@patch("src.retrieve.aicte.requests.get")
def test_second_download_for_same_course_and_url_skips_http_call(mock_get, adapter, match):
    mock_get.return_value = _mock_response()

    first = adapter.download(match, tier="engineering")
    second = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert second == first


@patch("src.retrieve.aicte.requests.get")
def test_different_url_triggers_new_download(mock_get, adapter, match):
    mock_get.return_value = _mock_response()
    adapter.download(match, tier="engineering")

    other_match = SourceMatch(
        course_name="Civil Engineering",
        matched_name="Revised Model Curriculum for UG Degree Course in Civil Engineering",
        matched_url="https://www.aicte.gov.in/sites/default/files/civil.pdf",
        confidence=0.9,
    )
    adapter.download(other_match, tier="engineering")

    assert mock_get.call_count == 2


@patch("src.retrieve.aicte.requests.get")
def test_http_failure_propagates_and_writes_no_manifest_entry(mock_get, adapter, match):
    response = _mock_response(status_code=404)
    response.raise_for_status.side_effect = Exception("404 Client Error")
    mock_get.return_value = response

    with pytest.raises(Exception, match="404 Client Error"):
        adapter.download(match, tier="engineering")

    from src.retrieve import manifest

    assert manifest.get_entry(match.course_name, match.matched_url) is None
