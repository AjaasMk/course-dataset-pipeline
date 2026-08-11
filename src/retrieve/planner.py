from typing import Optional

from src.courses.taxonomy import Course
from src.retrieve.models import (
    RETRIEVAL_SEGMENTS,
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.registry import SourceRegistry

USABLE_STATUSES = ("verified", "reachable")
MAX_ALIASES = 3
DEFAULT_QUALIFICATION_LEVEL = "Undergraduate"

_NON_CANONICAL = (SourceTier.D, SourceTier.E, SourceTier.F)


def _range(prefix: str, start: int, end: int) -> list[str]:
    return [f"{prefix}{n:03d}" for n in range(start, end + 1)]


SEGMENT_FIELD_IDS: dict[Segment, list[str]] = {
    Segment.COURSE_IDENTITY: _range("F", 1, 8),
    Segment.DURATION_MODE: _range("F", 9, 18),
    Segment.ELIGIBILITY: _range("F", 19, 30),
    Segment.ENTRANCE_ADMISSION: _range("F", 31, 40),
    Segment.CURRICULUM: _range("F", 41, 50),
    Segment.SPECIALISATION: _range("F", 51, 56),
    Segment.INSTITUTION_OFFERING: _range("F", 57, 71),
    Segment.RANKING_ACCREDITATION: _range("F", 72, 79),
    Segment.FEES: _range("F", 80, 91),
    Segment.SCHOLARSHIPS: _range("F", 92, 101),
    Segment.CAREER_MAPPING: _range("F", 102, 111),
    Segment.SALARY: _range("F", 112, 123),
    Segment.RECRUITERS_PLACEMENT: _range("F", 124, 132),
}


# Taxonomy field -> Regulator Map areas. segment_sources says which sources can
# serve a segment; the Regulator Map says which regulators govern a course area.
# Without intersecting them, a mechanical engineering course plans intents against
# the Dental and Nursing Councils.
_FIELD_TO_REGULATOR_AREAS = {
    "Engineering & Applied Technolog": ["engineering_technology"],
    "Computing, AI & Information Sys": ["engineering_technology"],
    "Architecture, Planning & Built": ["architecture", "engineering_technology"],
    "Medicine, Dentistry & Clinical ": ["medicine", "dentistry"],
    "Nursing, Pharmacy & Allied Heal": ["nursing", "pharmacy"],
    "Rehabilitation, Disability & Sp": ["rehabilitation_special_education"],
    "Public Health & Healthcare Mana": ["medicine"],
    "Law, Governance & Public Policy": ["law"],
    "Education & Teaching": ["teacher_education"],
    "Agriculture, Food & Natural Res": ["agriculture"],
    "Veterinary & Animal Sciences": ["agriculture"],
    "Vocational, Trades & Applied Sk": ["vocational_nsqf"],
    # Added 2026-08-10. AICTE's model-syllabus page publishes 47 curricula and
    # only 20 had ever been fetched -- not because the rest were hard to reach,
    # but because these fields fell through to general_university_degrees,
    # which has no Curriculum source, so no AICTE intent was ever issued. The
    # documents sit on a listing page the AICTE adapter already crawls,
    # including Diploma curricula for Animation, Game Design, Film and TV
    # Production and Media Communication -- courses this project had written
    # off as having no regulator at all.
    #
    # Each field is mapped because AICTE demonstrably publishes a curriculum
    # for it, checked against the real live index rather than inferred from the
    # field name. Fields with nothing on that page are deliberately left out:
    # routing a course to a regulator that publishes nothing for it only
    # manufactures unresolved intents.
    #
    # Held back until src/retrieve/matching.py::guarded_score was wired into
    # the AICTE adapter. Without it this mapping bound "Mass Communication" to
    # the Electronics and Communication Engineering syllabus at 0.84, on the
    # shared word alone.
    "Business, Management & Entrepre": ["engineering_technology"],
    "Design, Creative Arts & Fashion": ["engineering_technology"],
    "Film, Animation, Gaming & Inter": ["engineering_technology"],
    "Communication, Journalism & Med": ["engineering_technology"],
    "Life Sciences & Biotechnology": ["engineering_technology"],
}
_DEFAULT_REGULATOR_AREA = "general_university_degrees"

# NTA/CUET publish per-EXAM pages (Joint Entrance Examination, NEET,
# CUET-UG), not per-COURSE pages -- fuzzy-matching a course name alone
# against an exam title structurally caps out around 0.4-0.5 (confirmed
# live, e.g. "Physics (Core)" vs "Joint Entrance Examination": 0.50),
# comfortably below the 0.80 match threshold no matter how good the fuzzy
# matcher is, because the two strings describe different things. This maps
# a course's regulator area to the exam vocabulary that source actually
# indexes under -- ONLY for areas verified against NTA's real 10-exam
# index (src/retrieve/nta.py), not guessed. Areas with a real national
# entrance exam NOT administered by NTA (architecture/NATA via COA,
# law/CLAT via the NLU Consortium) are deliberately left out: forcing a
# match against NTA's index for those would either find nothing (honest
# unresolved, no regression) or, worse, coincidentally match an unrelated
# NTA exam -- omission is the safe default here, not an oversight.
#
# Bare acronyms ONLY, never a full official title. Confirmed live: the
# full title "Joint Entrance Examination" scores 1.00 against BOTH the
# correct jeemain document AND "Hotel Management Joint Entrance
# Examination" (nchm-jee) -- token_set_ratio treats the shorter title as a
# full token-subset of the longer one. "All India Entrance Examination"
# has the same problem (0.80-0.87 against unrelated exams that happen to
# share "Entrance Examination" wording). Bare acronyms route through
# NTA's own curated _EXAM_ALIASES vocabulary instead of a literal-substring
# match against raw titles, and were confirmed live to have zero
# collisions across all 10 real NTA exam titles (src/retrieve/nta.py,
# see test_known_limitation_a_full_exam_title_...).
_AREA_TO_EXAM_TERMS: dict[str, list[str]] = {
    "engineering_technology": ["JEE"],
    "medicine": ["NEET"],
    "dentistry": ["NEET"],
    "agriculture": ["ICAR"],
    "general_university_degrees": ["CUET"],
}

# NSP's 31 real schemes (src/retrieve/nsp.py) are organized by beneficiary
# category (SC/ST/OBC/disability/merit/regional), not by field of study --
# matching a course name alone caps around 0.3-0.4 for almost all of them,
# and correctly stays unresolved (that's not a bug: a generic SC/ST scheme
# genuinely has no course-specific angle). The exception: 6 AICTE-branded
# schemes (Pragati/Saksham/Swanath) explicitly target "Technical Degree"/
# "Technical Diploma" students, and 4 ICAR schemes explicitly target
# agriculture. Confirmed live: "AICTE Technical" scores 100 against all 6
# with zero false positives across the other 25 (next closest: 32.9);
# "ICAR" scores 100 against all 4 (next closest: 15.1). Every other
# course area is deliberately left unmapped -- there is no other
# course-specific scheme in NSP's real index to route to.
_AREA_TO_SCHOLARSHIP_TERMS: dict[str, list[str]] = {
    "engineering_technology": ["AICTE Technical"],
    "agriculture": ["ICAR"],
}

# NIRF (src/retrieve/nirf.py) already has its own category-alias system
# (_CATEGORY_ALIASES) for exactly this reason -- one ranking table per
# broad discipline, not per specific course/specialisation -- but the
# alias vocabulary doesn't cover niche specialisation names, so a course
# like "Urban Design" never fuzzy-matches its way to the "Architecture"
# category on course name alone (confirmed live: 0.44 best, capped by
# noise). Diagnostic sampling (2026-08-09, 90 courses across all 30
# taxonomy fields) found this pattern at real scale: 152 below-threshold
# NIRF intents just in that sample, across 4 segments simultaneously
# (Institution & Offering, Ranking & Accreditation, Recruiters &
# Placement, Salary -- NIRF serves all four).
#
# Deliberately scoped to the 7 areas where a real, specific NIRF category
# exists AND already has a regulator_map area to key off of. NOT mapped:
# general_university_degrees -> NIRF's generic "University"/"Overall"
# category. That's a real ranking, but claiming it as "the Ranking
# evidence" for, say, a Sports Science or Aviation course (both fall back
# to this area) would be imprecise in exactly the way Hard Constraint 4
# warns against -- a generic overall-universities list isn't
# discipline-specific ranking evidence. Also not mapped: a "management"
# area, since none exists in _FIELD_TO_REGULATOR_AREAS yet even though
# NIRF has a real "Management" category -- a real follow-up opportunity,
# not silently added here without extending that table first.
_AREA_TO_NIRF_TERMS: dict[str, list[str]] = {
    "engineering_technology": ["Engineering"],
    "medicine": ["Medical"],
    "dentistry": ["Dental"],
    "pharmacy": ["Pharmacy"],
    "law": ["Law"],
    "architecture": ["Architecture"],
    "agriculture": ["Agriculture"],
}

# (segment, source_id) -> the area-vocabulary map that source's real index is
# organized by. Generalizes the NTA/CUET exam-vocabulary fix, the NSP
# scholarship-vocabulary fix, and the NIRF category-vocabulary fix into one
# mechanism rather than duplicating the lookup/union logic per source -- all
# three fix the same root problem (a source indexed by something other than
# course name) the same way.
_AREA_VOCABULARY_BY_SEGMENT_SOURCE: dict[tuple[Segment, str], dict[str, list[str]]] = {
    (Segment.ENTRANCE_ADMISSION, "NTA"): _AREA_TO_EXAM_TERMS,
    (Segment.ENTRANCE_ADMISSION, "CUET"): _AREA_TO_EXAM_TERMS,
    (Segment.SCHOLARSHIPS, "NSP"): _AREA_TO_SCHOLARSHIP_TERMS,
    (Segment.INSTITUTION_OFFERING, "NIRF"): _AREA_TO_NIRF_TERMS,
    (Segment.RANKING_ACCREDITATION, "NIRF"): _AREA_TO_NIRF_TERMS,
    (Segment.RECRUITERS_PLACEMENT, "NIRF"): _AREA_TO_NIRF_TERMS,
    (Segment.SALARY, "NIRF"): _AREA_TO_NIRF_TERMS,
}


def _area_vocabulary_terms(
    segment: Segment, source_id: str, course: Course, registry: SourceRegistry
) -> list[str]:
    area_terms = _AREA_VOCABULARY_BY_SEGMENT_SOURCE.get((segment, source_id))
    if area_terms is None:
        return []
    terms: list[str] = []
    for area in regulator_areas_for(course.fields):
        for term in area_terms.get(area, []):
            if term not in terms:
                terms.append(term)
    return terms


# NCS's 52 real sectors (src/retrieve/ncs.py) are labour-market sectors, not
# regulator areas -- Computing and Engineering share a regulator_map area
# (both "engineering_technology") but need different sectors entirely
# (IT-ITeS vs manufacturing-adjacent ones), so the area abstraction used
# above is too coarse here. Keyed on the raw taxonomy field instead.
#
# Deliberately scoped to fields with an unambiguous, near-exact sector name
# match -- confirmed live, all 12 distinct terms below score 1.00 against
# their intended sector with the next-closest candidate no higher than 0.77
# (Legal Activities vs Water Supply/Sewerage/Waste Management), safely below
# the 0.80 threshold. Fields left out deliberately, not by oversight: no
# single NCS sector cleanly represents them (Engineering spans several
# manufacturing-adjacent sectors depending on sub-discipline; Business/
# Management, Design, Performing Arts, and the remaining ~14 fields have no
# comparably clean match) -- forcing one would be the same imprecision Hard
# Constraint 4 warns against, not a fix.
_FIELD_TO_NCS_TERMS: dict[str, list[str]] = {
    "Computing, AI & Information Sys": ["IT-ITeS"],
    "Agriculture, Food & Natural Res": ["Agriculture"],
    "Medicine, Dentistry & Clinical ": ["Healthcare"],
    "Nursing, Pharmacy & Allied Heal": ["Healthcare"],
    "Public Health & Healthcare Mana": ["Healthcare"],
    "Law, Governance & Public Policy": ["Legal Activities"],
    "Education & Teaching": ["Education, Training and Research"],
    "Environment, Sustainability & C": ["Environmental Science"],
    "Sports, Physical Education & We": ["Sports, Physical Education, Fitness and Leisure"],
    "Hospitality, Tourism, Culinary ": ["Tourism and Hospitality"],
    "Communication, Journalism & Med": ["Media and Entertainment"],
    "Film, Animation, Gaming & Inter": ["Media and Entertainment"],
    "Architecture, Planning & Built": ["Construction"],
    "Accounting, Finance, Economics ": ["BFSI"],
    "Aviation, Maritime, Transport &": ["Aerospace and Aviation"],
}


def _ncs_terms_for(course: Course) -> list[str]:
    terms: list[str] = []
    for field in course.fields:
        for term in _FIELD_TO_NCS_TERMS.get(field, []):
            if term not in terms:
                terms.append(term)
    return terms


def regulator_areas_for(fields: list[str]) -> list[str]:
    areas: list[str] = []
    for field in fields:
        for area in _FIELD_TO_REGULATOR_AREAS.get(field, [_DEFAULT_REGULATOR_AREA]):
            if area not in areas:
                areas.append(area)
    if _DEFAULT_REGULATOR_AREA not in areas:
        areas.append(_DEFAULT_REGULATOR_AREA)
    return areas


def _regulator_sources(registry: SourceRegistry) -> set[str]:
    sources: set[str] = set()
    for area in registry.regulator_map.values():
        sources.add(area["primary"])
        sources.update(area.get("secondary") or [])
    return sources


def _permitted_regulators(registry: SourceRegistry, fields: list[str]) -> set[str]:
    permitted: set[str] = set()
    for area in regulator_areas_for(fields):
        mapping = registry.regulator_map.get(area)
        if mapping is None:
            continue
        permitted.add(mapping["primary"])
        permitted.update(mapping.get("secondary") or [])
    return permitted


def _document_types(source_id: str) -> list[DocumentType]:
    return [DocumentType.OFFICIAL_WEBPAGE, DocumentType.OFFICIAL_PDF]


def _role_for(registry: SourceRegistry, source_id: str, listed_as: str, floor: SourceTier) -> IntentRole:
    tiers = registry.tiers_for(source_id)
    if all(tier in _NON_CANONICAL for tier in tiers):
        return IntentRole.DISCOVERY
    if listed_as == "secondary":
        return IntentRole.SECONDARY
    # The segment's min_tier is an authority floor on the primary role: a source
    # the cookbook considers too weak to be canonical here may still corroborate.
    if min(tiers, key=lambda t: t.value).value > floor.value:
        return IntentRole.SECONDARY
    return IntentRole.PRIMARY


def _query_terms(course: Course) -> list[str]:
    terms = [course.standard_course_name]
    for alias in course.aliases[:MAX_ALIASES]:
        if alias not in terms:
            terms.append(alias)
    return terms


def plan_course(
    course: Course,
    registry: SourceRegistry,
    qualification_level: str = DEFAULT_QUALIFICATION_LEVEL,
    segments: Optional[list[Segment]] = None,
) -> list[RetrievalIntent]:
    # Explanatory segments (course overview, skills, further-study, reviews)
    # own no F-numbered fields, so there is nothing for a retrieval intent to
    # route to -- default to the retrieval-facing subset, not the full taxonomy.
    wanted = segments if segments is not None else list(RETRIEVAL_SEGMENTS)
    query_terms = _query_terms(course)
    regulators = _regulator_sources(registry)
    permitted = _permitted_regulators(registry, course.fields)

    intents: list[RetrievalIntent] = []
    for segment in wanted:
        config = registry.segment_sources.get(segment.value)
        if config is None:
            continue

        floor = SourceTier(config.get("min_tier", SourceTier.D.value))
        priority = 0
        for listed_as in ("preferred", "secondary"):
            for source_id in config.get(listed_as) or []:
                source = registry.sources.get(source_id)
                # Planning against a blocked or unverified source only
                # manufactures a failure the orchestrator has to absorb.
                if source is None or source.status not in USABLE_STATUSES:
                    continue
                # A regulator only serves the course areas the Regulator Map
                # assigns it. Non-regulator sources serve every area.
                if source_id in regulators and source_id not in permitted:
                    continue

                priority += 1
                # Union, not replace: extra vocabulary only ever adds
                # candidate terms, and fuzz.token_set_ratio's per-title
                # score is a max() over query_terms, so adding terms can
                # only raise or hold a candidate's score, never lower it.
                extra_terms = _area_vocabulary_terms(segment, source_id, course, registry)
                if segment == Segment.CAREER_MAPPING and source_id == "NCS":
                    extra_terms = extra_terms + _ncs_terms_for(course)
                terms = query_terms + [t for t in extra_terms if t not in query_terms]
                intents.append(
                    RetrievalIntent(
                        # Content-derived, not order-derived: RETRIEVAL_SEGMENTS
                        # is a frozenset whose iteration order is randomized
                        # per Python process (PYTHONHASHSEED), so a counter-based
                        # id let the same string mean a different (segment,
                        # source) pair on every re-run -- confirmed live to
                        # silently alias one run's resolved document onto an
                        # unrelated intent on the next run, via store.py's
                        # INSERT OR REPLACE keyed only on intent_id. Deriving the
                        # id from (course, segment, source) makes re-planning the
                        # same course idempotent by construction (Hard
                        # Constraint 5), not just internally consistent within
                        # one process.
                        intent_id=f"RI-{course.course_id}-{segment.value}-{source_id}",
                        course_id=course.course_id,
                        segment=segment,
                        field_ids=SEGMENT_FIELD_IDS[segment],
                        source_id=source_id,
                        priority=priority,
                        role=_role_for(registry, source_id, listed_as, floor),
                        query_terms=terms,
                        required_document_type=_document_types(source_id),
                        qualification_level=qualification_level,
                    )
                )
    return intents
