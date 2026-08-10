from src.extract.extract_inputs import read_extraction_inputs
from src.retrieve import store
from src.retrieve.models import (
    DocumentRecord,
    DocumentType,
    IntentResolution,
    IntentRole,
    MatchType,
    RetrievalIntent,
    Segment,
    SourceTier,
)


def _link(db, course_id, segment, doc_id, source_id="UGC"):
    intent_id = f"RI-{course_id}-{doc_id}-{segment.name}"
    store.insert_intent(
        RetrievalIntent(
            intent_id=intent_id,
            course_id=course_id,
            segment=segment,
            field_ids=["F019"],
            source_id=source_id,
            priority=1,
            role=IntentRole.PRIMARY,
            query_terms=["x"],
            required_document_type=[DocumentType.OFFICIAL_PDF],
            qualification_level="Undergraduate",
        ),
        db_path=db,
    )
    store.insert_document(
        DocumentRecord(
            document_id=doc_id,
            source_id=source_id,
            source_tier=SourceTier.A,
            document_url=f"http://x/{doc_id}.pdf",
            document_title=doc_id,
            local_path=f"data/raw/{source_id}/{doc_id}.pdf",
            retrieved_at="2026-08-07T00:00:00Z",
        ),
        db_path=db,
    )
    store.insert_resolution(
        IntentResolution(
            intent_id=intent_id,
            document_id=doc_id,
            match_confidence=0.95,
            match_type=MatchType.EXACT,
            validated=True,
        ),
        db_path=db,
    )


def test_one_input_per_course_not_per_document(tmp_path):
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "mech", Segment.CURRICULUM, "DOC-2", source_id="AICTE")

    inputs = read_extraction_inputs(db_path=db)

    assert [i.course_id for i in inputs] == ["mech"]


def test_an_input_lists_every_chunk_file_for_the_course(tmp_path):
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "mech", Segment.CURRICULUM, "DOC-2", source_id="AICTE")

    only = read_extraction_inputs(db_path=db)[0]

    assert sorted(only.chunk_filenames) == ["DOC-1.json", "DOC-2.json"]


def test_documents_are_grouped_by_the_segment_they_serve(tmp_path):
    # Segment-scoped extraction needs to know which document answers which
    # segment, rather than treating a course's evidence as one blob.
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "mech", Segment.CURRICULUM, "DOC-2", source_id="AICTE")

    only = read_extraction_inputs(db_path=db)[0]

    assert only.documents_by_segment[Segment.ELIGIBILITY] == ["DOC-1"]
    assert only.documents_by_segment[Segment.CURRICULUM] == ["DOC-2"]


def test_a_document_serving_two_segments_appears_under_both(tmp_path):
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "mech", Segment.DURATION_MODE, "DOC-1")

    only = read_extraction_inputs(db_path=db)[0]

    assert only.documents_by_segment[Segment.ELIGIBILITY] == ["DOC-1"]
    assert only.documents_by_segment[Segment.DURATION_MODE] == ["DOC-1"]
    assert only.chunk_filenames == ["DOC-1.json"]


def test_courses_are_returned_in_a_stable_order(tmp_path):
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "civil", Segment.ELIGIBILITY, "DOC-2")

    assert [i.course_id for i in read_extraction_inputs(db_path=db)] == ["civil", "mech"]


def test_a_course_with_no_resolved_document_is_absent(tmp_path):
    db = tmp_path / "m.db"
    store.insert_intent(
        RetrievalIntent(
            intent_id="RI-lonely",
            course_id="animation",
            segment=Segment.FEES,
            field_ids=["F080"],
            source_id="UGC",
            priority=1,
            role=IntentRole.PRIMARY,
            query_terms=["x"],
            required_document_type=[DocumentType.OFFICIAL_PDF],
            qualification_level="Undergraduate",
        ),
        db_path=db,
    )

    assert read_extraction_inputs(db_path=db) == []
