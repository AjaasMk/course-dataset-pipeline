"""The retrieval query per segment.

Written to find the SHAPE of the content, not the course. Chunks are already
course-scoped by the time retrieval runs, so repeating the course name would
score every chunk equally and rank nothing. What separates a chunk holding
`core_subjects` from one holding a preamble is the vocabulary of a syllabus
table: subject, credits, semester, elective, laboratory.

Vocabulary follows the fields each fact model can actually hold, so a segment
never retrieves evidence for something it has nowhere to store.
"""

from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
)

# The user's stated keep-list for curriculum content: subject names, subject
# codes, credits, units, topics, learning outcomes, syllabus detail.
_CURRICULUM = (
    "core subjects foundation subjects professional core elective electives open "
    "elective subject code course code course title credits credit semester unit "
    "units syllabus scheme of instruction scheme of examination curriculum "
    "structure topics covered module modules learning outcomes course outcomes "
    "laboratory lab practical experiments project work mini project major project "
    "internship industrial training field work fieldwork dissertation thesis "
    "contact hours lecture tutorial"
)

_ELIGIBILITY = (
    "eligibility eligible minimum qualification qualifying examination passed "
    "class 12 intermediate senior secondary stream science commerce arts "
    "compulsory subjects physics chemistry mathematics biology english minimum "
    "percentage marks aggregate age limit relaxation medical fitness portfolio "
    "aptitude interview lateral entry diploma holders equivalence"
)

_COURSE = (
    "programme name course name degree awarded abbreviation nomenclature "
    "qualification level undergraduate postgraduate diploma certificate bachelor "
    "master duration years semesters total credits full time part time online "
    "distance mode of study regulating body approved by exit option multiple entry"
)

_SPECIALISATION = (
    "specialisation specialization branch stream discipline major minor honours "
    "track concentration offered specialisations available branches area of "
    "specialisation elective stream career focus"
)

SEGMENT_QUERIES: dict[str, str] = {
    "Curriculum": _CURRICULUM,
    "Eligibility": _ELIGIBILITY,
    "Course Identity": _COURSE,
    "Duration & Mode": _COURSE,
    "Specialisation": _SPECIALISATION,
}

_FIELD_IDS = {
    "Curriculum": CURRICULUM_FIELD_IDS,
    "Eligibility": ELIGIBILITY_FIELD_IDS,
    "Course Identity": COURSE_FIELD_IDS,
    "Duration & Mode": COURSE_FIELD_IDS,
    "Specialisation": SPECIALISATION_FIELD_IDS,
}


class NoQueryForSegment(KeyError):
    """Raised rather than falling back to the course name.

    A silent generic query would retrieve arbitrary chunks and look like it
    worked, which is worse than refusing -- the retrieval layer's whole purpose
    is that what reaches Sonnet was chosen, not defaulted into.
    """


def query_for(segment: str) -> str:
    if segment not in SEGMENT_QUERIES:
        raise NoQueryForSegment(
            f"no retrieval query defined for segment {segment!r}; add one to "
            f"SEGMENT_QUERIES before routing this segment through retrieval"
        )
    query = SEGMENT_QUERIES[segment]
    # Field names are part of the query on purpose: they are the vocabulary the
    # extraction prompt will ask about, so ranking on them aligns what is
    # retrieved with what will be extracted.
    return f"{query} {' '.join(_FIELD_IDS[segment])}".replace("_", " ")
