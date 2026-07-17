from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SourceCategory(str, Enum):
    REGULATORY_PRIMARY = "regulatory_primary"
    SYLLABUS_SUPPLEMENT = "syllabus_supplement"
    FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED = (
        "fact_supplement_independent_writing_required"
    )
    GENERAL_BACKGROUND = "general_background"
    AGGREGATE_STATS_ONLY = "aggregate_stats_only"
    CAREER_INFO = "career_info"


class SourceType(str, Enum):
    REGULATOR_PDF = "regulator_pdf"
    REGULATOR_WEBPAGE = "regulator_webpage"
    UNIVERSITY_WEBPAGE = "university_webpage"
    AGGREGATOR_WEBPAGE = "aggregator_webpage"
    NONE = "none"


class SourceRef(BaseModel):
    field: str  # which CourseDetail field this grounds, e.g. "description"
    url: str
    category: SourceCategory
    # category == FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED means Stage 3
    # must run an n-gram/similarity check against this source's original text,
    # in addition to the faithfulness check — see CLAUDE.md Validation rules.


class CourseDetail(BaseModel):
    course_name: str
    category: str
    degrees_offered: list[str] = []
    colleges_available: Optional[int] = None  # from AISHE, NOT from curriculum docs
    description: Optional[str] = None
    eligibility: Optional[str] = None
    duration: Optional[str] = None
    career_scope: Optional[str] = None
    # one or more SourceRef per field — e.g. description may cite both an
    # AICTE doc and a Careers360 page. Filter by .field to get a field's refs.
    source_refs: list[SourceRef] = []


class ManifestEntry(BaseModel):
    course_name: str
    tier: str
    source_type: SourceType
    matched_url: Optional[str] = None
    local_path: Optional[str] = None
    file_hash: Optional[str] = None
    match_confidence: float = 0.0
    retrieved_at: str
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    http_status: Optional[int] = None
