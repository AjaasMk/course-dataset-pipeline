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
    Segment.INTERNSHIPS: _range("F", 133, 142),
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
}
_DEFAULT_REGULATOR_AREA = "general_university_degrees"


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
    counter = 0
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

                counter += 1
                priority += 1
                intents.append(
                    RetrievalIntent(
                        intent_id=f"RI-{course.course_id}-{counter:03d}",
                        course_id=course.course_id,
                        segment=segment,
                        field_ids=SEGMENT_FIELD_IDS[segment],
                        source_id=source_id,
                        priority=priority,
                        role=_role_for(registry, source_id, listed_as, floor),
                        query_terms=query_terms,
                        required_document_type=_document_types(source_id),
                        qualification_level=qualification_level,
                    )
                )
    return intents
