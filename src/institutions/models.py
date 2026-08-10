from typing import Optional

from pydantic import BaseModel


class Institution(BaseModel):
    institution_id: str
    canonical_name: str
    aishe_code: Optional[str] = None
    nirf_id: Optional[str] = None
    institution_type: Optional[str] = None
    ownership_type: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    nirf_rank: Optional[int] = None
    nirf_score: Optional[float] = None
    ranking_year: Optional[str] = None
    ranking_category: Optional[str] = None
    discovered_from_source_id: str
    official_url: Optional[str] = None


class InstitutionAlias(BaseModel):
    institution_id: str
    observed_name: str
    source_id: str
    confidence: float = 1.0


class InstitutionCourseOffering(BaseModel):
    institution_id: str
    course_id: str
    official_course_url: Optional[str] = None
    discovered_from_source_id: str
    confidence: float = 0.0


class RankedProfile(BaseModel):
    institution_id: str
    canonical_name: str
    nirf_id: str
    ranking_category: str
    ranking_year: str
