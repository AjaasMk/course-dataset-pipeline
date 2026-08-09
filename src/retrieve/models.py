from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SourceTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class Segment(str, Enum):
    """The client's Segment Sources sheet (S01-S19) is the canonical chunking
    taxonomy. It has 18 distinct values covering those 19 rows, not 19: S08
    (institutions offering the course) and S09 (ownership classification)
    both roll into the single INSTITUTION_OFFERING value, exactly as the
    client's own Data Fields sheet already merges them into one field group
    (F057-F071) -- verified against the workbook, not assumed.

    14 of these own F-numbered field ranges and are used for Stage 1
    retrieval intents (see RETRIEVAL_SEGMENTS below); the other 4 -- course
    overview, skills developed, further-study pathways, student reviews --
    have no atomic fields and exist only for Stage 2 chunking/routing.
    """

    COURSE_IDENTITY = "Course Identity"  # S01
    COURSE_OVERVIEW = "Course Overview"  # S02 -- explanatory, no F-fields
    DURATION_MODE = "Duration & Mode"  # S03
    ELIGIBILITY = "Eligibility"  # S04
    ENTRANCE_ADMISSION = "Entrance & Admission"  # S05
    CURRICULUM = "Curriculum"  # S06
    SPECIALISATION = "Specialisation"  # S07
    INSTITUTION_OFFERING = "Institution & Offering"  # S08 + S09 merged
    RANKING_ACCREDITATION = "Ranking & Accreditation"  # S10
    FEES = "Fees"  # S11
    SCHOLARSHIPS = "Scholarships"  # S12
    CAREER_MAPPING = "Career Mapping"  # S13
    SKILLS_DEVELOPED = "Skills Developed"  # S14 -- explanatory, no F-fields
    SALARY = "Salary"  # S15
    RECRUITERS_PLACEMENT = "Recruiters & Placement"  # S16
    INTERNSHIPS = "Internships"  # S17
    FURTHER_STUDY_PATHWAYS = "Further-Study Pathways"  # S18 -- explanatory, no F-fields
    STUDENT_REVIEWS = "Student Reviews & Campus Experience"  # S19 -- explanatory, no F-fields


# The 4 segments with no atomic Data Fields -- Stage 1 retrieval intents have
# nothing to route to for these, so they are excluded from planning entirely.
# Stage 2 chunking still classifies content into them for the Vector DB layer.
EXPLANATORY_SEGMENTS: frozenset[Segment] = frozenset(
    {Segment.COURSE_OVERVIEW, Segment.SKILLS_DEVELOPED, Segment.FURTHER_STUDY_PATHWAYS, Segment.STUDENT_REVIEWS}
)

# Derived, not hand-maintained: the 14-segment retrieval view is a computed
# subset of the one canonical 18-value taxonomy, so a future taxonomy change
# cannot let the two silently drift apart.
RETRIEVAL_SEGMENTS: frozenset[Segment] = frozenset(Segment) - EXPLANATORY_SEGMENTS


class IntentRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DISCOVERY = "discovery"


class MatchType(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    SEMANTIC = "semantic"
    FUZZY = "fuzzy"
    INSTITUTION_SPECIFIC = "institution_specific"


class DocumentType(str, Enum):
    OFFICIAL_WEBPAGE = "official webpage"
    OFFICIAL_PDF = "official PDF"
    DATASET = "dataset"
    LISTING_PAGE = "listing page"


class RetrievalStatus(str, Enum):
    AUTHORITATIVE_SOURCE_FOUND = "authoritative_source_found"
    SECONDARY_SOURCE_FOUND = "secondary_source_found"
    UNRESOLVED = "unresolved"


class RetrievalIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str
    course_id: str
    segment: Segment
    field_ids: list[str] = Field(min_length=1)
    source_id: str
    priority: int = Field(ge=1)
    role: IntentRole = IntentRole.PRIMARY
    query_terms: list[str] = Field(min_length=1)
    required_document_type: list[DocumentType] = Field(min_length=1)
    qualification_level: str


class DiscoveredDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_url: str
    document_title: str
    match_confidence: float = Field(ge=0.0, le=1.0)
    match_type: MatchType
    publication_date: Optional[str] = None
    academic_year: Optional[str] = None


class DocumentRecord(BaseModel):
    document_id: str
    source_id: str
    source_tier: SourceTier
    document_url: str
    document_title: str
    local_path: Optional[str] = None
    file_hash: Optional[str] = None
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    http_status: Optional[int] = None
    publication_date: Optional[str] = None
    academic_year: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    retrieved_at: str


class IntentResolution(BaseModel):
    intent_id: str
    document_id: str
    match_confidence: float = Field(ge=0.0, le=1.0)
    match_type: MatchType
    validated: bool = False
    validation_note: Optional[str] = None
