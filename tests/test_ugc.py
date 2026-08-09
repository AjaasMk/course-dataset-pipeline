from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.ugc import UGCAdapter, title_from_filename

REGULATIONS_HTML = """
<html><body>
  <a href="/pdfnews/5576784_UG-and-PG-Regulations-2025.pdf">View</a>
  <a href="/pdfnews/2584862_ODL-third-Amendment-Regualtions-2024.pdf">View</a>
  <a href="/pdfnews/4299042_Appointment-of-Teachers-and-other-Academic-Staff.pdf">View</a>
  <a href="/pdfnews/Setting%20up%20and%20Operation%20of%20Campuses.pdf">View</a>
  <a href="/about">About UGC</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return UGCAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.ugc.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-040",
        "course_id": "bsc_psychology",
        "segment": Segment.ELIGIBILITY,
        "field_ids": ["F019", "F030"],
        "source_id": "UGC",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["UG and PG regulations"],
        "required_document_type": [DocumentType.OFFICIAL_PDF],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text=REGULATIONS_HTML):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_a():
    assert UGCAdapter.source_id == "UGC"
    assert UGCAdapter.tiers == [SourceTier.A]


def test_title_strips_the_numeric_prefix_and_hyphens():
    assert title_from_filename("5576784_UG-and-PG-Regulations-2025.pdf") == "UG and PG Regulations 2025"


def test_title_decodes_percent_escapes():
    assert title_from_filename("Setting%20up%20and%20Operation%20of%20Campuses.pdf") == (
        "Setting up and Operation of Campuses"
    )


@patch("src.retrieve.ugc.requests.get")
def test_index_titles_come_from_the_filename_not_the_view_link_text(mock_get, adapter):
    mock_get.return_value = _html_response()

    titles = set(adapter.build_index())

    assert "View" not in titles
    assert "UG and PG Regulations 2025" in titles


@patch("src.retrieve.ugc.requests.get")
def test_index_keeps_only_pdfs(mock_get, adapter):
    mock_get.return_value = _html_response()

    assert len(adapter.build_index()) == 4


@patch("src.retrieve.ugc.requests.get")
def test_hash_named_pdfs_are_excluded(mock_get, adapter):
    # UGC serves some uploads under a bare content hash, which yields a title
    # carrying no information and can only ever be a spurious match.
    mock_get.return_value = _html_response(
        '<html><body><a href="/pdfnews/9de3a363f1e3ca10e9645b323f76738e.pdf">View</a>'
        '<a href="/pdfnews/5576784_UG-and-PG-Regulations-2025.pdf">View</a></body></html>'
    )

    assert list(adapter.build_index()) == ["UG and PG Regulations 2025"]


@patch("src.retrieve.ugc.requests.get")
def test_resolve_ranks_the_matching_regulation_first(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent())[0]

    assert best.document_title == "UG and PG Regulations 2025"
    assert best.document_url.endswith(".pdf")


@patch("src.retrieve.ugc.requests.get")
def test_distance_learning_intent_resolves_to_the_odl_regulation(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["ODL distance education amendment"]))[0]

    assert "ODL" in best.document_title
