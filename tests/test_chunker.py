import httpx
import pytest
from anthropic import APIConnectionError

from src.extract.chunker import (
    MAX_TOKENS,
    _split_oversized_text,
    _tail_tokens,
    _token_count,
    chunk_document,
    detect_pdf_sections,
)
from src.extract.models import PageText, Section


class _FakeCountTokensResponse:
    def __init__(self, input_tokens: int):
        self.input_tokens = input_tokens


class _FakeMessages:
    def count_tokens(self, model, messages):
        # Approximates real subword tokenization (~1.3 tokens/word) so
        # chunk-splitting behavior in these tests still exercises MAX_TOKENS
        # the way the real count_tokens() API would, without a network call.
        text = messages[0]["content"]
        return _FakeCountTokensResponse(input_tokens=max(1, int(len(text.split()) * 1.3)))


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _chunk(sections, source_document="doc.pdf", source_url="https://example.com/doc"):
    return chunk_document(sections, source_document=source_document, source_url=source_url, client=_FakeClient())


def _connection_error():
    return APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages/count_tokens"))


class _FlakyMessages:
    """Fails with APIConnectionError a fixed number of times, then succeeds."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def count_tokens(self, model, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise _connection_error()
        return _FakeCountTokensResponse(input_tokens=5)


class _FlakyClient:
    def __init__(self, fail_times: int):
        self.messages = _FlakyMessages(fail_times)


def test_token_count_retries_on_connection_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.extract.chunker.time.sleep", lambda seconds: None)
    client = _FlakyClient(fail_times=2)

    result = _token_count("some text", client)

    assert result == 5
    assert client.messages.calls == 3


def test_token_count_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("src.extract.chunker.time.sleep", lambda seconds: None)
    client = _FlakyClient(fail_times=5)

    with pytest.raises(APIConnectionError):
        _token_count("some text", client)

    assert client.messages.calls == 3


def test_split_oversized_text_splits_at_sentence_boundaries():
    # ~1000 words / ~1300 fake tokens -- comfortably over MAX_TOKENS=1000,
    # with clean sentence punctuation to split on (mirrors the real oversized
    # paragraph found live in a Careers360 "What is X" intro block).
    sentence = "This is one sentence in a long block of real prose text."
    text = " ".join([sentence] * 100)

    pieces = _split_oversized_text(text, _FakeClient())

    assert len(pieces) > 1
    client = _FakeClient()
    for piece in pieces:
        assert _token_count(piece, client) <= MAX_TOKENS
    # No content lost or reordered by the split.
    assert " ".join(pieces).replace("  ", " ") == text


def test_split_oversized_text_falls_back_to_word_grouping_with_no_punctuation():
    # No sentence-ending punctuation at all (e.g. an unbroken table row) --
    # _SENTENCE_SPLIT_RE finds nothing to split on, forcing the word-group
    # fallback.
    text = " ".join(["word"] * 1000)

    pieces = _split_oversized_text(text, _FakeClient())

    assert len(pieces) > 1
    client = _FakeClient()
    for piece in pieces:
        assert _token_count(piece, client) <= MAX_TOKENS


def test_tail_tokens_returns_full_text_when_already_under_target():
    text = "A short bit of text."
    assert _tail_tokens(text, 125, _FakeClient()) == text


def test_tail_tokens_returns_suffix_of_text_within_target():
    words = [f"word{i}" for i in range(500)]
    text = " ".join(words)

    result = _tail_tokens(text, 50, _FakeClient())

    assert text.endswith(result)
    assert _token_count(result, _FakeClient()) <= 50


def test_chunk_document_splits_a_single_oversized_paragraph():
    # A single paragraph alone exceeding MAX_TOKENS used to become its own
    # ~2x-over-limit chunk (chunk_document never split within a paragraph) --
    # confirmed live on real pilot data after the tokenizer fix made true
    # sizes visible. Now it must be split into multiple compliant chunks.
    sentence = "This is one sentence in a long block of real prose text."
    oversized_paragraph = " ".join([sentence] * 100)
    sections = [Section(heading_title="What is X", paragraphs=[oversized_paragraph])]

    chunks = _chunk(sections)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= MAX_TOKENS + 200  # slack for carried overlap


def test_chunk_document_short_section_fits_in_one_chunk():
    sections = [Section(heading_title="Preamble", paragraphs=["A short paragraph of text."])]

    chunks = _chunk(sections)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == 0
    assert chunks[0].text == "A short paragraph of text."
    assert chunks[0].heading_title == "Preamble"
    assert chunks[0].source_document == "doc.pdf"
    assert chunks[0].source_url == "https://example.com/doc"
    assert chunks[0].token_count > 0


def test_chunk_document_splits_long_section_by_paragraph():
    # Each paragraph is ~150 words (~200 tokens); 6 paragraphs should force a split
    # well before all of them fit in one ~1000 token chunk.
    long_paragraph = " ".join(["word"] * 150)
    sections = [Section(heading_title="Long Section", paragraphs=[long_paragraph] * 12)]

    chunks = _chunk(sections)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 1000 + 200  # some slack for overlap carried into the next chunk


def test_chunk_document_carries_overlap_into_next_chunk():
    long_paragraph = " ".join(["word"] * 150)
    sections = [Section(heading_title="Long Section", paragraphs=[long_paragraph] * 12)]

    chunks = _chunk(sections)

    assert len(chunks) > 1
    # The tail of chunk N should reappear at the start of chunk N+1 (the overlap).
    first_chunk_tail_words = chunks[0].text.split()[-20:]
    second_chunk_head_words = chunks[1].text.split()[:20]
    assert any(word in second_chunk_head_words for word in first_chunk_tail_words)


def test_chunk_document_assigns_sequential_ids_across_sections():
    sections = [
        Section(heading_title="Section One", paragraphs=["First paragraph."]),
        Section(heading_title="Section Two", paragraphs=["Second paragraph."]),
    ]

    chunks = _chunk(sections)

    assert [c.chunk_id for c in chunks] == [0, 1]
    assert chunks[0].heading_title == "Section One"
    assert chunks[1].heading_title == "Section Two"


def test_chunk_document_carries_page_number_from_section():
    sections = [Section(heading_title="Preamble", page_number=9, paragraphs=["Some content."])]

    chunks = _chunk(sections)

    assert chunks[0].page_number == 9


def test_detect_pdf_sections_finds_all_caps_heading():
    pages = [
        PageText(page_number=9, text="PREAMBLE\n\nMechanical engineering involves scientific analysis.\n\nMore preamble text here."),
    ]

    sections = detect_pdf_sections(pages)

    assert len(sections) == 1
    assert sections[0].heading_title == "PREAMBLE"
    assert sections[0].page_number == 9
    assert sections[0].paragraphs == [
        "Mechanical engineering involves scientific analysis.",
        "More preamble text here.",
    ]


def test_detect_pdf_sections_splits_on_multiple_headings_across_pages():
    pages = [
        PageText(page_number=9, text="PREAMBLE\n\nPreamble content."),
        PageText(page_number=10, text="SYLLABUS\n\nSyllabus content."),
    ]

    sections = detect_pdf_sections(pages)

    assert len(sections) == 2
    assert sections[0].heading_title == "PREAMBLE"
    assert sections[0].page_number == 9
    assert sections[1].heading_title == "SYLLABUS"
    assert sections[1].page_number == 10


def test_detect_pdf_sections_does_not_treat_title_case_line_as_heading():
    # Real false positives found against the actual AICTE PDF: committee-roster
    # entries and addresses are short, Title Case, no trailing punctuation --
    # exactly the shape a naive heuristic mistakes for a heading. Real headings
    # in this document are consistently ALL CAPS ("PREAMBLE", "PROFESSIONAL
    # CORE COURSES"), so Title Case alone must not qualify.
    pages = [
        PageText(
            page_number=5,
            text="PREAMBLE\n\nNelson Mandela Marg, Vasant Kunj\n\n5 Prof. K.V. Gangadharan\n\nReal preamble content follows.",
        ),
    ]

    sections = detect_pdf_sections(pages)

    assert len(sections) == 1
    assert sections[0].heading_title == "PREAMBLE"
    assert "Nelson Mandela Marg, Vasant Kunj" in sections[0].paragraphs
    assert "5 Prof. K.V. Gangadharan" in sections[0].paragraphs


def test_detect_pdf_sections_does_not_treat_long_sentence_as_heading():
    pages = [
        PageText(
            page_number=9,
            text="PREAMBLE\n\nThis is a normal sentence that happens to be reasonably long and ends with a period.",
        ),
    ]

    sections = detect_pdf_sections(pages)

    assert len(sections) == 1
    assert sections[0].heading_title == "PREAMBLE"
    assert len(sections[0].paragraphs) == 1
