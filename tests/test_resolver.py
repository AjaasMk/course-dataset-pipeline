import pytest

from src.retrieve.models import (
    DiscoveredDocument,
    DocumentRecord,
    DocumentType,
    IntentRole,
    MatchType,
    RetrievalIntent,
    RetrievalStatus,
    Segment,
    SourceTier,
)
from src.retrieve.resolver import resolve_intents
from src.retrieve import store


class FakeAdapter:
    def __init__(self, source_id, tiers, documents=None, fails=False):
        self.source_id = source_id
        self.tiers = tiers
        self._documents = documents or []
        self._fails = fails
        self.resolve_calls = 0
        self.download_calls = 0

    def supports(self, intent):
        return intent.source_id == self.source_id

    def resolve(self, intent):
        self.resolve_calls += 1
        if self._fails:
            raise RuntimeError("network exploded")
        return list(self._documents)

    def download(self, document):
        self.download_calls += 1
        return DocumentRecord(
            document_id=f"DOC-{abs(hash(document.document_url)) % 10**8}",
            source_id=self.source_id,
            source_tier=self.tiers[0],
            document_url=document.document_url,
            document_title=document.document_title,
            retrieved_at="2026-08-07T00:00:00Z",
        )


def _document(url, confidence, title="Mechanical Engineering Curriculum"):
    return DiscoveredDocument(
        document_url=url,
        document_title=title,
        match_confidence=confidence,
        match_type=MatchType.FUZZY,
    )


def _intent(source_id="AICTE", **overrides) -> RetrievalIntent:
    fields = {
        "intent_id": f"RI-{source_id}",
        "course_id": "mechanical_engineering",
        "segment": Segment.CURRICULUM,
        "field_ids": ["F042"],
        "source_id": source_id,
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["Mechanical Engineering"],
        "required_document_type": [DocumentType.OFFICIAL_PDF],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "m.db"


def test_a_confident_match_is_downloaded_and_recorded(db):
    adapter = FakeAdapter("AICTE", [SourceTier.A], [_document("http://a/mech.pdf", 0.95)])

    report = resolve_intents([_intent()], {"AICTE": adapter}, thresholds={"AICTE": 0.80}, db_path=db)

    assert adapter.download_calls == 1
    assert report.resolved == 1
    assert store.count_documents(db_path=db) == 1


def test_a_low_confidence_match_is_not_downloaded(db):
    adapter = FakeAdapter("AICTE", [SourceTier.A], [_document("http://a/textile.pdf", 0.69)])

    report = resolve_intents([_intent()], {"AICTE": adapter}, thresholds={"AICTE": 0.80}, db_path=db)

    assert adapter.download_calls == 0
    assert report.unresolved == 1
    assert store.count_documents(db_path=db) == 0


def test_a_per_source_threshold_is_honoured(db):
    adapter = FakeAdapter("UGC", [SourceTier.A], [_document("http://u/reg.pdf", 0.70)])

    report = resolve_intents(
        [_intent(source_id="UGC")], {"UGC": adapter}, thresholds={"UGC": 0.65}, db_path=db
    )

    assert report.resolved == 1


def test_every_document_over_threshold_is_kept_not_just_the_best(db):
    adapter = FakeAdapter(
        "AICTE",
        [SourceTier.A],
        [_document("http://a/one.pdf", 0.95), _document("http://a/two.pdf", 0.88)],
    )

    resolve_intents([_intent()], {"AICTE": adapter}, thresholds={"AICTE": 0.80}, db_path=db)

    assert store.count_documents(db_path=db) == 2


def test_an_intent_with_no_adapter_is_unresolved_not_an_error(db):
    report = resolve_intents([_intent(source_id="NAAC")], {}, thresholds={}, db_path=db)

    assert report.unresolved == 1
    assert report.errored == 0


def test_tier_is_reported_even_when_no_adapter_exists(db):
    # Tier is a property of the source, not of the adapter. Taking it from the
    # adapter loses stratification for exactly the intents that went unserved,
    # which is where Hard Constraint 6 most needs it.
    report = resolve_intents(
        [_intent(source_id="NAAC")], {}, thresholds={}, tiers={"NAAC": SourceTier.A}, db_path=db
    )

    assert ("Curriculum", "A") in report.by_segment_tier
    assert ("Curriculum", "?") not in report.by_segment_tier


def test_an_adapter_failure_is_isolated_to_its_own_intent(db):
    broken = FakeAdapter("AICTE", [SourceTier.A], fails=True)
    working = FakeAdapter("NIRF", [SourceTier.A], [_document("http://n/rank.html", 0.99)])

    report = resolve_intents(
        [_intent(), _intent(source_id="NIRF", intent_id="RI-NIRF")],
        {"AICTE": broken, "NIRF": working},
        thresholds={"AICTE": 0.80, "NIRF": 0.80},
        db_path=db,
    )

    assert report.errored == 1
    assert report.resolved == 1


def test_one_document_shared_by_two_courses_is_downloaded_once(db):
    adapter = FakeAdapter("NIRF", [SourceTier.A], [_document("http://n/eng.html", 0.99)])

    resolve_intents(
        [
            _intent(source_id="NIRF", intent_id="RI-1", course_id="mechanical_engineering"),
            _intent(source_id="NIRF", intent_id="RI-2", course_id="civil_engineering"),
        ],
        {"NIRF": adapter},
        thresholds={"NIRF": 0.80},
        db_path=db,
    )

    assert store.count_documents(db_path=db) == 1
    assert len(store.intents_for_document(store.get_document_by_url("http://n/eng.html", db_path=db).document_id, db_path=db)) == 2


def test_unresolved_intents_are_queryable_afterwards(db):
    adapter = FakeAdapter("AICTE", [SourceTier.A], [_document("http://a/x.pdf", 0.10)])

    resolve_intents([_intent()], {"AICTE": adapter}, thresholds={"AICTE": 0.80}, db_path=db)

    assert [i.intent_id for i in store.unresolved_intents(db_path=db)] == ["RI-AICTE"]


def test_report_is_stratified_by_segment_and_source_tier(db):
    adapter = FakeAdapter("AICTE", [SourceTier.A], [_document("http://a/mech.pdf", 0.95)])

    report = resolve_intents([_intent()], {"AICTE": adapter}, thresholds={"AICTE": 0.80}, db_path=db)

    key = ("Curriculum", "A")
    assert key in report.by_segment_tier
    assert report.by_segment_tier[key][RetrievalStatus.AUTHORITATIVE_SOURCE_FOUND.value] == 1


def test_a_discovery_role_never_counts_as_authoritative(db):
    adapter = FakeAdapter("CAREERS360", [SourceTier.D], [_document("http://c/x.html", 0.99)])

    report = resolve_intents(
        [_intent(source_id="CAREERS360", role=IntentRole.DISCOVERY)],
        {"CAREERS360": adapter},
        thresholds={"CAREERS360": 0.80},
        db_path=db,
    )

    assert report.by_segment_tier[("Curriculum", "D")][
        RetrievalStatus.SECONDARY_SOURCE_FOUND.value
    ] == 1
    assert report.resolved_authoritative == 0
