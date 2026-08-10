import hashlib
from unittest.mock import Mock, patch

from src.retrieve.document_refresh import UpdateCheckResult, check_for_update
from src.retrieve.models import DocumentRecord, SourceTier

ORIGINAL_BYTES = b"<html>original content</html>"
CHANGED_BYTES = b"<html>updated content, curriculum revised</html>"


def _document(**overrides) -> DocumentRecord:
    fields = {
        "document_id": "DOC-aicte-mech",
        "source_id": "AICTE",
        "source_tier": SourceTier.A,
        "document_url": "https://www.aicte.gov.in/sites/default/files/Final_Mechanical Engg.pdf",
        "document_title": "Revised Model Curriculum for UG Degree Course in Mechanical Engineering",
        "file_hash": hashlib.sha256(ORIGINAL_BYTES).hexdigest(),
        "retrieved_at": "2026-01-15T10:00:00+00:00",
    }
    fields.update(overrides)
    return DocumentRecord(**fields)


def _response(content: bytes):
    response = Mock()
    response.content = content
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.document_refresh.requests.get")
def test_reports_unchanged_when_the_hash_matches(mock_get):
    mock_get.return_value = _response(ORIGINAL_BYTES)

    result = check_for_update(_document())

    assert isinstance(result, UpdateCheckResult)
    assert result.changed is False
    assert result.old_hash == result.new_hash


@patch("src.retrieve.document_refresh.requests.get")
def test_reports_changed_when_the_hash_differs(mock_get):
    mock_get.return_value = _response(CHANGED_BYTES)

    result = check_for_update(_document())

    assert result.changed is True
    assert result.old_hash != result.new_hash
    assert result.new_hash == hashlib.sha256(CHANGED_BYTES).hexdigest()


@patch("src.retrieve.document_refresh.requests.get")
def test_a_record_with_no_stored_hash_is_always_reported_changed(mock_get):
    # Nothing to diff against -- a fresh hash is new information, not a
    # confirmed "no change" the way a real hash-vs-hash match would be.
    mock_get.return_value = _response(ORIGINAL_BYTES)

    result = check_for_update(_document(file_hash=None))

    assert result.changed is True


@patch("src.retrieve.document_refresh.requests.get")
def test_result_carries_the_real_document_identity(mock_get):
    mock_get.return_value = _response(ORIGINAL_BYTES)

    result = check_for_update(_document())

    assert result.document_id == "DOC-aicte-mech"
    assert result.document_url == _document().document_url


@patch("src.retrieve.document_refresh.requests.get")
def test_uses_the_identifying_user_agent_by_default(mock_get):
    from src.retrieve.base import USER_AGENT

    mock_get.return_value = _response(ORIGINAL_BYTES)

    check_for_update(_document())

    assert mock_get.call_args.kwargs["headers"] == {"User-Agent": USER_AGENT}


@patch("src.retrieve.document_refresh.requests.get")
def test_accepts_caller_supplied_headers_and_verify(mock_get):
    mock_get.return_value = _response(ORIGINAL_BYTES)

    check_for_update(_document(), headers={"User-Agent": "custom"}, verify="data/ca_bundles/x.pem")

    assert mock_get.call_args.kwargs["headers"] == {"User-Agent": "custom"}
    assert mock_get.call_args.kwargs["verify"] == "data/ca_bundles/x.pem"
