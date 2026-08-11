from typing import Optional

from pydantic import BaseModel, Field


class Course(BaseModel):
    """F001-F018 (Course Identity + Duration & Mode). One current row per
    course -- genuinely 1:1, unlike Eligibility/Curriculum/Specialisation."""

    record_id: Optional[str] = None
    course_id: str
    standard_course_name: str
    common_course_name: Optional[str] = None
    abbreviation: Optional[str] = None
    qualification_level: Optional[str] = None
    qualification_type: Optional[str] = None
    academic_or_vocational: Optional[str] = None
    regulating_body: Optional[str] = None
    course_aliases: list[str] = Field(default_factory=list)
    minimum_duration: Optional[str] = None
    maximum_duration: Optional[str] = None
    semester_count: Optional[int] = None
    credit_count: Optional[int] = None
    study_mode: Optional[str] = None
    full_time_available: Optional[bool] = None
    part_time_available: Optional[bool] = None
    online_available: Optional[bool] = None
    distance_available: Optional[bool] = None
    exit_options: list[str] = Field(default_factory=list)
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class EligibilityRule(BaseModel):
    """F019-F030. Versioned by (course_id, eligibility_year): the client's
    Mandatory Human Review Matrix refreshes eligibility every admission
    cycle, so 2025's rule and 2026's rule are both real, distinct facts."""

    record_id: Optional[str] = None
    course_id: str
    eligibility_year: str
    minimum_qualification: Optional[str] = None
    accepted_streams: list[str] = Field(default_factory=list)
    compulsory_subjects: list[str] = Field(default_factory=list)
    recommended_subjects: list[str] = Field(default_factory=list)
    minimum_percentage: Optional[str] = None
    age_requirement: Optional[str] = None
    medical_requirement: Optional[str] = None
    portfolio_required: Optional[bool] = None
    interview_required: Optional[bool] = None
    lateral_entry_available: Optional[bool] = None
    international_equivalence: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class Curriculum(BaseModel):
    """F041-F050. Versioned by (course_id, curriculum_year): refreshes when
    the regulation changes, per the Segment Sources sheet."""

    record_id: Optional[str] = None
    course_id: str
    curriculum_year: str
    foundation_subjects: list[str] = Field(default_factory=list)
    core_subjects: list[str] = Field(default_factory=list)
    electives: list[str] = Field(default_factory=list)
    practical_components: Optional[str] = None
    laboratory_components: Optional[str] = None
    internship: Optional[str] = None
    fieldwork: Optional[str] = None
    project: Optional[str] = None
    dissertation: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class Specialisation(BaseModel):
    """F051-F056. One-to-many per course, keyed by specialisation_name -- an
    MBA has several specialisations (HR, Finance, Marketing), each its own
    fact, not a flat string list on the course."""

    record_id: Optional[str] = None
    course_id: str
    specialisation_name: str
    available_at_level: Optional[str] = None
    parent_course: Optional[str] = None
    typical_subjects: list[str] = Field(default_factory=list)
    career_focus: Optional[str] = None
    specialisation_type: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


# Field-name -> client Field ID, one map per table. Used to verify every
# POPULATED field carries a citation (Hard Constraint 2) while leaving null
# fields uncited (Hard Constraint 4: null over fabrication).
COURSE_FIELD_IDS = {
    "standard_course_name": "F001",
    "common_course_name": "F002",
    "abbreviation": "F003",
    "qualification_level": "F004",
    "qualification_type": "F005",
    "academic_or_vocational": "F006",
    "regulating_body": "F007",
    "course_aliases": "F008",
    "minimum_duration": "F009",
    "maximum_duration": "F010",
    "semester_count": "F011",
    "credit_count": "F012",
    "study_mode": "F013",
    "full_time_available": "F014",
    "part_time_available": "F015",
    "online_available": "F016",
    "distance_available": "F017",
    "exit_options": "F018",
}

ELIGIBILITY_FIELD_IDS = {
    "minimum_qualification": "F019",
    "accepted_streams": "F020",
    "compulsory_subjects": "F021",
    "recommended_subjects": "F022",
    "minimum_percentage": "F023",
    "age_requirement": "F024",
    "medical_requirement": "F025",
    "portfolio_required": "F026",
    "interview_required": "F027",
    "lateral_entry_available": "F028",
    "international_equivalence": "F029",
}

CURRICULUM_FIELD_IDS = {
    "foundation_subjects": "F041",
    "core_subjects": "F042",
    "electives": "F043",
    "practical_components": "F044",
    "laboratory_components": "F045",
    "internship": "F046",
    "fieldwork": "F047",
    "project": "F048",
    "dissertation": "F049",
}

SPECIALISATION_FIELD_IDS = {
    # F051. Was absent, which exempted it from the citation gate -- a
    # specialisation could be named with no evidence and nothing objected.
    # Its sibling F050 (curriculum_year) is deliberately NOT in
    # CURRICULUM_FIELD_IDS: it is a versioning key set by the caller, like
    # course_id, so requiring a quote for it would fail every record.
    "specialisation_name": "F051",
    "available_at_level": "F052",
    "parent_course": "F053",
    "typical_subjects": "F054",
    "career_focus": "F055",
    "specialisation_type": "F056",
}
