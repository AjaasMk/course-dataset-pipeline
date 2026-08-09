from unittest.mock import Mock, patch

import pytest

from src.retrieve.careers360 import Careers360Adapter
from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)

PAGE_BYTES = b"<html><body>course page</body></html>"

LISTING_HTML = """
<html><body>
  <a href="/courses/bsc-psychology">BSc Psychology</a>
  <a href="/courses/ba-psychology">BA Psychology</a>
  <a href="/courses/bsc-physics">BSc Physics</a>
  <a href="/courses/bsc-psychology/colleges">BSc Psychology Colleges</a>
  <a href="/news/some-article">Some Article</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return Careers360Adapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.careers360.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-010",
        "course_id": "bsc_psychology",
        "segment": Segment.COURSE_IDENTITY,
        "field_ids": ["F001"],
        "source_id": "CAREERS360",
        "priority": 3,
        "role": IntentRole.DISCOVERY,
        "query_terms": ["BSc Psychology"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _listing_response():
    response = Mock()
    response.text = LISTING_HTML
    response.raise_for_status = Mock()
    return response


def _page_response():
    response = Mock()
    response.content = PAGE_BYTES
    response.status_code = 200
    response.headers = {"Content-Type": "text/html"}
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_d():
    assert Careers360Adapter.source_id == "CAREERS360"
    assert Careers360Adapter.tiers == [SourceTier.D]


@patch("src.retrieve.careers360.requests.get")
def test_resolve_returns_ranked_candidates(mock_get, adapter):
    mock_get.return_value = _listing_response()

    documents = adapter.resolve(_intent())

    assert len(documents) > 1
    assert documents[0].document_title == "BSc Psychology"
    confidences = [d.match_confidence for d in documents]
    assert confidences == sorted(confidences, reverse=True)


@patch("src.retrieve.careers360.requests.get")
def test_resolve_ignores_non_course_pages(mock_get, adapter):
    mock_get.return_value = _listing_response()

    titles = {d.document_title for d in adapter.resolve(_intent())}

    assert "Some Article" not in titles
    assert "BSc Psychology Colleges" not in titles


@patch("src.retrieve.careers360.requests.get")
def test_download_records_the_document_at_tier_d(mock_get, adapter):
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]
    mock_get.return_value = _page_response()

    record = adapter.download(document)

    assert record.source_tier == SourceTier.D
    assert record.content_length is None


@patch("src.retrieve.careers360.requests.get")
def test_download_is_idempotent_on_document_url(mock_get, adapter):
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]

    mock_get.return_value = _page_response()
    first = adapter.download(document)
    calls_after_first = mock_get.call_count

    second = adapter.download(document)

    assert mock_get.call_count == calls_after_first
    assert second.document_id == first.document_id
