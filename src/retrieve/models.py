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
    COURSE_IDENTITY = "Course Identity"
    DURATION_MODE = "Duration & Mode"
    ELIGIBILITY = "Eligibility"
    ENTRANCE_ADMISSION = "Entrance & Admission"
    CURRICULUM = "Curriculum"
    SPECIALISATION = "Specialisation"
    INSTITUTION_OFFERING = "Institution & Offering"
    RANKING_ACCREDITATION = "Ranking & Accreditation"
    FEES = "Fees"
    SCHOLARSHIPS = "Scholarships"
    CAREER_MAPPING = "Career Mapping"
    SALARY = "Salary"
    RECRUITERS_PLACEMENT = "Recruiters & Placement"
    INTERNSHIPS = "Internships"


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
