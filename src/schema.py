from typing import Optional

from pydantic import BaseModel


class CourseDetail(BaseModel):
    course_name: str
    category: str
    degrees_offered: list[str] = []
    colleges_available: Optional[int] = None  # from AISHE, NOT from curriculum docs
    description: Optional[str] = None
    eligibility: Optional[str] = None
    duration: Optional[str] = None
    career_scope: Optional[str] = None
    source_refs: list[str] = []


class ManifestEntry(BaseModel):
    course_name: str
    tier: str
    source_type: str  # regulator_pdf | regulator_webpage | university_webpage | none
    matched_url: Optional[str] = None
    local_path: Optional[str] = None
    file_hash: Optional[str] = None
    match_confidence: float = 0.0
    retrieved_at: str
