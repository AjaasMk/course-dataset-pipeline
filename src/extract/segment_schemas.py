"""Field schemas per segment, for generating content where no source exists.

Four segments have real fact models and take their field names from them, so
generation and extraction populate the same shape. The other ten have no fact
model yet (see src/facts/ -- only Course, EligibilityRule, Curriculum and
Specialisation are built), so their fields here are PROVISIONAL: they follow
the F-number ranges in planner.py::SEGMENT_FIELD_IDS but the names have not
been reconciled against the client's Data Fields sheet. Reconcile before these
reach a published page.
"""

from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
)

_FROM_FACT_MODELS = {
    "Course Identity": {k: "string or list of strings" for k in COURSE_FIELD_IDS},
    "Duration & Mode": {k: "string or list of strings" for k in COURSE_FIELD_IDS},
    "Eligibility": {k: "string or list of strings" for k in ELIGIBILITY_FIELD_IDS},
    "Curriculum": {k: "string or list of strings" for k in CURRICULUM_FIELD_IDS},
    "Specialisation": {k: "string or list of strings" for k in SPECIALISATION_FIELD_IDS},
}

# Provisional -- no fact model exists for these yet.
_PROVISIONAL = {
    "Entrance & Admission": {
        "accepted_entrance_exams": "list of exam names commonly accepted",
        "admission_route": "merit / entrance / counselling, as a description",
        "application_window": "typical time of year, never a specific date",
        "selection_process": "string",
        "reservation_notes": "string",
    },
    "Institution & Offering": {
        "institution_types_offering": "list, e.g. central universities, state universities",
        "typical_intake_range": "indicative range, never a single figure",
        "ownership_mix": "string describing government vs private availability",
        "approval_bodies": "list of regulators that typically approve this course",
    },
    "Ranking & Accreditation": {
        "ranking_bodies": "list of bodies that rank institutions offering this course",
        "accreditation_bodies": "list",
        "ranking_notes": "string, must not state a rank for any institution",
    },
    "Fees": {
        "tuition_fee_range": "indicative range, government and private stated separately",
        "hostel_fee_range": "indicative range",
        "examination_fee": "indicative range",
        "total_indicative_cost": "indicative range for the full programme",
        "fee_notes": "string",
    },
    "Scholarships": {
        "scholarship_types": "list of the kinds commonly available",
        "eligibility_basis": "string, e.g. merit, income, category",
        "typical_award_range": "indicative range",
        "scholarship_notes": "string, must not name a specific scheme deadline",
    },
    "Career Mapping": {
        "career_titles": "list of job titles this course commonly leads to",
        "sectors": "list of employing sectors",
        "entry_level_roles": "list",
        "further_study_routes": "list",
        "regulated_roles": "list of roles requiring registration or a licence",
    },
    "Salary": {
        "entry_salary_range": "indicative annual range",
        "mid_career_salary_range": "indicative annual range",
        "factors_affecting_salary": "list",
        "salary_notes": "string, must state that figures vary widely",
    },
    "Recruiters & Placement": {
        "recruiting_sectors": "list of sectors, NOT named companies",
        "typical_roles_recruited": "list",
        "placement_notes": "string, must not state a placement percentage",
    },
}

# Explanatory segments have no atomic field to populate by design -- they are
# prose. Their shapes come from the blocks they render into in the client's own
# template, measured rather than chosen: see docs/specs/page-block-map.json.
_EXPLANATORY = {
    "Course Overview": {
        "hero_summary": "string of 30-40 words, what this course is, for a student "
        "and parent reading it first",
        "overview_paragraphs": "list of exactly 3 paragraphs of about 60 words each: "
        "what the course studies, what areas it commonly covers and how it is taught, "
        "and what it leads to including where further study is required",
    },
    "Skills Developed": {
        "skills": "list of 9 objects, each {name, description}. name is 1-3 words, "
        "description is one sentence. Mix subject knowledge with transferable skills",
    },
    "Further-Study Pathways": {
        "pathway": "list of exactly 5 short stage labels in order, from the school "
        "qualification a student enters with to a professional role",
    },
}

SEGMENT_SCHEMAS = {**_FROM_FACT_MODELS, **_PROVISIONAL, **_EXPLANATORY}

PROVISIONAL_SEGMENTS = frozenset(_PROVISIONAL)
EXPLANATORY_SCHEMA_SEGMENTS = frozenset(_EXPLANATORY)


def schema_for(segment: str) -> dict:
    return SEGMENT_SCHEMAS.get(segment, {"summary": "string"})


def is_provisional(segment: str) -> bool:
    return segment in PROVISIONAL_SEGMENTS
