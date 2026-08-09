import pytest

from src.extract.models import Chunk
from src.extract.segment_monitor import MISMATCH_WARN_RATIO, check_document_segment_distribution
from src.retrieve.models import Segment


def _chunk(segment_id, chunk_id=0) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, text="x", source_document="doc.pdf", source_url="http://x",
        token_count=10, segment_id=segment_id, segment_match_confidence=0.9,
    )


def test_a_document_matching_its_retrieval_tag_is_not_flagged():
    chunks = [_chunk(Segment.CURRICULUM, i) for i in range(10)]

    result = check_document_segment_distribution("DOC-1", chunks, document_segments=[Segment.CURRICULUM])

    assert result.flagged is False


def test_a_small_stray_share_is_logged_but_not_flagged():
    # A document fetched for Curriculum incidentally containing a couple of
    # eligibility-flavoured headings is a legitimate incidental find, not a
    # tagging problem.
    chunks = [_chunk(Segment.CURRICULUM, i) for i in range(9)] + [_chunk(Segment.ELIGIBILITY, 9)]

    result = check_document_segment_distribution("DOC-1", chunks, document_segments=[Segment.CURRICULUM])

    assert result.flagged is False
    assert result.stray_ratio == pytest.approx(0.1)


def test_a_large_mismatch_share_is_flagged():
    # ~40% of chunks in a different segment than the document's own retrieval
    # tag signals either a wrong document-level tag or a systemic matcher
    # problem for this source type -- must surface, not be silently absorbed.
    chunks = [_chunk(Segment.CURRICULUM, i) for i in range(6)] + [
        _chunk(Segment.ELIGIBILITY, i) for i in range(6, 10)
    ]

    result = check_document_segment_distribution("DOC-1", chunks, document_segments=[Segment.CURRICULUM])

    assert result.flagged is True
    assert result.stray_ratio == pytest.approx(0.4)


def test_the_threshold_boundary_is_documented_not_guessed():
    assert MISMATCH_WARN_RATIO == 0.40


def test_unclassified_chunks_count_as_stray_not_as_matching():
    chunks = [_chunk(Segment.CURRICULUM, i) for i in range(6)] + [_chunk("unclassified", i) for i in range(6, 10)]

    result = check_document_segment_distribution("DOC-1", chunks, document_segments=[Segment.CURRICULUM])

    assert result.stray_ratio == pytest.approx(0.4)


def test_a_document_with_no_own_retrieval_tag_reports_but_never_flags():
    # A document with no retrieval-level segment (e.g. discovered incidentally)
    # has nothing to compare against -- report the distribution, don't guess a
    # verdict.
    chunks = [_chunk(Segment.CURRICULUM, i) for i in range(10)]

    result = check_document_segment_distribution("DOC-1", chunks, document_segments=[])

    assert result.flagged is False
    assert result.stray_ratio is None


def test_a_document_covering_two_retrieval_segments_treats_either_as_matching():
    # A source legitimately fetched for two segments (e.g. one UGC PDF
    # resolved for both Eligibility and Duration & Mode) should not have its
    # own second segment's chunks counted as stray against the first.
    chunks = [_chunk(Segment.ELIGIBILITY, i) for i in range(5)] + [
        _chunk(Segment.DURATION_MODE, i) for i in range(5, 10)
    ]

    result = check_document_segment_distribution(
        "DOC-1", chunks, document_segments=[Segment.ELIGIBILITY, Segment.DURATION_MODE]
    )

    assert result.flagged is False
    assert result.stray_ratio == 0.0


def test_empty_chunk_list_reports_cleanly():
    result = check_document_segment_distribution("DOC-1", [], document_segments=[Segment.CURRICULUM])

    assert result.flagged is False
    assert result.stray_ratio is None
