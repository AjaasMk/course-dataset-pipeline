from unittest.mock import Mock, patch

import pytest

from src.retrieve.aicte import AICTEAdapter
from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)

PDF_BYTES = b"%PDF-1.4 fake pdf bytes"

LISTING_HTML = """
<html><body>
  <a href="/files/mech.pdf">Revised Model Curriculum for UG Degree Course in Mechanical Engineering</a>
  <a href="/files/civil.pdf">Revised Model Curriculum for UG Degree Course in Civil Engineering</a>
  <a href="/files/textile.pdf">Model Curriculum for UG Degree Course in Textile Engineering</a>
  <a href="/files/notes.doc">Model Curriculum for UG Degree Course in Chemical Engineering</a>
  <a href="/files/circular.pdf">Approval Process Handbook</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return AICTEAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.aicte.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-001",
        "course_id": "mechanical_engineering",
        "segment": Segment.CURRICULUM,
        "field_ids": ["F042"],
        "source_id": "AICTE",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["Mechanical Engineering"],
        "required_document_type": [DocumentType.OFFICIAL_PDF],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _listing_response():
    response = Mock()
    response.text = LISTING_HTML
    response.raise_for_status = Mock()
    return response


def _pdf_response(content=PDF_BYTES):
    response = Mock()
    response.content = content
    response.status_code = 200
    response.headers = {"Content-Type": "application/pdf", "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


def test_adapter_declares_its_source_id_and_tier():
    assert AICTEAdapter.source_id == "AICTE"
    assert AICTEAdapter.tiers == [SourceTier.A]


def test_supports_only_intents_addressed_to_this_source(adapter):
    assert adapter.supports(_intent(source_id="AICTE"))
    assert not adapter.supports(_intent(source_id="NIRF"))


@patch("src.retrieve.aicte.requests.get")
def test_resolve_returns_several_ranked_candidates(mock_get, adapter):
    mock_get.return_value = _listing_response()

    documents = adapter.resolve(_intent())

    assert len(documents) > 1
    confidences = [d.match_confidence for d in documents]
    assert confidences == sorted(confidences, reverse=True)


@patch("src.retrieve.aicte.requests.get")
def test_resolve_ranks_the_matching_branch_first(mock_get, adapter):
    mock_get.return_value = _listing_response()

    best = adapter.resolve(_intent())[0]

    assert "Mechanical Engineering" in best.document_title
    assert best.document_url.endswith("mech.pdf")


@patch("src.retrieve.aicte.requests.get")
def test_resolve_honours_the_required_document_type(mock_get, adapter):
    mock_get.return_value = _listing_response()

    documents = adapter.resolve(_intent(query_terms=["Chemical Engineering"]))

    assert all(d.document_url.endswith(".pdf") for d in documents)


@patch("src.retrieve.aicte.requests.get")
def test_download_writes_the_file_and_records_the_document(mock_get, adapter):
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]
    mock_get.return_value = _pdf_response()

    record = adapter.download(document)

    assert record.source_id == "AICTE"
    assert record.source_tier == SourceTier.A
    assert record.file_hash is not None
    assert record.local_path is not None


@patch("src.retrieve.aicte.requests.get")
def test_download_is_idempotent_on_document_url(mock_get, adapter):
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]

    mock_get.return_value = _pdf_response()
    first = adapter.download(document)
    calls_after_first = mock_get.call_count

    second = adapter.download(document)

    assert mock_get.call_count == calls_after_first
    assert second.document_id == first.document_id
