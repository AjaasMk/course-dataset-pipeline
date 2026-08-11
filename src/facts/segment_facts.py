from typing import Optional

from enum import Enum

from pydantic import BaseModel, Field


class RouteBadge(str, Enum):
    """The five route badges the client's career cards render, verbatim."""

    AFTER_BACHELORS = "Possible after bachelor's"
    TRAINING_REQUIRED = "Training may be required"
    POSTGRADUATE = "Postgraduate route"
    REGULATED = "Advanced regulated route"
    HIGHER_STUDY = "Higher study required"

# The seven segments the client's page needs that had no fact model, so
# extraction had nowhere to write and they fell through to generation even
# where real regulator documents had been retrieved and chunked. Measured
# 2026-08-11: 165 course-segment pairs across the 25-course pilot held real
# sources and were set to show invented content instead.
#
# Field names and F-numbers come from the client's own Data Fields sheet,
# read directly rather than inferred from the F-number ranges in planner.py --
# those ranges were right about the spans but say nothing about the names.
#
# Fields numbered P0xx are provisional: the client's page renders them but the
# Data Fields sheet assigns no ID. They are gated exactly like F-numbers, so an
# uncited value in one is nulled the same way -- nothing slips past Hard
# Constraint 2 while the client decides whether to adopt them.
#
# Ranking & Accreditation (F072-F079) is deliberately absent: src/facts/models.py
# already has Ranking, with 871 real NIRF rows behind it.


class EntranceAdmission(BaseModel):
    """F031-F040. One row per exam per year -- a course commonly accepts
    several entrance routes (JEE and a state CET), and each is its own fact
    with its own dates, not a field on the course."""

    record_id: Optional[str] = None
    course_id: str
    exam_name: str
    exam_year: Optional[str] = None
    conducting_body: Optional[str] = None
    applicable_courses: list[str] = Field(default_factory=list)
    applicable_institutions: list[str] = Field(default_factory=list)
    application_start: Optional[str] = None
    application_end: Optional[str] = None
    exam_date: Optional[str] = None
    counselling_body: Optional[str] = None
    official_information_bulletin: Optional[str] = None
    # The page renders a five-step admission pathway ("Check eligibility" ->
    # "Confirm admission") that the Data Fields sheet does not model at all.
    admission_steps: list[str] = Field(default_factory=list)
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class FeeStructure(BaseModel):
    """F080-F091. Keyed by fee_year and quota_or_seat_type: the same course at
    the same institution charges different amounts under merit and management
    quotas, and collapsing them into one figure is how a fee page misleads.

    Amounts stay strings. The sources publish "Rs 45,000 per annum",
    "45000/-" and "Rs 0.45 lakh", and parsing those into a number would put a
    confident figure behind a guess about the unit."""

    record_id: Optional[str] = None
    course_id: str
    fee_year: str
    quota_or_seat_type: Optional[str] = None
    tuition_fee: Optional[str] = None
    admission_fee: Optional[str] = None
    examination_fee: Optional[str] = None
    laboratory_fee: Optional[str] = None
    library_fee: Optional[str] = None
    caution_deposit: Optional[str] = None
    hostel_fee: Optional[str] = None
    mess_fee: Optional[str] = None
    transport_fee: Optional[str] = None
    total_estimated_cost: Optional[str] = None
    # The page's fee table is long-format -- one row per cost category with a
    # frequency and a note for parents. The sheet is wide-format, one column
    # per fee. These two carry the columns the wide shape cannot express.
    fee_frequency: Optional[str] = None
    parent_check_note: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class CareerMapping(BaseModel):
    """F102-F111. One row per occupation a course leads to.

    relationship_strength and direct_entry_possible carry the distinction the
    client's own demo page makes between a role a graduate can take now and one
    that needs postgraduate study or registration -- the difference between
    'Research Assistant' and 'Clinical Psychologist'."""

    record_id: Optional[str] = None
    course_id: str
    occupation_id: str
    # The page renders this as one of five route badges, not free text:
    # "Possible after bachelor's", "Training may be required", "Postgraduate
    # route", "Advanced regulated route", "Higher study required". Constrained
    # so a value that cannot be rendered fails here rather than on the page.
    relationship_strength: Optional[RouteBadge] = None
    direct_entry_possible: Optional[bool] = None
    additional_degree_required: Optional[str] = None
    licence_required: Optional[str] = None
    preferred_skills: list[str] = Field(default_factory=list)
    typical_entry_role: Optional[str] = None
    career_progression: Optional[str] = None
    government_opportunities: Optional[str] = None
    self_employment_possible: Optional[str] = None
    # The career card's body sentence. typical_entry_role names the role and
    # career_progression names the route; neither is the description the card
    # renders between them.
    career_note: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class SalaryObservation(BaseModel):
    """F112-F123. An observation, not a salary: the same course reports
    different figures by role, experience, region and industry, and the record
    is only meaningful with those qualifiers attached.

    sample_size is why this is a separate model rather than three fields on the
    course -- a median over 12 offers and one over 4,000 are not comparable,
    and the client's demo page asks for exactly this to be shown."""

    record_id: Optional[str] = None
    course_id: str
    salary_course: Optional[str] = None
    salary_job_role: Optional[str] = None
    qualification_level: Optional[str] = None
    experience_level: Optional[str] = None
    city_or_region: Optional[str] = None
    industry: Optional[str] = None
    salary_type: Optional[str] = None
    salary_min: Optional[str] = None
    salary_average: Optional[str] = None
    salary_max: Optional[str] = None
    sample_size: Optional[int] = None
    salary_source_year: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class PlacementRecord(BaseModel):
    """F124-F132. One row per recruiter per institution per year.

    verified_status exists because the client's Mandatory Human Review Matrix
    names recruiter claims as high-risk: a logo on a course page implies an
    offer that may never have been made to that course's graduates."""

    record_id: Optional[str] = None
    course_id: str
    recruiter_name: str
    placement_institution: Optional[str] = None
    course_or_department: Optional[str] = None
    # A list, not a string: every recruiter card on the page shows two or more
    # role chips. Changed before any extraction has written to it, when the
    # change is free.
    role_recruited_for: list[str] = Field(default_factory=list)
    recruiter_sector: Optional[str] = None
    recruiter_note: Optional[str] = None
    placement_year: Optional[str] = None
    number_hired: Optional[int] = None
    placement_scope: Optional[str] = None
    official_report: Optional[str] = None
    verified_status: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


class InstitutionOfferingFact(BaseModel):
    """F057-F071. One row per institution offering the course.

    Named to stay out of the way of src/facts/models.py::InstitutionOffering,
    which is the retrieval-side link between an institution and a course. This
    is the client's Data Fields row -- recognition status, approvals, intake --
    and conflating the two would put regulatory claims in a table built for
    candidate matching."""

    record_id: Optional[str] = None
    course_id: str
    official_institution_name: str
    previous_name: Optional[str] = None
    institution_type: Optional[str] = None
    ownership_type: Optional[str] = None
    affiliating_university: Optional[str] = None
    autonomous_status: Optional[str] = None
    ugc_status: Optional[str] = None
    aicte_status: Optional[str] = None
    professional_council_status: Optional[str] = None
    aishe_code: Optional[str] = None
    nirf_id: Optional[str] = None
    campus: Optional[str] = None
    intake: Optional[int] = None
    approval_academic_year: Optional[str] = None
    official_course_url: Optional[str] = None
    # Everything the ranked college card shows that the sheet does not model.
    # annual_fee is per-institution: FeeStructure is course-level, so it cannot
    # answer "what does THIS college charge", which is what the card renders.
    city_or_region: Optional[str] = None
    course_variant: Optional[str] = None
    admission_route: Optional[str] = None
    offering_highlight: Optional[str] = None
    annual_fee: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None


ENTRANCE_FIELD_IDS = {
    "exam_name": "F031",
    "exam_year": "F032",
    "conducting_body": "F033",
    "applicable_courses": "F034",
    "applicable_institutions": "F035",
    "application_start": "F036",
    "application_end": "F037",
    "exam_date": "F038",
    "counselling_body": "F039",
    "official_information_bulletin": "F040",
    "admission_steps": "P002",
}

FEES_FIELD_IDS = {
    "tuition_fee": "F080",
    "admission_fee": "F081",
    "examination_fee": "F082",
    "laboratory_fee": "F083",
    "library_fee": "F084",
    "caution_deposit": "F085",
    "hostel_fee": "F086",
    "mess_fee": "F087",
    "transport_fee": "F088",
    "fee_year": "F089",
    "quota_or_seat_type": "F090",
    "total_estimated_cost": "F091",
    "fee_frequency": "P003",
    "parent_check_note": "P004",
}

CAREER_FIELD_IDS = {
    "occupation_id": "F102",
    "relationship_strength": "F103",
    "direct_entry_possible": "F104",
    "additional_degree_required": "F105",
    "licence_required": "F106",
    "preferred_skills": "F107",
    "typical_entry_role": "F108",
    "career_progression": "F109",
    "government_opportunities": "F110",
    "self_employment_possible": "F111",
    "career_note": "P012",
}

SALARY_FIELD_IDS = {
    "salary_course": "F112",
    "salary_job_role": "F113",
    "qualification_level": "F114",
    "experience_level": "F115",
    "city_or_region": "F116",
    "industry": "F117",
    "salary_type": "F118",
    "salary_min": "F119",
    "salary_average": "F120",
    "salary_max": "F121",
    "sample_size": "F122",
    "salary_source_year": "F123",
}

PLACEMENT_FIELD_IDS = {
    "placement_institution": "F124",
    "course_or_department": "F125",
    "recruiter_name": "F126",
    "role_recruited_for": "F127",
    "placement_year": "F128",
    "number_hired": "F129",
    "placement_scope": "F130",
    "official_report": "F131",
    "verified_status": "F132",
    "recruiter_sector": "P005",
    "recruiter_note": "P006",
}

OFFERING_FIELD_IDS = {
    "official_institution_name": "F057",
    "previous_name": "F058",
    "institution_type": "F059",
    "ownership_type": "F060",
    "affiliating_university": "F061",
    "autonomous_status": "F062",
    "ugc_status": "F063",
    "aicte_status": "F064",
    "professional_council_status": "F065",
    "aishe_code": "F066",
    "nirf_id": "F067",
    "campus": "F068",
    "intake": "F069",
    "approval_academic_year": "F070",
    "official_course_url": "F071",
    "city_or_region": "P007",
    "course_variant": "P008",
    "admission_route": "P009",
    "offering_highlight": "P010",
    "annual_fee": "P011",
}

# What each segment stores, so extraction and the page can both look it up by
# the segment name the rest of the pipeline already uses.
SEGMENT_FACTS = {
    "Entrance & Admission": (EntranceAdmission, ENTRANCE_FIELD_IDS),
    "Fees": (FeeStructure, FEES_FIELD_IDS),
    "Career Mapping": (CareerMapping, CAREER_FIELD_IDS),
    "Salary": (SalaryObservation, SALARY_FIELD_IDS),
    "Recruiters & Placement": (PlacementRecord, PLACEMENT_FIELD_IDS),
    "Institution & Offering": (InstitutionOfferingFact, OFFERING_FIELD_IDS),
}
