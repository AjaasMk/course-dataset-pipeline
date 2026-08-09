from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.nta import NTAAdapter

HOMEPAGE_HTML = """
<html><body>
  <a href="/about">About NTA</a>
  <a href="https://jeemain.nta.nic.in">Joint Entrance Examination</a>
  <a href="https://cmat.nta.nic.in/">Common Management Admission Test</a>
  <a href="https://ugcnet.nta.nic.in">UGC National Eligibility Test</a>
  <a href="https://exams.nta.nic.in/icar/">ICAR'S All India Entrance Examination</a>
  <a href="https://exams.nta.nic.in/nchm-jee/">Hotel Management Joint Entrance Examination</a>
  <a href="https://neet.nta.nic.in/">National Eligibility Cum Entrance Test</a>
  <a href="https://cuet.nta.nic.in/">COMMON UNIVERSITY ENTRANCE TEST (UG)</a>
  <a href="/ContactUs">Contact Us</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return NTAAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.nta.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-030",
        "course_id": "mechanical_engineering",
        "segment": Segment.ENTRANCE_ADMISSION,
        "field_ids": ["F031", "F033", "F040"],
        "source_id": "NTA",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["JEE Main", "engineering entrance exam"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text=HOMEPAGE_HTML):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_a():
    assert NTAAdapter.source_id == "NTA"
    assert NTAAdapter.tiers == [SourceTier.A]


@patch("src.retrieve.nta.requests.get")
def test_index_keeps_only_exam_portals(mock_get, adapter):
    mock_get.return_value = _html_response()

    index = adapter.build_index()

    assert "About NTA" not in index
    assert "Contact Us" not in index
    assert len(index) == 7


@patch("src.retrieve.nta.requests.get")
def test_engineering_intent_resolves_to_jee(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent())[0]

    assert best.document_url.startswith("https://jeemain.nta.nic.in")


@patch("src.retrieve.nta.requests.get")
def test_medical_intent_resolves_to_neet(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["NEET", "medical entrance"]))[0]

    assert best.document_url.startswith("https://neet.nta.nic.in")


@patch("src.retrieve.nta.requests.get")
def test_management_intent_resolves_to_cmat(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["management entrance exam", "MBA"]))[0]

    assert best.document_url.startswith("https://cmat.nta.nic.in")


@patch("src.retrieve.nta.requests.get")
def test_unrelated_course_scores_below_the_acceptance_threshold(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["Bharatanatyam"]))[0]

    assert best.match_confidence < 0.80
