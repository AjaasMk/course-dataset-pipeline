from enum import Enum
from typing import Optional

from pydantic import BaseModel


class CitationRequired(Exception):
    """Raised when a fact is recorded without evidence.

    Hard Constraint 2: a field with content and no citation is invalid. Enforcing
    it at the store boundary means an uncited fact cannot reach the database at
    all, rather than being caught later by a validator that may not run.
    """


class VerificationStatus(str, Enum):
    PENDING = "pending"
    AI_CHECKED = "ai_checked"
    HUMAN_VERIFIED = "human_verified"
    REJECTED = "rejected"


# The client's Mandatory Human Review Matrix names the claim categories that may
# not auto-publish. A ranking claim is one of them, so AI-checked is not enough.
PUBLISHABLE_STATUSES = (VerificationStatus.HUMAN_VERIFIED,)


class SourceRef(BaseModel):
    """F143-F158. Binds one field of one fact record to the document that
    evidences it, with the quoted text that supports it."""

    field_id: str
    document_id: str
    quoted_evidence: str
    page_number: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.PENDING
    reviewed_by: Optional[str] = None


class Ranking(BaseModel):
    """F072-F079. One row per institution x ranking body x category x year --
    an institution ranked in several categories holds several rankings."""

    record_id: Optional[str] = None
    institution_id: str
    ranking_body: str
    ranking_year: str
    ranking_category: str
    rank: Optional[int] = None
    rank_band: Optional[str] = None
    ranking_score: Optional[float] = None
    naac_status: Optional[str] = None
    nba_programme_status: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None

    def identity(self) -> tuple[str, str, str, str]:
        return (self.institution_id, self.ranking_body, self.ranking_category, self.ranking_year)

    def values(self) -> tuple:
        return (self.rank, self.rank_band, self.ranking_score, self.naac_status, self.nba_programme_status)


class InstitutionOffering(BaseModel):
    """F057-F071. One row per institution x campus x course x academic year."""

    record_id: Optional[str] = None
    institution_id: str
    course_id: str
    official_institution_name: str
    previous_name: Optional[str] = None
    institution_type: Optional[str] = None
    ownership_type: Optional[str] = None
    affiliating_university: Optional[str] = None
    autonomous_status: Optional[str] = None
    ugc_status: Optional[str] = None
    aicte_status: Optional[str] = None
    professional_council_status: Optional[str] = None
    aishe_code: Optional[str] = None
    nirf_id: Optional[str] = None
    campus: Optional[str] = None
    intake: Optional[int] = None
    approval_academic_year: Optional[str] = None
    official_course_url: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None
