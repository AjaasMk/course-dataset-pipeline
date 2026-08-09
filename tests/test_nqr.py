from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.nqr import NQRAdapter

SECTORS_HTML = """
<html><body>
  <a href="https://www.nqr.gov.in/qualifications-search/2">Aerospace &amp; Aviation</a>
  <a href="https://www.nqr.gov.in/qualifications-search/3">Agriculture</a>
  <a href="https://www.nqr.gov.in/qualifications-search/7">Capital Goods &amp; Manufacturing</a>
  <a href="https://www.nqr.gov.in/qualifications-search/17">Healthcare</a>
  <a href="https://www.nqr.gov.in/qualifications-search/10">Education, Training &amp; Research</a>
  <a href="https://www.nqr.gov.in/screen-reader-access">Screen Reader Access</a>
  <a href="#skip-main">Skip to Main Content</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return NQRAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.nqr.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-060",
        "course_id": "aircraft_maintenance",
        "segment": Segment.COURSE_IDENTITY,
        "field_ids": ["F004", "F007"],
        "source_id": "NQR",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["Aerospace & Aviation"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text=SECTORS_HTML):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_a():
    assert NQRAdapter.source_id == "NQR"
    assert NQRAdapter.tiers == [SourceTier.A]


@patch("src.retrieve.nqr.requests.get")
def test_index_keeps_only_qualification_sectors(mock_get, adapter):
    mock_get.return_value = _html_response()

    index = adapter.build_index()

    assert "Screen Reader Access" not in index
    assert "Skip to Main Content" not in index
    assert len(index) == 5


@patch("src.retrieve.nqr.requests.get")
def test_resolve_matches_the_named_sector(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent())[0]

    assert best.document_title == "Aerospace & Aviation"
    assert best.document_url.endswith("/2")


@patch("src.retrieve.nqr.requests.get")
def test_healthcare_intent_resolves_to_healthcare(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["Healthcare", "nursing"]))[0]

    assert best.document_title == "Healthcare"


@patch("src.retrieve.nqr.requests.get")
def test_uncovered_discipline_scores_below_threshold(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["Bharatanatyam"]))[0]

    assert best.match_confidence < 0.80
