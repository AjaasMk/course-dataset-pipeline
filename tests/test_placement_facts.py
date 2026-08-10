import pytest

from src.facts.engine import field_ref
from src.facts.models import CitationRequired

# These tests were written first, against src/facts/placement_facts.py and
# placement_store.py, which are not built yet -- work paused mid-slice to chase
# a larger free win (27 unfetched AICTE model curricula). They are kept rather
# than deleted so the contract survives: the 6,872 placement records already
# parsed out of the NIRF profiles have nowhere cited to land until this exists.
pytest.importorskip("src.facts.placement_facts", reason="placement facts slice not built yet")

from src.facts.placement_facts import PLACEMENT_FIELD_IDS, InstitutionPlacement  # noqa: E402
from src.facts.placement_store import current_placement, record_placement  # noqa: E402


def _placement(**overrides):
    base = dict(
        institution_id="INST-abc",
        ranking_category="Engineering",
        academic_year="2023-24",
        programme_level="UG",
        students_graduating=210,
        students_placed=55,
        median_salary_rupees=850000,
        students_higher_studies=96,
        sanctioned_intake=463,
    )
    base.update(overrides)
    return InstitutionPlacement(**base)


def _all_refs(doc_id="DOC-1", evidence="2020-21 220 218 2021-22 4 2023-24 210 55 850000 96"):
    return [field_ref(f, doc_id, evidence) for f in PLACEMENT_FIELD_IDS.values()]


def test_a_fully_cited_placement_is_recorded_and_reads_back(tmp_path):
    db = tmp_path / "facts.db"
    record_id = record_placement(_placement(), _all_refs(), db_path=db)

    assert record_id
    found = current_placement("INST-abc", "Engineering", "2023-24", "UG", db_path=db)
    assert found is not None
    assert found.median_salary_rupees == 850000
    assert found.students_placed == 55
    assert found.students_higher_studies == 96
    assert found.sanctioned_intake == 463


def test_a_populated_field_without_a_citation_is_refused(tmp_path):
    # Hard Constraint 2 at the storage boundary: median salary is one of the
    # client's 15 Mandatory Human Review categories, so an uncited figure must
    # not be able to reach the database at all.
    db = tmp_path / "facts.db"
    partial = [r for r in _all_refs() if r.field_id != PLACEMENT_FIELD_IDS["median_salary_rupees"]]

    with pytest.raises(CitationRequired) as raised:
        record_placement(_placement(), partial, db_path=db)

    assert "median_salary_rupees" in str(raised.value)


def test_a_null_field_needs_no_citation(tmp_path):
    # Hard Constraint 4: Innovation-category profiles carry no placement table
    # at all, so those fields are legitimately null and must not be forced to
    # carry evidence that does not exist.
    db = tmp_path / "facts.db"
    intake_only = _placement(
        students_graduating=None,
        students_placed=None,
        median_salary_rupees=None,
        students_higher_studies=None,
    )
    refs = [field_ref(PLACEMENT_FIELD_IDS["sanctioned_intake"], "DOC-1", "UG [4 Years] 463")]

    record_id = record_placement(intake_only, refs, db_path=db)

    assert record_id
    found = current_placement("INST-abc", "Engineering", "2023-24", "UG", db_path=db)
    assert found.median_salary_rupees is None
    assert found.sanctioned_intake == 463


def test_a_zero_salary_still_requires_a_citation(tmp_path):
    # "0(Zero)" is a real reported value, not missing data -- so it counts as
    # populated and must be cited like any other figure.
    db = tmp_path / "facts.db"
    zeroed = _placement(median_salary_rupees=0, students_placed=0)
    partial = [r for r in _all_refs() if r.field_id != PLACEMENT_FIELD_IDS["median_salary_rupees"]]

    with pytest.raises(CitationRequired):
        record_placement(zeroed, partial, db_path=db)


def test_the_same_institution_holds_separate_rows_per_programme_level(tmp_path):
    db = tmp_path / "facts.db"
    record_placement(_placement(programme_level="UG"), _all_refs(), db_path=db)
    record_placement(
        _placement(programme_level="PG", median_salary_rupees=1600000), _all_refs(), db_path=db
    )

    ug = current_placement("INST-abc", "Engineering", "2023-24", "UG", db_path=db)
    pg = current_placement("INST-abc", "Engineering", "2023-24", "PG", db_path=db)
    assert ug.median_salary_rupees == 850000
    assert pg.median_salary_rupees == 1600000


def test_the_same_institution_holds_separate_rows_per_ranking_category(tmp_path):
    # NIRF publishes a separate submission per category, and an institution
    # ranked in both Overall and Engineering reports different placement
    # figures in each. Collapsing them would silently drop one real fact.
    db = tmp_path / "facts.db"
    record_placement(_placement(ranking_category="Engineering"), _all_refs(), db_path=db)
    record_placement(
        _placement(ranking_category="Overall", median_salary_rupees=920000), _all_refs(), db_path=db
    )

    eng = current_placement("INST-abc", "Engineering", "2023-24", "UG", db_path=db)
    overall = current_placement("INST-abc", "Overall", "2023-24", "UG", db_path=db)
    assert eng.median_salary_rupees == 850000
    assert overall.median_salary_rupees == 920000


def test_rerecording_an_unchanged_placement_does_not_manufacture_history(tmp_path):
    db = tmp_path / "facts.db"
    first = record_placement(_placement(), _all_refs(), db_path=db)
    second = record_placement(_placement(), _all_refs(), db_path=db)

    assert first == second


def test_a_changed_salary_supersedes_rather_than_overwrites(tmp_path):
    db = tmp_path / "facts.db"
    first = record_placement(_placement(), _all_refs(), db_path=db)
    second = record_placement(_placement(median_salary_rupees=875000), _all_refs(), db_path=db)

    assert first != second
    assert current_placement("INST-abc", "Engineering", "2023-24", "UG", db_path=db).median_salary_rupees == 875000
