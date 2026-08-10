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
from src.retrieve import store


def _document(**overrides) -> DocumentRecord:
    fields = {
        "document_id": "DOC-001",
        "source_id": "NIRF",
        "source_tier": SourceTier.A,
        "document_url": "https://www.nirfindia.org/rankings/2026/engineering.html",
        "document_title": "NIRF 2026 Engineering Rankings",
        "retrieved_at": "2026-08-07T10:00:00Z",
    }
    fields.update(overrides)
    return DocumentRecord(**fields)


def _intent(intent_id: str, course_id: str, **overrides) -> RetrievalIntent:
    fields = {
        "intent_id": intent_id,
        "course_id": course_id,
        "segment": Segment.RANKING_ACCREDITATION,
        "field_ids": ["F072", "F073"],
        "source_id": "NIRF",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["engineering", "ranking"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _resolution(intent_id: str, document_id: str = "DOC-001") -> IntentResolution:
    return IntentResolution(
        intent_id=intent_id,
        document_id=document_id,
        match_confidence=0.94,
        match_type=MatchType.EXACT,
        validated=True,
    )


def test_document_round_trips_by_url(tmp_path):
    db = tmp_path / "m.db"
    store.insert_document(_document(), db_path=db)
    found = store.get_document_by_url(_document().document_url, db_path=db)
    assert found is not None and found.document_id == "DOC-001"


def test_document_round_trips_by_id(tmp_path):
    db = tmp_path / "m.db"
    store.insert_document(_document(), db_path=db)
    found = store.get_document_by_id("DOC-001", db_path=db)
    assert found is not None and found.document_url == _document().document_url


def test_get_document_by_id_returns_none_when_missing(tmp_path):
    db = tmp_path / "m.db"
    assert store.get_document_by_id("DOC-does-not-exist", db_path=db) is None


def test_reinserting_the_same_url_does_not_duplicate(tmp_path):
    db = tmp_path / "m.db"
    store.insert_document(_document(), db_path=db)
    store.insert_document(_document(document_id="DOC-999"), db_path=db)
    assert store.count_documents(db_path=db) == 1


def test_one_document_serves_many_courses(tmp_path):
    db = tmp_path / "m.db"
    store.insert_document(_document(), db_path=db)
    for n, course in enumerate(["civil_engineering", "mechanical_engineering"], start=1):
        intent = _intent(f"RI-{n:03d}", course)
        store.insert_intent(intent, db_path=db)
        store.insert_resolution(_resolution(intent.intent_id), db_path=db)

    assert store.count_documents(db_path=db) == 1
    assert len(store.intents_for_document("DOC-001", db_path=db)) == 2


def test_an_intent_with_no_resolution_is_unresolved(tmp_path):
    db = tmp_path / "m.db"
    store.insert_document(_document(), db_path=db)
    store.insert_intent(_intent("RI-001", "civil_engineering"), db_path=db)
    store.insert_intent(_intent("RI-002", "animation"), db_path=db)
    store.insert_resolution(_resolution("RI-001"), db_path=db)

    unresolved = store.unresolved_intents(db_path=db)
    assert [i.intent_id for i in unresolved] == ["RI-002"]
