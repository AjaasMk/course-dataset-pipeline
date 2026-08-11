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
from src.facts.segment_facts import SEGMENT_FACTS

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

_ENTRANCE = (
    "entrance examination exam name conducting body national testing agency "
    "application form opens closes last date registration schedule exam date "
    "admit card counselling seat allotment participating institutes information "
    "bulletin brochure admission notice important dates JEE NEET CUET CET GATE"
)

_FEES = (
    "fee fees fee structure tuition fee admission fee examination fee laboratory "
    "fee library fee caution deposit refundable hostel fee mess charges transport "
    "fee per annum per semester per year total cost rupees amount payable merit "
    "seat management quota NRI category government seat fee schedule"
)

_CAREER = (
    "career opportunities job roles employment occupation designation entry level "
    "role progression promotion higher study required licence registration "
    "professional practice government jobs public sector recruitment competitive "
    "examination self employment entrepreneurship freelance skills expected"
)

_SALARY = (
    "salary median salary average salary annual package CTC lakhs per annum LPA "
    "compensation remuneration pay scale stipend fresher entry level experienced "
    "senior median of placed graduates number of students placed sector industry "
    "location city survey year"
)

_PLACEMENT = (
    "placement placed recruiters recruiting companies employers hiring campus "
    "placement drive offers made number of students placed placement percentage "
    "placement report training and placement cell department wise institute wise "
    "graduating batch year top recruiters"
)

_OFFERING = (
    "institution name university college institute affiliated to affiliating "
    "university autonomous status deemed to be university government aided private "
    "self financing UGC recognised AICTE approved council approval AISHE code NIRF "
    "id campus sanctioned intake approved intake seats academic year"
)

SEGMENT_QUERIES: dict[str, str] = {
    "Curriculum": _CURRICULUM,
    "Eligibility": _ELIGIBILITY,
    "Course Identity": _COURSE,
    "Duration & Mode": _COURSE,
    "Specialisation": _SPECIALISATION,
    "Entrance & Admission": _ENTRANCE,
    "Fees": _FEES,
    "Career Mapping": _CAREER,
    "Salary": _SALARY,
    "Recruiters & Placement": _PLACEMENT,
    "Institution & Offering": _OFFERING,
}

_FIELD_IDS = {
    "Curriculum": CURRICULUM_FIELD_IDS,
    "Eligibility": ELIGIBILITY_FIELD_IDS,
    "Course Identity": COURSE_FIELD_IDS,
    "Duration & Mode": COURSE_FIELD_IDS,
    "Specialisation": SPECIALISATION_FIELD_IDS,
    **{segment: field_ids for segment, (_, field_ids) in SEGMENT_FACTS.items()},
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
