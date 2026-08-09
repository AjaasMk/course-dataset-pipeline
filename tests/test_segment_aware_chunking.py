from src.extract.chunker import chunk_document
from src.extract.models import Section
from src.extract.segment_match import UNCLASSIFIED
from src.retrieve.models import Segment
from tests.test_chunker import _FakeClient


def test_every_chunk_in_a_section_carries_the_same_segment_id():
    # A section with enough paragraphs to require several chunks -- every
    # fragment must self-identify, not just the first one. This is the fix
    # for the NIRF-style header-loss bug generalised: a fragment no longer
    # depends on carrying overlap text from chunk 0 to know what it is.
    section = Section(
        heading_title="COURSE OBJECTIVE(S):",
        paragraphs=["Sentence about the course objective. " * 40 for _ in range(20)],
    )

    chunks = chunk_document([section], "doc.pdf", "http://x", client=_FakeClient())

    assert len(chunks) > 1
    assert all(c.segment_id == Segment.CURRICULUM for c in chunks)
    assert all(c.segment_match_confidence >= 0.65 for c in chunks)


def test_every_chunk_also_carries_the_original_heading():
    section = Section(
        heading_title="India Rankings 2025: Engineering",
        paragraphs=["IR-E-U-0456 | IIT Madras | Chennai | Tamil Nadu | 88.72 | 1"] * 30,
    )

    chunks = chunk_document([section], "doc.html", "http://x", client=_FakeClient())

    assert all(c.heading_title == "India Rankings 2025: Engineering" for c in chunks)
    assert all(c.segment_id == Segment.RANKING_ACCREDITATION for c in chunks)


def test_an_unmatched_heading_tags_every_chunk_unclassified_not_dropped():
    section = Section(heading_title="PREAMBLE", paragraphs=["Some front-matter text here."] * 10)

    chunks = chunk_document([section], "doc.pdf", "http://x", client=_FakeClient())

    assert chunks
    assert all(c.segment_id == UNCLASSIFIED for c in chunks)
    assert all(c.heading_title == "PREAMBLE" for c in chunks)


def test_a_section_with_no_heading_is_unclassified():
    section = Section(heading_title=None, paragraphs=["Front cover text with no real heading."])

    chunks = chunk_document([section], "doc.pdf", "http://x", client=_FakeClient())

    assert chunks[0].segment_id == UNCLASSIFIED


def test_different_sections_can_carry_different_segments():
    sections = [
        Section(heading_title="ELIGIBILITY FOR ADMISSION", paragraphs=["10+2 with PCM required."]),
        Section(heading_title="COURSE CONTENTS:", paragraphs=["Thermodynamics, fluid mechanics."]),
    ]

    chunks = chunk_document(sections, "doc.pdf", "http://x", client=_FakeClient())

    by_heading = {c.heading_title: c.segment_id for c in chunks}
    assert by_heading["ELIGIBILITY FOR ADMISSION"] == Segment.ELIGIBILITY
    assert by_heading["COURSE CONTENTS:"] == Segment.CURRICULUM
