from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
    GENERAL_BACKGROUND_WEBPAGE = "general_background_webpage"
    NONE = "none"


class Eligibility(BaseModel):
    ug: Optional[str] = Field(default=None, description="UG eligibility criteria, 30-60 words")
    pg: Optional[str] = Field(default=None, description="PG eligibility criteria, 30-60 words")


class EntranceExams(BaseModel):
    ug: list[str] = []
    pg: list[str] = []


class FeeRange(BaseModel):
    min_private: Optional[int] = None
    max_private: Optional[int] = None
    min_government: Optional[int] = None
    max_government: Optional[int] = None


class Fees(BaseModel):
    currency: str = "INR"
    ug: Optional[FeeRange] = None
    pg: Optional[FeeRange] = None
    doctoral: Optional[FeeRange] = None
    diploma: Optional[FeeRange] = None


class CollegesAvailable(BaseModel):
    private_count: Optional[int] = None
    government_count: Optional[int] = None


class JobProfile(BaseModel):
    title: str
    description: Optional[str] = Field(default=None, description="15-30 word summary of this role")
    avg_salary_lpa: Optional[float] = None


class SyllabusSemester(BaseModel):
    semester: int
    subjects: list[str] = []


class Syllabus(BaseModel):
    ug_semesters: list[SyllabusSemester] = []
    pg_semesters: list[SyllabusSemester] = []
    note: Optional[str] = Field(
        default=None,
        description="10-25 words, e.g. which institution's curriculum this example is drawn from",
    )


class TopCollege(BaseModel):
    name: str
    type: str  # "private" | "government"
    nirf_rank: Optional[int] = None
    fees: Optional[int] = None


class FAQ(BaseModel):
    question: str = Field(description="Single question, phrased as a student would search")
    answer: str = Field(description="30-60 word answer")


class CourseDetail(BaseModel):
    course_name: str
    category: str
    degrees_offered: list[str] = []
    duration: Optional[str] = Field(
        default=None, description="Short phrase, e.g. 'B.Tech: 4 years, M.Tech: 2 years'"
    )
    description: Optional[str] = Field(default=None, description="80-120 word course overview")
    admission_process: Optional[str] = Field(default=None, description="Short phrase, 5-15 words")
    eligibility: Optional[Eligibility] = None
    entrance_exams: Optional[EntranceExams] = None
    fees: Optional[Fees] = None
    colleges_available: Optional[CollegesAvailable] = None
    core_subjects: list[str] = []
    specializations: list[str] = []
    career_scope: Optional[str] = Field(
        default=None, description="100-150 word career/industry outlook"
    )
    average_salary_lpa: Optional[float] = None
    job_profiles: list[JobProfile] = []
    top_recruiters: list[str] = []
    required_skills: list[str] = []
    upcoming_trends: list[str] = []
    syllabus: Optional[Syllabus] = None
    top_colleges: list[TopCollege] = []
    related_courses: list[str] = []
    faqs: list[FAQ] = []


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
