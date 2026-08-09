from src.institutions.offerings import (
    CATEGORY_LEVEL_CONFIDENCE,
    candidate_offerings,
    nirf_categories_for_field,
)
from src.institutions import store
from src.institutions.models import Institution


def _institution(n: str, rank: int, category: str) -> Institution:
    return Institution(
        institution_id=f"INST-{n}",
        canonical_name=n.upper(),
        nirf_rank=rank,
        ranking_year="2025",
        ranking_category=category,
        discovered_from_source_id="NIRF",
    )


def test_engineering_field_maps_to_the_engineering_ranking():
    assert "Engineering" in nirf_categories_for_field("Engineering & Applied Technolog")


def test_computing_field_also_maps_to_engineering():
    assert "Engineering" in nirf_categories_for_field("Computing, AI & Information Sys")


def test_medicine_field_maps_to_medical_and_dental():
    categories = nirf_categories_for_field("Medicine, Dentistry & Clinical ")
    assert {"Medical", "Dental"} <= set(categories)


def test_an_unmapped_field_falls_back_to_general_rankings():
    # Performing Arts has no NIRF discipline table; the general University and
    # College rankings are the only honest candidate pool.
    assert nirf_categories_for_field("Performing Arts & Music") == ["University", "College"]


def test_candidates_come_from_the_matching_discipline_in_rank_order(tmp_path):
    db = tmp_path / "i.db"
    for n, rank in [("a", 2), ("b", 1)]:
        store.upsert_institution(_institution(n, rank, "Engineering"), db_path=db)
    store.upsert_institution(_institution("c", 1, "Law"), db_path=db)

    found = candidate_offerings(
        course_id="mechanical_engineering",
        fields=["Engineering & Applied Technolog"],
        year="2025",
        limit=5,
        db_path=db,
    )

    assert [o.institution_id for o in found] == ["INST-b", "INST-a"]


def test_candidate_confidence_reflects_discipline_level_evidence(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution("a", 1, "Engineering"), db_path=db)

    only = candidate_offerings(
        "mechanical_engineering", ["Engineering & Applied Technolog"], "2025", 5, db_path=db
    )[0]

    # Being ranked in Engineering is evidence the institution works in that
    # discipline, not that it runs this specific course. The institution's own
    # course page is what would raise this.
    assert only.confidence == CATEGORY_LEVEL_CONFIDENCE
    assert only.confidence < 0.80
    assert only.official_course_url is None


def test_a_course_in_two_fields_pools_both_disciplines(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution("a", 1, "Engineering"), db_path=db)
    store.upsert_institution(_institution("b", 1, "Architecture"), db_path=db)

    found = candidate_offerings(
        "interior_design",
        ["Engineering & Applied Technolog", "Architecture, Planning & Built"],
        "2025",
        5,
        db_path=db,
    )

    assert {o.institution_id for o in found} == {"INST-a", "INST-b"}


def test_the_same_institution_is_not_offered_twice(tmp_path):
    db = tmp_path / "i.db"
    store.upsert_institution(_institution("a", 1, "Engineering"), db_path=db)
    store.upsert_institution(_institution("a", 4, "University"), db_path=db)

    found = candidate_offerings(
        "mechanical_engineering",
        ["Engineering & Applied Technolog", "Performing Arts & Music"],
        "2025",
        5,
        db_path=db,
    )

    assert len(found) == 1
