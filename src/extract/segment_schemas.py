"""Field schemas per segment, for generating content where no source exists.

Four segments have real fact models and take their field names from them, so
generation and extraction populate the same shape. The other ten have no fact
model yet (see src/facts/ -- only Course, EligibilityRule, Curriculum and
Specialisation are built), so their fields here are PROVISIONAL: they follow
the F-number ranges in planner.py::SEGMENT_FIELD_IDS but the names have not
been reconciled against the client's Data Fields sheet. Reconcile before these
reach a published page.
"""

from src.facts.segment_facts import SEGMENT_FACTS
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

# Derived from the fact models, not hand-written. These were provisional names
# invented before src/facts/segment_facts.py existed, and the two drifted: Fees
# generated 5 fields while extraction wrote 12, so a block's shape depended on
# whether it happened to be sourced or generated. Generating into the same
# F-numbered fields extraction writes is what makes a sourced and a generated
# Fees block interchangeable on the page.
_TYPE_HINTS = {
    "list[str]": "list of strings",
    "int": "integer",
    "bool": "true or false",
}


def _describe(fact_model, name: str) -> str:
    annotation = str(fact_model.model_fields[name].annotation)
    for needle, hint in _TYPE_HINTS.items():
        if needle in annotation:
            return hint
    if any(token in name for token in ("fee", "salary", "amount", "cost", "income")):
        return "indicative range as a string, never a single precise figure"
    if any(token in name for token in ("year", "date", "deadline")):
        return "typical period as a string, never a specific date"
    return "string"


_PROVISIONAL = {
    segment: {name: _describe(fact_model, name) for name in field_ids}
    for segment, (fact_model, field_ids) in SEGMENT_FACTS.items()
}

# Ranking lives in src/facts/models.py rather than segment_facts, because it
# predates that module and already holds 871 real NIRF rows. It still needs a
# generation shape for courses NIRF does not rank, so it is added by hand here
# rather than being the one segment on the page with no fallback.
_PROVISIONAL["Ranking & Accreditation"] = {
    "ranking_body": "string, e.g. NIRF",
    "ranking_year": "typical period as a string, never a specific year",
    "ranking_category": "string",
    "rank": "integer",
    "rank_band": "indicative band as a string, never a single rank",
    "ranking_score": "string",
    "naac_status": "string",
    "nba_programme_status": "string",
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
