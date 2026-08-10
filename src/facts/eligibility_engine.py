from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.facts.course_facts import ELIGIBILITY_FIELD_IDS, EligibilityRule

CheckResult = Literal["pass", "fail", "unknown"]
Verdict = Literal["eligible", "not_eligible", "insufficient_data"]

# Fields stored as free text on EligibilityRule ("75% aggregate", "60%
# (55% for reserved category)", "Must be 17 by December 31"). Regex-
# parsing arbitrary text like this into comparable numbers risks a
# confidently WRONG pass/fail -- exactly the false precision Hard
# Constraint 4 exists to prevent. These are never auto-evaluated; they
# surface as explicit manual-check items instead.
_UNPARSED_TEXT_FIELDS = ("minimum_qualification", "minimum_percentage", "age_requirement", "international_equivalence")


class ApplicantProfile(BaseModel):
    """The applicant-side facts an eligibility check needs. Deliberately
    has no percentage/age fields -- see _UNPARSED_TEXT_FIELDS."""

    stream: Optional[str] = None
    subjects_completed: list[str] = Field(default_factory=list)
    has_portfolio: Optional[bool] = None
    wants_lateral_entry: bool = False


class EligibilityCheck(BaseModel):
    field_id: str
    condition: str
    result: CheckResult
    detail: str


class EligibilityVerdict(BaseModel):
    course_id: str
    eligibility_year: str
    overall: Verdict
    checks: list[EligibilityCheck] = Field(default_factory=list)
    # Real rule conditions that exist but were never evaluated, because
    # they're free text -- always non-empty here means overall can never
    # honestly be "eligible", regardless of how the structured checks went.
    unparsed_conditions: list[str] = Field(default_factory=list)
    # Real, structured rule facts that matter to an applicant but aren't
    # eligibility gates (interview_required is a process step, not a
    # pass/fail condition; medical_requirement is informational).
    notes: list[str] = Field(default_factory=list)


def _check_streams(rule: EligibilityRule, profile: ApplicantProfile) -> Optional[EligibilityCheck]:
    if not rule.accepted_streams:
        return None
    field_id = ELIGIBILITY_FIELD_IDS["accepted_streams"]
    condition = f"stream in {rule.accepted_streams}"
    if profile.stream is None:
        return EligibilityCheck(field_id=field_id, condition=condition, result="unknown", detail="applicant stream not provided")
    if profile.stream in rule.accepted_streams:
        return EligibilityCheck(field_id=field_id, condition=condition, result="pass", detail=f"{profile.stream} is accepted")
    return EligibilityCheck(
        field_id=field_id, condition=condition, result="fail",
        detail=f"{profile.stream} is not in the accepted streams {rule.accepted_streams}",
    )


def _check_compulsory_subjects(rule: EligibilityRule, profile: ApplicantProfile) -> Optional[EligibilityCheck]:
    if not rule.compulsory_subjects:
        return None
    field_id = ELIGIBILITY_FIELD_IDS["compulsory_subjects"]
    condition = f"compulsory subjects {rule.compulsory_subjects} all completed"
    if not profile.subjects_completed:
        return EligibilityCheck(field_id=field_id, condition=condition, result="unknown", detail="applicant's completed subjects not provided")
    missing = [s for s in rule.compulsory_subjects if s not in profile.subjects_completed]
    if not missing:
        return EligibilityCheck(field_id=field_id, condition=condition, result="pass", detail="all compulsory subjects completed")
    return EligibilityCheck(field_id=field_id, condition=condition, result="fail", detail=f"missing: {missing}")


def _check_portfolio(rule: EligibilityRule, profile: ApplicantProfile) -> Optional[EligibilityCheck]:
    if rule.portfolio_required is not True:
        return None
    field_id = ELIGIBILITY_FIELD_IDS["portfolio_required"]
    condition = "portfolio required"
    if profile.has_portfolio is None:
        return EligibilityCheck(field_id=field_id, condition=condition, result="unknown", detail="applicant portfolio status not provided")
    if profile.has_portfolio:
        return EligibilityCheck(field_id=field_id, condition=condition, result="pass", detail="applicant has a portfolio")
    return EligibilityCheck(field_id=field_id, condition=condition, result="fail", detail="course requires a portfolio; applicant has none")


def _check_lateral_entry(rule: EligibilityRule, profile: ApplicantProfile) -> Optional[EligibilityCheck]:
    # Only relevant if the applicant is actually asking for lateral entry --
    # lateral_entry_available says nothing about a normal-entry applicant.
    if not profile.wants_lateral_entry:
        return None
    field_id = ELIGIBILITY_FIELD_IDS["lateral_entry_available"]
    condition = "lateral entry available"
    if rule.lateral_entry_available is None:
        return EligibilityCheck(field_id=field_id, condition=condition, result="unknown", detail="rule does not state whether lateral entry is available")
    if rule.lateral_entry_available:
        return EligibilityCheck(field_id=field_id, condition=condition, result="pass", detail="lateral entry is available")
    return EligibilityCheck(field_id=field_id, condition=condition, result="fail", detail="lateral entry is not available for this course")


def evaluate_eligibility(rule: EligibilityRule, profile: ApplicantProfile) -> EligibilityVerdict:
    checks = [
        c for c in (
            _check_streams(rule, profile),
            _check_compulsory_subjects(rule, profile),
            _check_portfolio(rule, profile),
            _check_lateral_entry(rule, profile),
        ) if c is not None
    ]

    unparsed = [field for field in _UNPARSED_TEXT_FIELDS if getattr(rule, field) is not None]

    notes = []
    if rule.interview_required:
        notes.append("Interview required as part of the admission process.")
    if rule.medical_requirement:
        notes.append(f"Medical requirement: {rule.medical_requirement}")

    if any(c.result == "fail" for c in checks):
        overall: Verdict = "not_eligible"
    elif any(c.result == "unknown" for c in checks) or unparsed:
        overall = "insufficient_data"
    else:
        overall = "eligible"

    return EligibilityVerdict(
        course_id=rule.course_id,
        eligibility_year=rule.eligibility_year,
        overall=overall,
        checks=checks,
        unparsed_conditions=unparsed,
        notes=notes,
    )
