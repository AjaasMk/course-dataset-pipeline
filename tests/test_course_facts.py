import pytest

from src.facts import course_store as store
from src.facts.models import CitationRequired, VerificationStatus
from src.facts.course_facts import Course, Curriculum, EligibilityRule, Specialisation


def _ref(field_id, document_id="DOC-1", text="evidence text"):
    return store.field_ref(field_id, document_id, text, VerificationStatus.AI_CHECKED)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "course_facts.db"


# --- Course: one current row per course, per-field citation ---------------


def test_a_course_round_trips_with_a_citation_per_populated_field(db):
    course = Course(
        course_id="mech",
        standard_course_name="Mechanical Engineering",
        regulating_body="AICTE",
    )
    refs = [_ref("F001", "DOC-ugc"), _ref("F007", "DOC-aicte")]

    store.record_course(course, refs=refs, db_path=db)
    current = store.current_course("mech", db_path=db)

    assert current.standard_course_name == "Mechanical Engineering"


def test_different_fields_may_cite_different_documents(db):
    course = Course(course_id="mech", standard_course_name="Mechanical Engineering", regulating_body="AICTE")
    refs = [_ref("F001", "DOC-ugc"), _ref("F007", "DOC-aicte")]
    record_id = store.record_course(course, refs=refs, db_path=db)

    by_field = {r.field_id: r.document_id for r in store.refs_for("courses", record_id, db_path=db)}

    assert by_field["F001"] == "DOC-ugc"
    assert by_field["F007"] == "DOC-aicte"


def test_a_populated_field_with_no_citation_is_rejected(db):
    # regulating_body is populated but only F001 is cited -- Hard Constraint 2.
    course = Course(course_id="mech", standard_course_name="Mechanical Engineering", regulating_body="AICTE")

    with pytest.raises(CitationRequired) as caught:
        store.record_course(course, refs=[_ref("F001")], db_path=db)

    assert "regulating_body" in str(caught.value) or "F007" in str(caught.value)


def test_a_null_field_needs_no_citation(db):
    # Hard Constraint 4: null over fabrication. abbreviation is left unset and
    # must not force a citation that doesn't exist.
    course = Course(course_id="mech", standard_course_name="Mechanical Engineering")

    store.record_course(course, refs=[_ref("F001")], db_path=db)

    assert store.current_course("mech", db_path=db).abbreviation is None


def test_a_changed_course_field_supersedes(db):
    store.record_course(
        Course(course_id="mech", standard_course_name="Mechanical Engineering", credit_count=120),
        refs=[_ref("F001"), _ref("F012")],
        db_path=db,
    )
    store.record_course(
        Course(course_id="mech", standard_course_name="Mechanical Engineering", credit_count=140),
        refs=[_ref("F001"), _ref("F012")],
        db_path=db,
    )

    current = store.current_course("mech", db_path=db)
    history = store.course_history("mech", db_path=db)

    assert current.credit_count == 140
    assert sorted(h.credit_count for h in history) == [120, 140]


# --- Eligibility: versioned by (course_id, eligibility_year) --------------


def test_two_eligibility_years_coexist(db):
    store.record_eligibility(
        EligibilityRule(course_id="mech", eligibility_year="2025", minimum_percentage="45%"),
        refs=[_ref("F023")],
        db_path=db,
    )
    store.record_eligibility(
        EligibilityRule(course_id="mech", eligibility_year="2026", minimum_percentage="50%"),
        refs=[_ref("F023")],
        db_path=db,
    )

    both = store.eligibility_for_years("mech", ["2025", "2026"], db_path=db)

    assert sorted((e.eligibility_year, e.minimum_percentage) for e in both) == [
        ("2025", "45%"),
        ("2026", "50%"),
    ]


def test_eligibility_missing_a_citation_is_rejected(db):
    rule = EligibilityRule(course_id="mech", eligibility_year="2025", minimum_percentage="45%")

    with pytest.raises(CitationRequired):
        store.record_eligibility(rule, refs=[], db_path=db)


# --- Curriculum: versioned by (course_id, curriculum_year) ----------------


def test_curriculum_changes_are_versioned_not_overwritten(db):
    store.record_curriculum(
        Curriculum(course_id="mech", curriculum_year="2023", core_subjects=["Thermodynamics"]),
        refs=[_ref("F042")],
        db_path=db,
    )
    store.record_curriculum(
        Curriculum(course_id="mech", curriculum_year="2025", core_subjects=["Thermodynamics", "AI for ME"]),
        refs=[_ref("F042")],
        db_path=db,
    )

    current = store.current_curriculum("mech", "2025", db_path=db)
    old = store.current_curriculum("mech", "2023", db_path=db)

    assert current.core_subjects == ["Thermodynamics", "AI for ME"]
    assert old.core_subjects == ["Thermodynamics"]


# --- Specialisation: one-to-many per course --------------------------------


def test_a_course_holds_several_specialisations(db):
    for name in ["Robotics", "Thermal Engineering"]:
        store.record_specialisation(
            Specialisation(course_id="mech", specialisation_name=name, available_at_level="Postgraduate"),
            refs=[_ref("F051"), _ref("F052")],
            db_path=db,
        )

    found = store.specialisations_for("mech", db_path=db)

    assert sorted(s.specialisation_name for s in found) == ["Robotics", "Thermal Engineering"]


def test_a_specialisation_re_recorded_unchanged_does_not_duplicate(db):
    spec = Specialisation(course_id="mech", specialisation_name="Robotics", available_at_level="Postgraduate")

    store.record_specialisation(spec, refs=[_ref("F051"), _ref("F052")], db_path=db)
    store.record_specialisation(spec, refs=[_ref("F051"), _ref("F052")], db_path=db)

    assert len(store.specialisations_for("mech", db_path=db)) == 1
