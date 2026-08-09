import pytest

from src.facts import store
from src.facts.models import CitationRequired, Ranking, SourceRef, VerificationStatus


def _ranking(**overrides) -> Ranking:
    fields = {
        "institution_id": "INST-aaa",
        "ranking_body": "NIRF",
        "ranking_year": "2025",
        "ranking_category": "Engineering",
        "rank": 1,
        "ranking_score": 88.72,
    }
    fields.update(overrides)
    return Ranking(**fields)


def _ref(field_id: str = "F075", document_id: str = "DOC-1") -> SourceRef:
    return SourceRef(
        field_id=field_id,
        document_id=document_id,
        quoted_evidence="IR-E-U-0456 | IIT Madras | Chennai | Tamil Nadu | 88.72 | 1",
        page_number=None,
        verification_status=VerificationStatus.AI_CHECKED,
    )


@pytest.fixture
def db(tmp_path):
    return tmp_path / "facts.db"


def test_a_ranking_round_trips_with_its_citation(db):
    store.record_ranking(_ranking(), refs=[_ref()], db_path=db)

    current = store.current_rankings("INST-aaa", db_path=db)

    assert len(current) == 1
    assert current[0].rank == 1
    assert store.refs_for(current[0].record_id, db_path=db)[0].quoted_evidence.startswith("IR-E-U-0456")


def test_a_fact_without_any_citation_is_rejected(db):
    # Hard Constraint 2: a field with content and no citation is invalid.
    with pytest.raises(CitationRequired):
        store.record_ranking(_ranking(), refs=[], db_path=db)


def test_one_institution_holds_a_ranking_per_category(db):
    for category, rank in [("Engineering", 1), ("Overall", 1), ("Management", 13)]:
        store.record_ranking(_ranking(ranking_category=category, rank=rank), refs=[_ref()], db_path=db)

    current = store.current_rankings("INST-aaa", db_path=db)

    assert sorted(r.ranking_category for r in current) == ["Engineering", "Management", "Overall"]


def test_a_changed_value_supersedes_rather_than_overwrites(db):
    store.record_ranking(_ranking(rank=1), refs=[_ref()], db_path=db)
    store.record_ranking(_ranking(rank=3), refs=[_ref()], db_path=db)

    current = store.current_rankings("INST-aaa", db_path=db)
    history = store.ranking_history("INST-aaa", "NIRF", "Engineering", "2025", db_path=db)

    assert [r.rank for r in current] == [3]
    assert sorted(r.rank for r in history) == [1, 3]


def test_a_superseded_row_keeps_its_own_citation(db):
    store.record_ranking(_ranking(rank=1), refs=[_ref(document_id="DOC-old")], db_path=db)
    store.record_ranking(_ranking(rank=3), refs=[_ref(document_id="DOC-new")], db_path=db)

    history = store.ranking_history("INST-aaa", "NIRF", "Engineering", "2025", db_path=db)
    by_rank = {r.rank: r for r in history}

    assert store.refs_for(by_rank[1].record_id, db_path=db)[0].document_id == "DOC-old"
    assert store.refs_for(by_rank[3].record_id, db_path=db)[0].document_id == "DOC-new"


def test_recording_an_unchanged_value_does_not_create_history(db):
    store.record_ranking(_ranking(rank=1), refs=[_ref()], db_path=db)
    store.record_ranking(_ranking(rank=1), refs=[_ref()], db_path=db)

    assert len(store.ranking_history("INST-aaa", "NIRF", "Engineering", "2025", db_path=db)) == 1


def test_different_ranking_years_coexist(db):
    store.record_ranking(_ranking(ranking_year="2024", rank=5), refs=[_ref()], db_path=db)
    store.record_ranking(_ranking(ranking_year="2025", rank=1), refs=[_ref()], db_path=db)

    current = store.current_rankings("INST-aaa", db_path=db)

    assert sorted((r.ranking_year, r.rank) for r in current) == [("2024", 5), ("2025", 1)]


def test_high_risk_facts_start_unverified_for_human_review(db):
    # Ranking claims are on the Mandatory Human Review Matrix, so an AI-checked
    # value must not present itself as verified.
    store.record_ranking(_ranking(), refs=[_ref()], db_path=db)

    only = store.current_rankings("INST-aaa", db_path=db)[0]

    assert not store.is_publishable(only.record_id, db_path=db)
