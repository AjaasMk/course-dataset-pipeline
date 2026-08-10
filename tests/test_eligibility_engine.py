from src.facts.course_facts import EligibilityRule
from src.facts.eligibility_engine import ApplicantProfile, evaluate_eligibility


def _rule(**overrides):
    fields = {
        "course_id": "mechanical_engineering",
        "eligibility_year": "2026",
        "accepted_streams": ["Science"],
        "compulsory_subjects": ["Physics", "Chemistry", "Mathematics"],
    }
    fields.update(overrides)
    return EligibilityRule(**fields)


def test_eligible_when_every_structured_condition_is_satisfied():
    rule = _rule()
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics", "English"])

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "eligible"
    assert all(c.result == "pass" for c in verdict.checks)


def test_not_eligible_when_stream_does_not_match():
    rule = _rule()
    profile = ApplicantProfile(stream="Commerce", subjects_completed=["Physics", "Chemistry", "Mathematics"])

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "not_eligible"
    failing = [c for c in verdict.checks if c.result == "fail"]
    assert any(c.field_id == "F020" for c in failing)  # accepted_streams


def test_not_eligible_when_a_compulsory_subject_is_missing():
    rule = _rule()
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Mathematics"])  # no Chemistry

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "not_eligible"
    failing = [c for c in verdict.checks if c.result == "fail"]
    assert any(c.field_id == "F021" for c in failing)  # compulsory_subjects


def test_a_hard_fail_wins_even_if_other_conditions_are_unknown():
    rule = _rule(portfolio_required=True)
    # stream fails; portfolio status unknown (profile doesn't say) -- must
    # still report not_eligible, not insufficient_data, once anything hard-fails
    profile = ApplicantProfile(stream="Arts", subjects_completed=["Physics", "Chemistry", "Mathematics"])

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "not_eligible"


def test_insufficient_data_when_a_condition_cannot_be_checked_and_nothing_fails():
    rule = _rule(portfolio_required=True)
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics"])
    # has_portfolio left unset

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "insufficient_data"
    unknowns = [c for c in verdict.checks if c.result == "unknown"]
    assert any(c.field_id == "F026" for c in unknowns)  # portfolio_required


def test_free_text_conditions_are_never_auto_evaluated():
    # minimum_percentage is free text ("75% aggregate", "60% (55% for
    # reserved category)") -- deterministically parsing arbitrary text like
    # this risks a confidently wrong pass/fail. It must surface as a
    # manual-check item, never silently skipped and never guessed at.
    rule = _rule(minimum_percentage="75% aggregate in PCM", age_requirement="Must be 17 by December 31")
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics"])

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "insufficient_data"
    assert "minimum_percentage" in " ".join(verdict.unparsed_conditions)
    assert "age_requirement" in " ".join(verdict.unparsed_conditions)
    # and it must not appear as a pass/fail check pretending to be evaluated
    assert not any(c.field_id == "F023" for c in verdict.checks)  # minimum_percentage


def test_absent_free_text_conditions_produce_no_unparsed_entries():
    rule = _rule()  # minimum_percentage, age_requirement etc. left null
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics"])

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.unparsed_conditions == []
    assert verdict.overall == "eligible"


def test_no_applicable_rule_conditions_at_all_is_eligible_by_default():
    rule = EligibilityRule(course_id="x", eligibility_year="2026")  # nothing set
    profile = ApplicantProfile()

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "eligible"
    assert verdict.checks == []


def test_lateral_entry_request_checked_against_rule_when_applicant_wants_it():
    rule = _rule(lateral_entry_available=False)
    profile = ApplicantProfile(
        stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics"],
        wants_lateral_entry=True,
    )

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "not_eligible"


def test_lateral_entry_not_checked_when_applicant_does_not_want_it():
    rule = _rule(lateral_entry_available=False)
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics"])

    verdict = evaluate_eligibility(rule, profile)

    assert verdict.overall == "eligible"  # lateral_entry_available is irrelevant unless requested


def test_interview_and_medical_requirements_surface_as_informational_notes():
    rule = _rule(interview_required=True, medical_requirement="Fitness certificate from a registered medical practitioner")
    profile = ApplicantProfile(stream="Science", subjects_completed=["Physics", "Chemistry", "Mathematics"])

    verdict = evaluate_eligibility(rule, profile)

    # interview_required is a real, structured bool but is a process step,
    # not an eligibility gate -- never a pass/fail determinant
    assert not any(c.field_id == "F027" for c in verdict.checks)  # interview_required
    assert any("interview" in note.lower() for note in verdict.notes)
    assert any("medical" in note.lower() for note in verdict.notes)
