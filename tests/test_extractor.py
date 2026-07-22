from unittest.mock import Mock

import pytest

from src.extract.extractor import (
    ExtractionTruncatedError,
    extract_course_detail,
    reconstruct_document,
)
from src.extract.models import Chunk
from src.schema import CourseDetail


def _chunk(chunk_id, text):
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        source_document="doc.html",
        source_url="https://example.com",
        token_count=len(text.split()),
    )


def _text_block(text):
    block = Mock()
    block.type = "text"
    block.text = text
    return block


def _mock_client_returning(json_text, stop_reason="end_turn"):
    fake_response = Mock()
    fake_response.content = [_text_block(json_text)]
    fake_response.stop_reason = stop_reason
    mock_client = Mock()
    mock_client.messages.create.return_value = fake_response
    return mock_client


def test_reconstruct_document_orders_chunks_by_chunk_id():
    chunks = [_chunk(1, "second"), _chunk(0, "first")]
    assert reconstruct_document(chunks) == "first\n\nsecond"


def test_extract_course_detail_calls_client_with_expected_params():
    fake_json = CourseDetail(course_name="Chemical Engineering", category="engineering").model_dump_json()
    mock_client = _mock_client_returning(fake_json)

    chunks = [_chunk(0, "Chemical Engineering combines chemistry and physics.")]
    result = extract_course_detail(
        chunks, "Chemical Engineering", "engineering", client=mock_client
    )

    assert result.course_name == "Chemical Engineering"
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    assert "Chemical Engineering" in call_kwargs["messages"][0]["content"]
    assert "combines chemistry and physics" in call_kwargs["messages"][0]["content"]
    system_block = call_kwargs["system"][0]
    assert "properties" in system_block["text"]  # schema was embedded in the system prompt
    assert system_block["cache_control"] == {"type": "ephemeral"}  # schema is cached across calls


def test_extract_course_detail_strips_markdown_fence_before_validating():
    fake_json = CourseDetail(course_name="X", category="engineering").model_dump_json()
    fenced = f"```json\n{fake_json}\n```"
    mock_client = _mock_client_returning(fenced)

    result = extract_course_detail([_chunk(0, "text")], "X", "engineering", client=mock_client)

    assert result.course_name == "X"


def test_extract_course_detail_creates_default_client_when_none_given(monkeypatch):
    fake_json = CourseDetail(course_name="X", category="engineering").model_dump_json()
    mock_client_instance = _mock_client_returning(fake_json)
    mock_client_cls = Mock(return_value=mock_client_instance)
    monkeypatch.setattr("src.extract.extractor.anthropic.Anthropic", mock_client_cls)

    result = extract_course_detail([_chunk(0, "text")], "X", "engineering")

    assert result.course_name == "X"
    mock_client_cls.assert_called_once()


def test_extract_course_detail_raises_clear_error_when_truncated_by_max_tokens():
    mock_client = _mock_client_returning(
        '{"course_name": "X", incomplete', stop_reason="max_tokens"
    )

    with pytest.raises(ExtractionTruncatedError, match="cut off"):
        extract_course_detail([_chunk(0, "text")], "X", "engineering", client=mock_client)
