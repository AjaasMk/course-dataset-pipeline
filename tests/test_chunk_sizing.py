import pytest

from src.extract.chunk_sizing import (
    HARD_MAX_TOKENS,
    MIN_TOKENS,
    normalise,
    tokens_for,
)
from src.extract.llm_chunker import LLMChunk
from src.retrieve.models import Segment

WORD = "curriculum "
TEXT = WORD * 2000


def _chunk(chunk_id, start, end, segment=Segment.CURRICULUM):
    body = TEXT[start:end]
    return LLMChunk(
        chunk_id=chunk_id,
        document_id="DOC-1",
        text=body,
        content_hash=f"h{chunk_id}",
        char_start=start,
        char_end=end,
        segment_id=segment,
    )


def test_small_adjacent_chunks_merge_into_the_size_band():
    chunks = [_chunk(i, i * 300, (i + 1) * 300) for i in range(10)]

    out = normalise(chunks, TEXT)

    assert len(out) < len(chunks)
    assert all(tokens_for(c.text) <= HARD_MAX_TOKENS for c in out)


def test_an_oversized_chunk_is_split_rather_than_passed_through():
    chunks = [_chunk(0, 0, 12000)]

    out = normalise(chunks, TEXT)

    assert len(out) > 1
    assert all(tokens_for(c.text) <= HARD_MAX_TOKENS for c in out)


def test_every_normalised_chunk_is_a_verbatim_slice_of_the_source():
    # The guard the whole module exists under: quoted evidence must stay
    # byte-identical to the stored document or Hard Constraint 2 citations
    # cannot be validated against it.
    chunks = [_chunk(i, i * 300, (i + 1) * 300) for i in range(10)]

    out = normalise(chunks, TEXT)

    for chunk in out:
        assert chunk.text == TEXT[chunk.char_start : chunk.char_end]
        assert chunk.text in TEXT


def test_chunks_from_different_segments_never_merge():
    # Merging across a segment boundary would silently undo the label fix that
    # cut miscategorised Course Identity chunks by 91%.
    chunks = [
        _chunk(0, 0, 300, Segment.CURRICULUM),
        _chunk(1, 300, 600, Segment.COURSE_IDENTITY),
        _chunk(2, 600, 900, Segment.CURRICULUM),
    ]

    out = normalise(chunks, TEXT)

    assert {c.segment_id.value for c in out} == {"Curriculum", "Course Identity"}


def test_later_chunks_carry_overlap_and_the_first_does_not():
    chunks = [_chunk(i, i * 3000, (i + 1) * 3000) for i in range(3)]

    out = normalise(chunks, TEXT)

    assert out[0].char_start == 0
    assert any(c.char_start < chunks[i].char_start for i, c in enumerate(out) if i)


def test_empty_input_returns_empty():
    assert normalise([], TEXT) == []


def test_content_hash_is_recomputed_for_the_new_body():
    chunks = [_chunk(i, i * 300, (i + 1) * 300) for i in range(6)]

    out = normalise(chunks, TEXT)

    assert all(c.content_hash != f"h{i}" for i, c in enumerate(out))
