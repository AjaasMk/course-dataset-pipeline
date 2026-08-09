from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.nsp import NSPAdapter, scheme_name_from_block

SCHEMES_HTML = """
<html><body>
  <div class="card">
    AICTE - Swanath Scholarship Scheme ( Technical Degree) (Welfare Based Scheme) Scheme
    Open from : 01-06-2026 Scheme Close on : 31-10-2026
    <a href="/docs/AICTE_3039_G.pdf">Specifications</a>
    <a href="/docs/AICTE_3039_F.pdf">FAQ</a>
  </div>
  <div class="card">
    PM USP Special Scholarship Scheme For Jammu Kashmir And Ladakh (Merit Based Scheme) Scheme
    Open from : 01-06-2026
    <a href="/docs/PM_USPY_SchemeSpecifications.pdf">Specifications</a>
  </div>
  <div class="footer">
    <a href="/docs/NSPInstituteKYCRegistrationUserManual.pdf">How to fill Registration Form</a>
  </div>
</body></html>
"""


@pytest.fixture
def adapter():
    return NSPAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.nsp.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-070",
        "course_id": "btech_cse",
        "segment": Segment.SCHOLARSHIPS,
        "field_ids": ["F092", "F094"],
        "source_id": "NSP",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["AICTE Swanath Scholarship technical degree"],
        "required_document_type": [DocumentType.OFFICIAL_PDF],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text=SCHEMES_HTML):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_a():
    assert NSPAdapter.source_id == "NSP"
    assert NSPAdapter.tiers == [SourceTier.A]


def test_scheme_name_is_cut_at_the_open_from_marker():
    block = "AICTE - Swanath Scholarship Scheme ( Technical Degree) Scheme Open from : 01-06-2026"
    assert scheme_name_from_block(block) == "AICTE - Swanath Scholarship Scheme ( Technical Degree)"


def test_scheme_name_survives_a_block_without_the_marker():
    assert scheme_name_from_block("Some Scholarship") == "Some Scholarship"


@patch("src.retrieve.nsp.requests.get")
def test_index_is_keyed_by_scheme_name_not_link_text(mock_get, adapter):
    mock_get.return_value = _html_response()

    index = adapter.build_index()

    assert "Specifications" not in index
    assert any("Swanath" in name for name in index)


@patch("src.retrieve.nsp.requests.get")
def test_index_ignores_documents_outside_a_scheme_block(mock_get, adapter):
    mock_get.return_value = _html_response()

    assert len(adapter.build_index()) == 2


@patch("src.retrieve.nsp.requests.get")
def test_resolve_ranks_the_matching_scheme_first(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent())[0]

    assert "Swanath" in best.document_title
    assert best.document_url.endswith("AICTE_3039_G.pdf")


@patch("src.retrieve.nsp.requests.get")
def test_unrelated_query_scores_below_threshold(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["Bharatanatyam"]))[0]

    assert best.match_confidence < 0.80
