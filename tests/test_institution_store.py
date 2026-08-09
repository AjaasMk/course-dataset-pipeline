from src.institutions import store
from src.institutions.models import Institution, InstitutionAlias, InstitutionCourseOffering


def _institution(**overrides) -> Institution:
    fields = {
        "institution_id": "INST-aaa",
        "canonical_name": "Jamia Millia Islamia",
        "nirf_id": "IR-O-U-0108",
        "city": "New Delhi",
        "state": "Delhi",
        "nirf_rank": 3,
        "ranking_year": "2025",
        "ranking_category": "University",
        "discovered_from_source_id": "NIRF",
    }
    fields.update(overrides)
    return Institution(**fields)


def test_institution_round_trips(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(), db_path=db)
    found = store.get_institution("INST-aaa", db_path=db)
    assert found is not None and found.canonical_name == "Jamia Millia Islamia"


def test_reinserting_the_same_institution_does_not_duplicate(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(), db_path=db)
    store.upsert_institution(_institution(ranking_category="Engineering"), db_path=db)
    assert store.count_institutions(db_path=db) == 1


def test_upsert_fills_a_field_that_was_previously_missing(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(aishe_code=None), db_path=db)
    store.upsert_institution(_institution(aishe_code="U-0123"), db_path=db)
    assert store.get_institution("INST-aaa", db_path=db).aishe_code == "U-0123"


def test_upsert_does_not_blank_an_existing_field_with_none(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(aishe_code="U-0123"), db_path=db)
    store.upsert_institution(_institution(aishe_code=None), db_path=db)
    assert store.get_institution("INST-aaa", db_path=db).aishe_code == "U-0123"


def test_aliases_accumulate_per_institution(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(), db_path=db)
    for name in ["Jamia Millia Islamia, New Delhi", "JMI"]:
        store.add_alias(
            InstitutionAlias(institution_id="INST-aaa", observed_name=name, source_id="NIRF"),
            db_path=db,
        )
    assert len(store.aliases_for("INST-aaa", db_path=db)) == 2


def test_the_same_alias_is_not_stored_twice(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(), db_path=db)
    alias = InstitutionAlias(institution_id="INST-aaa", observed_name="JMI", source_id="NIRF")
    store.add_alias(alias, db_path=db)
    store.add_alias(alias, db_path=db)
    assert len(store.aliases_for("INST-aaa", db_path=db)) == 1


def test_offerings_link_a_course_to_its_institutions(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(), db_path=db)
    store.upsert_institution(_institution(institution_id="INST-bbb", canonical_name="IIT Delhi"), db_path=db)
    for iid in ["INST-aaa", "INST-bbb"]:
        store.add_offering(
            InstitutionCourseOffering(
                institution_id=iid,
                course_id="mechanical_engineering",
                discovered_from_source_id="NIRF",
                confidence=0.9,
            ),
            db_path=db,
        )

    found = store.institutions_offering("mechanical_engineering", db_path=db)
    assert sorted(i.institution_id for i in found) == ["INST-aaa", "INST-bbb"]


def test_top_ranked_institutions_come_back_in_rank_order(tmp_path):
    db = tmp_path / "i.db"
    for n, rank in [("a", 3), ("b", 1), ("c", 2)]:
        store.upsert_institution(
            _institution(institution_id=f"INST-{n}", canonical_name=n.upper(), nirf_rank=rank),
            db_path=db,
        )

    ranked = store.top_ranked(category="University", year="2025", limit=2, db_path=db)
    assert [i.nirf_rank for i in ranked] == [1, 2]


def test_one_institution_keeps_a_ranking_in_every_category(tmp_path):
    # An institution ranked in several categories has several ranks. Storing the
    # rank on the institution row means the last category crawled overwrites the
    # rest -- which hid IIT Madras, rank 1 in Engineering, behind its rank in a
    # later category.
    db = tmp_path / "i.db"
    store.upsert_institution(_institution(nirf_rank=1, ranking_category="Engineering"), db_path=db)
    store.upsert_institution(_institution(nirf_rank=17, ranking_category="Overall"), db_path=db)

    engineering = store.top_ranked(category="Engineering", year="2025", limit=5, db_path=db)
    overall = store.top_ranked(category="Overall", year="2025", limit=5, db_path=db)

    assert [i.nirf_rank for i in engineering] == [1]
    assert [i.nirf_rank for i in overall] == [17]
    assert store.count_institutions(db_path=db) == 1
