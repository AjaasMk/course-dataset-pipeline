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


def _document(doc_id: str, url: str, source_id: str = "UGC") -> DocumentRecord:
    return DocumentRecord(
        document_id=doc_id,
        source_id=source_id,
        source_tier=SourceTier.A,
        document_url=url,
        document_title=f"{source_id} document",
        local_path=f"data/raw/{source_id}/{doc_id}.pdf",
        retrieved_at="2026-08-07T00:00:00Z",
    )


def _intent(intent_id: str, course_id: str, segment: Segment, source_id: str = "UGC") -> RetrievalIntent:
    return RetrievalIntent(
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
    )


def _link(db, intent: RetrievalIntent, document: DocumentRecord) -> None:
    store.insert_intent(intent, db_path=db)
    store.insert_document(document, db_path=db)
    store.insert_resolution(
        IntentResolution(
            intent_id=intent.intent_id,
            document_id=document.document_id,
            match_confidence=0.95,
            match_type=MatchType.EXACT,
            validated=True,
        ),
        db_path=db,
    )


def test_a_course_yields_its_resolved_documents(tmp_path):
    db = tmp_path / "m.db"
    _link(db, _intent("RI-1", "mech", Segment.ELIGIBILITY), _document("DOC-1", "http://a/1.pdf"))

    found = store.documents_for_course("mech", db_path=db)

    assert [d.document_id for d in found] == ["DOC-1"]
    assert found[0].local_path == "data/raw/UGC/DOC-1.pdf"


def test_documents_carry_the_segments_they_were_resolved_for(tmp_path):
    db = tmp_path / "m.db"
    doc = _document("DOC-1", "http://a/1.pdf")
    _link(db, _intent("RI-1", "mech", Segment.ELIGIBILITY), doc)
    _link(db, _intent("RI-2", "mech", Segment.DURATION_MODE), doc)

    only = store.documents_for_course("mech", db_path=db)[0]

    assert set(only.segments) == {Segment.ELIGIBILITY, Segment.DURATION_MODE}


def test_one_document_serving_two_segments_is_returned_once(tmp_path):
    db = tmp_path / "m.db"
    doc = _document("DOC-1", "http://a/1.pdf")
    _link(db, _intent("RI-1", "mech", Segment.ELIGIBILITY), doc)
    _link(db, _intent("RI-2", "mech", Segment.CURRICULUM), doc)

    assert len(store.documents_for_course("mech", db_path=db)) == 1


def test_documents_for_other_courses_are_excluded(tmp_path):
    db = tmp_path / "m.db"
    _link(db, _intent("RI-1", "mech", Segment.ELIGIBILITY), _document("DOC-1", "http://a/1.pdf"))
    _link(db, _intent("RI-2", "civil", Segment.ELIGIBILITY), _document("DOC-2", "http://a/2.pdf"))

    assert [d.document_id for d in store.documents_for_course("mech", db_path=db)] == ["DOC-1"]


def test_an_unresolved_intent_contributes_no_document(tmp_path):
    db = tmp_path / "m.db"
    store.insert_intent(_intent("RI-1", "mech", Segment.FEES), db_path=db)

    assert store.documents_for_course("mech", db_path=db) == []


def test_documents_can_be_filtered_to_one_segment(tmp_path):
    db = tmp_path / "m.db"
    _link(db, _intent("RI-1", "mech", Segment.ELIGIBILITY), _document("DOC-1", "http://a/1.pdf"))
    _link(db, _intent("RI-2", "mech", Segment.FEES, "NIRF"), _document("DOC-2", "http://b/2.pdf", "NIRF"))

    found = store.documents_for_course("mech", segment=Segment.FEES, db_path=db)

    assert [d.document_id for d in found] == ["DOC-2"]


def test_every_course_with_documents_is_listable(tmp_path):
    db = tmp_path / "m.db"
    _link(db, _intent("RI-1", "mech", Segment.ELIGIBILITY), _document("DOC-1", "http://a/1.pdf"))
    _link(db, _intent("RI-2", "civil", Segment.ELIGIBILITY), _document("DOC-2", "http://a/2.pdf"))
    store.insert_intent(_intent("RI-3", "animation", Segment.FEES), db_path=db)

    assert store.courses_with_documents(db_path=db) == ["civil", "mech"]
