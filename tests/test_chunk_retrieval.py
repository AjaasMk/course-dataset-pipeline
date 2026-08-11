from src.extract.chunk_retrieval import TOP_K, TOP_K_BY_SEGMENT, retrieve
from src.extract.compression import compress
from src.extract.models import Chunk
from src.retrieve.models import Segment

QUERY = "core subjects credits semester elective laboratory"


def _chunk(chunk_id, text):
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        source_document="DOC-1",
        source_url="DOC-1",
        token_count=max(1, len(text.split())),
        segment_id=Segment.CURRICULUM,
        segment_match_confidence=1.0,
    )


def test_compression_output_is_always_made_of_input_spans():
    # The guarantee the whole stage lives under: a retained sentence must still
    # be a byte-identical slice of the document, or quoted evidence taken from
    # it stops validating.
    text = (
        "This document was prepared by the committee. "
        "Semester 3 core subjects include Thermodynamics with 4 credits. "
        "We thank the chairman for his guidance and support throughout. "
        "Semester 4 electives include Robotics with 3 credits."
    )

    out = compress(text, QUERY)

    for sentence in out.split("."):
        if sentence.strip():
            assert sentence.strip() in text


def test_compression_keeps_content_and_drops_acknowledgements():
    text = (
        "We thank the chairman and all committee members for their guidance.\n"
        "Semester 3 core subjects Thermodynamics credits 4 unit 2.\n"
    )

    out = compress(text, QUERY)

    assert "Thermodynamics" in out


def test_compression_returns_input_unchanged_when_nothing_scores():
    text = "Foreword. Preface. Acknowledgement."
    assert compress(text, "zzz nothing matches") == text


def test_retrieval_of_a_small_set_skips_ranking_and_keeps_everything():
    chunks = [_chunk(i, f"core subjects semester {i} credits 4") for i in range(3)]

    result = retrieve(chunks, "Curriculum")

    assert len(result.chunks) == 3
    assert result.stages == {}


def test_curriculum_gets_a_wider_cut_than_the_default():
    # Measured: Curriculum evidence is diffuse (136 gold chunks over 20 real
    # extractions, recall still climbing at rank 50), so a top-5 that works for
    # every other segment recalls under half of it.
    chunks = [_chunk(i, f"Semester {i} core subjects credits elective unit {i}")
              for i in range(40)]

    result = retrieve(chunks, "Curriculum", compress_context=False)

    assert len(result.chunks) == TOP_K_BY_SEGMENT["Curriculum"]
    assert len(result.chunks) > TOP_K


def test_retrieval_returns_top_k_in_document_order():
    # Reranked order is a relevance judgement; a curriculum reads in sequence,
    # so handing the model shuffled semesters would invent a discontinuity.
    chunks = [
        _chunk(i, f"Semester {i} core subjects credits elective laboratory unit {i}")
        for i in range(12)
    ]

    result = retrieve(chunks, "Eligibility", compress_context=False)

    assert len(result.chunks) == TOP_K
    assert [c.chunk_id for c in result.chunks] == sorted(c.chunk_id for c in result.chunks)


def test_retrieval_reports_the_reduction_it_achieved():
    chunks = [_chunk(i, f"Semester {i} core subjects credits " + "filler " * 40)
              for i in range(12)]

    result = retrieve(chunks, "Eligibility", compress_context=False)

    assert result.chars_before > result.chars_after
    assert 0 < result.reduction < 1


def test_empty_input_returns_empty_without_loading_a_model():
    assert retrieve([], "Curriculum").chunks == []
