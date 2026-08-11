from typing import Literal

from rapidfuzz import fuzz, utils

from src.retrieve.models import Segment

UNCLASSIFIED: Literal["unclassified"] = "unclassified"

# Calibrated 2026-08-09 against every real heading on disk at the time (AICTE's
# Mechanical Engineering curriculum PDF: 68 ALL-CAPS headings including genuine
# section titles, front-matter noise, and faculty-name false positives from the
# heading heuristic; NIRF's two ranking pages; NTA's two exam portal pages,
# almost entirely navigation chrome). See scripts/calibrate_segment_matcher.py.
#
# First pass had no clean separation (noise up to 0.80, content down to 0.40)
# for two real reasons, not threshold tuning: the FURTHER_STUDY_PATHWAYS alias
# "higher education options" collided with "Department of Higher Education" (a
# government org name, not a further-study section) -- fixed by dropping the
# bare "higher education" phrase -- and several genuine AICTE curriculum
# headings ("TECHNOLOGY GROUP", "INDUSTRY SECTOR GROUP", "COURSE TOPICS",
# "MODE OF CONDUCT", "READINGS") had no matching alias at all -- fixed by
# adding them, from evidence, not guessed. Two ground-truth labels used for
# calibration were also wrong and got corrected, not the matcher: "1-COURSES
# ON HUMAN VALUES" is genuine curriculum content, not noise; "INTRODUCTION" is
# genuinely ambiguous (could belong to several segments) and is excluded from
# the calibration set rather than forced into either bucket.
#
# After those fixes: every labelled content heading scores >= 0.74, every
# labelled noise heading scores <= 0.57. 0.65 sits in that gap with margin on
# both sides.
SEGMENT_MATCH_THRESHOLD = 0.65

# Keyword vocabulary per segment. Government/regulator documents use their own
# vocabulary rather than the client's field names -- the same problem NIRF's
# category names and NTA's exam names posed for retrieval matching, addressed
# the same way: aliases seeded from real headings, not guessed from field names
# alone, and expected to grow as more real documents are seen.
SEGMENT_ALIASES: dict[Segment, list[str]] = {
    Segment.COURSE_IDENTITY: [
        "course name", "nomenclature", "qualification level", "degree title",
        "regulating body", "programme title", "about this document",
    ],
    Segment.COURSE_OVERVIEW: [
        "overview", "about the course", "course description", "programme overview",
        "programme educational objectives", "vision", "objectives of the programme",
    ],
    Segment.DURATION_MODE: [
        "duration", "credit distribution", "course structure", "mode of study",
        "full time", "part time", "distance mode", "online mode", "credit framework",
        "scheme of instruction and examination",
    ],
    Segment.ELIGIBILITY: [
        "eligibility", "eligibility for admission", "admission criteria",
        "minimum qualification", "entry requirements", "who can apply",
    ],
    Segment.ENTRANCE_ADMISSION: [
        "entrance examination", "admission process", "counselling", "application process",
        "how to apply", "selection procedure",
    ],
    Segment.CURRICULUM: [
        "syllabus", "curriculum", "course contents", "course outcomes", "course objective",
        "core courses", "professional elective", "laboratory", "practicals",
        "text books", "reference books", "general course structure and theme",
        "semester", "induction program", "professional core courses",
        # Added from real AICTE model-curriculum headings that scored below
        # threshold on first calibration (technology/industry elective
        # groupings, delivery mode, assessment, topic listing) -- evidence,
        # not guessed.
        "technology group", "industry sector group", "course topics",
        "mode of conduct", "assessment", "readings",
    ],
    Segment.SPECIALISATION: [
        "specialisation", "specialization", "electives offered", "branches", "streams offered",
    ],
    Segment.INSTITUTION_OFFERING: [
        "institutions offering the course", "colleges offering", "list of institutions",
        "government private aided classification", "ownership type",
    ],
    Segment.RANKING_ACCREDITATION: [
        "ranking", "accreditation", "nirf", "naac", "nba", "india rankings",
    ],
    Segment.FEES: [
        "fees", "tuition fee", "fee structure", "total cost", "cost of study",
    ],
    Segment.CAREER_MAPPING: [
        "career scope", "job roles", "occupations", "employment opportunities",
    ],
    Segment.SKILLS_DEVELOPED: [
        "skills developed", "competencies", "learning outcomes", "skill sets",
    ],
    Segment.SALARY: [
        "salary", "average salary", "compensation", "pay scale",
    ],
    Segment.RECRUITERS_PLACEMENT: [
        "recruiters", "placement", "placement record", "hiring companies",
    ],
    Segment.FURTHER_STUDY_PATHWAYS: [
        # Deliberately NOT "higher education" alone -- that phrase collides
        # with "Department of Higher Education" (a government org name that
        # appears as page furniture on many sources) and was the single
        # highest-scoring noise false positive in first calibration (0.80).
        "path to further study", "postgraduate progression", "options after graduation",
        "what to study next",
    ],
    Segment.STUDENT_REVIEWS: [
        "student reviews", "testimonials", "campus experience", "alumni feedback",
    ],
}


def classify_heading(heading: str) -> tuple[Segment, float] | tuple[Literal["unclassified"], float]:
    """Fuzzy-match a detected heading (PDF ALL-CAPS line or HTML h2/h3 text)
    against the segment alias vocabulary. Below SEGMENT_MATCH_THRESHOLD returns
    UNCLASSIFIED with its best score rather than force-matching the nearest
    segment -- a wrong segment tag is worse than no tag, since it feeds
    incorrect evidence into extraction for that segment."""
    if not heading or not heading.strip():
        return UNCLASSIFIED, 0.0

    best_segment: Segment | None = None
    best_score = 0.0
    for segment, aliases in SEGMENT_ALIASES.items():
        score = max(
            fuzz.token_set_ratio(heading, alias, processor=utils.default_process) for alias in aliases
        ) / 100
        if score > best_score:
            best_score = score
            best_segment = segment

    if best_segment is None or best_score < SEGMENT_MATCH_THRESHOLD:
        return UNCLASSIFIED, best_score
    return best_segment, best_score
