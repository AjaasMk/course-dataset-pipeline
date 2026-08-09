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


@patch("src.retrieve.nta.requests.get")
def test_known_limitation_a_full_exam_title_as_a_query_term_falsely_matches_a_similarly_worded_exam(
    mock_get, adapter
):
    # KNOWN LIMITATION, deliberately not hardened against here (2026-08-09).
    # Confirmed live: using the FULL official title "Joint Entrance
    # Examination" as a query term scores 1.00 against BOTH the correct
    # jeemain document AND "Hotel Management Joint Entrance Examination"
    # (nchm-jee) -- token_set_ratio treats the shorter title as a full
    # token-subset of the longer one, regardless of "Hotel Management"
    # being an unrelated prefix. A blanket length-ratio penalty would fix
    # this but was rejected: it would also crush scores for the legitimate
    # short-query-matches-inside-a-long-title case this adapter's alias
    # vocabulary depends on (e.g. "JEE Main" vs the "jee" alias would drop
    # from ~100 to ~37, breaking test_engineering_intent_resolves_to_jee).
    # The real fix lives in planner.py's _AREA_TO_EXAM_TERMS, which was
    # changed to emit bare acronyms ("JEE") instead of full titles --
    # acronyms route through _EXAM_ALIASES, not a literal-substring match
    # against the raw title (see the next test). This test documents the
    # underlying adapter limitation so nobody "fixes" it by reintroducing a
    # full title as a query term without knowing this collision exists.
    mock_get.return_value = _html_response()

    results = adapter.resolve(_intent(query_terms=["Joint Entrance Examination"]))
    nchm = next(d for d in results if "Hotel Management" in d.document_title)

    assert nchm.match_confidence >= 0.80


@patch("src.retrieve.nta.requests.get")
def test_bare_acronym_query_term_does_not_match_the_similarly_worded_exam(mock_get, adapter):
    mock_get.return_value = _html_response()

    results = adapter.resolve(_intent(query_terms=["JEE"]))
    by_title = {d.document_title: d.match_confidence for d in results}

    assert by_title["Joint Entrance Examination"] >= 0.80
    assert "Hotel Management Joint Entrance Examination" not in by_title or (
        by_title["Hotel Management Joint Entrance Examination"] < 0.80
    )
