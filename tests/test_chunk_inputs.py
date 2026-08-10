from src.extract.chunk_inputs import ChunkInput, read_chunk_inputs
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


def _link(db, course_id, segment, doc_id, source_id="UGC", tier=SourceTier.A, suffix="pdf"):
    store.insert_intent(
        RetrievalIntent(
            intent_id=f"RI-{course_id}-{doc_id}-{segment.name}",
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
            source_tier=tier,
            document_url=f"http://x/{doc_id}.{suffix}",
            document_title=f"{source_id} doc",
            local_path=f"data/raw/{source_id}/{doc_id}.{suffix}",
            retrieved_at="2026-08-07T00:00:00Z",
        ),
        db_path=db,
    )
    store.insert_resolution(
        IntentResolution(
            intent_id=f"RI-{course_id}-{doc_id}-{segment.name}",
            document_id=doc_id,
            match_confidence=0.95,
            match_type=MatchType.EXACT,
            validated=True,
        ),
        db_path=db,
    )


def test_reads_one_input_per_resolved_document(tmp_path):
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "mech", Segment.FEES, "DOC-2", source_id="NIRF")

    inputs = read_chunk_inputs(db_path=db)

    assert sorted(i.document_id for i in inputs) == ["DOC-1", "DOC-2"]


def test_each_input_carries_its_course_and_segments(tmp_path):
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")
    _link(db, "mech", Segment.CURRICULUM, "DOC-1")

    only = read_chunk_inputs(db_path=db)[0]

    assert only.course_id == "mech"
    assert set(only.segments) == {Segment.ELIGIBILITY, Segment.CURRICULUM}


def test_a_document_shared_by_two_courses_yields_an_input_per_course(tmp_path):
    # One NIRF ranking table serves many courses. Chunking it once is right, but
    # each course needs its own input row so extraction can find it.
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.RANKING_ACCREDITATION, "DOC-9", source_id="NIRF")
    _link(db, "civil", Segment.RANKING_ACCREDITATION, "DOC-9", source_id="NIRF")

    inputs = read_chunk_inputs(db_path=db)

    assert sorted(i.course_id for i in inputs) == ["civil", "mech"]
    assert {i.document_id for i in inputs} == {"DOC-9"}


def test_documents_without_a_local_path_are_skipped(tmp_path):
    # A resolved document normally has a local path, since the resolver only
    # records one after download() returns. This guards the case where a record
    # reaches the store without a file behind it -- there is nothing to chunk.
    db = tmp_path / "m.db"
    store.insert_intent(
        RetrievalIntent(
            intent_id="RI-nofile",
            course_id="mech",
            segment=Segment.ELIGIBILITY,
            field_ids=["F019"],
            source_id="UGC",
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
            document_id="DOC-NOFILE",
            source_id="UGC",
            source_tier=SourceTier.A,
            document_url="http://x/never-fetched.pdf",
            document_title="unfetched",
            local_path=None,
            retrieved_at="2026-08-07T00:00:00Z",
        ),
        db_path=db,
    )
    store.insert_resolution(
        IntentResolution(
            intent_id="RI-nofile",
            document_id="DOC-NOFILE",
            match_confidence=0.95,
            match_type=MatchType.EXACT,
            validated=True,
        ),
        db_path=db,
    )

    assert read_chunk_inputs(db_path=db) == []


def test_an_unresolved_intent_produces_no_input(tmp_path):
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

    assert read_chunk_inputs(db_path=db) == []


def test_chunk_input_names_its_output_file_by_document_only(tmp_path):
    # Not per (course, document): chunking is a property of the document's
    # content alone, independent of which course cites it. A course-scoped
    # filename ("mech__DOC-1.json") would mean the same real document gets
    # chunked from scratch once per course that resolves to it -- confirmed
    # live 2026-08-10 this produced 7,886 chunk inputs for ~163 real unique
    # documents (a ~48x redundancy in real, paid API calls) before this fix.
    db = tmp_path / "m.db"
    _link(db, "mech", Segment.ELIGIBILITY, "DOC-1")

    only = read_chunk_inputs(db_path=db)[0]

    assert only.chunk_filename == "DOC-1.json"
