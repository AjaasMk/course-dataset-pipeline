from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.facts.models import SourceRef


class Provenance(str, Enum):
    """How a record's content came to exist.

    Recorded per record rather than per field so a reader can never be left
    guessing: SOURCED means every populated field carries a SourceRef,
    GENERATED means none do and none can, PARTIAL means the record mixes both
    and the field-level SourceRefs are the only way to tell which is which.
    """

    SOURCED = "sourced"
    PARTIAL = "partially_generated"
    GENERATED = "generated"


class GenerationReason(str, Enum):
    NO_SOURCE_FOUND = "no_source_found"
    SOURCE_SILENT = "source_found_but_silent_on_field"
    # The client's page renders blocks -- "Is this course suitable for you?",
    # "Parent corner", the FAQ -- that no regulator or university publishes and
    # never will. Distinguishing these from NO_SOURCE_FOUND matters: that one
    # names a retrieval gap worth chasing, this one names content that is
    # advisory by nature, so a coverage report does not read them as the same
    # failure. See docs/specs/page-block-map.json.
    NO_ATOMIC_SOURCE_EXISTS = "no_atomic_source_exists"


# Whether generated content may be published in the client's Mandatory Human
# Review categories.
#
# Set True on 2026-08-11 by explicit instruction, reversing the recorded
# client position (plan Decision 2, "no LLM fallback") and the cookbook's
# Tier F rule ("abstain and request better evidence"). It is a named setting
# rather than a deleted guard so the decision stays visible, auditable and
# revertible in one line if the client's answer changes.
#
# What it does NOT change: provenance is still recorded on every record,
# citations are still impossible on generated content, and generated figures
# must be written as indicative ranges rather than verified values -- which is
# the client's own demo template's pattern ("Indicative fees: Rs 20,000-Rs
# 3,00,000/year*" with a footnote), not a compromise invented here.
PUBLISH_GENERATED_HIGH_RISK = True

# The claim categories the client's Mandatory Human Review Matrix names as
# requiring quoted evidence and human sign-off before publication.
HIGH_RISK_SEGMENTS = frozenset(
    {
        "Eligibility",
        "Entrance & Admission",
        "Fees",
        "Scholarships",
        "Salary",
        "Recruiters & Placement",
        "Ranking & Accreditation",
        "Institution & Offering",
        "Duration & Mode",
    }
)


class GenerationRecord(BaseModel):
    """Content produced without a source, and the reason it was.

    Deliberately NOT a subclass of the fact models: a generated record must
    never be substitutable for a sourced one in code that expects citations.
    """

    course_id: str
    segment: str
    provenance: Provenance = Provenance.GENERATED
    reason: GenerationReason = GenerationReason.NO_SOURCE_FOUND
    generator_model: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Which sources were tried and produced nothing. This is what makes a
    # generated record auditable -- it says the gap was real, not unchecked.
    sources_attempted: list[str] = Field(default_factory=list)

    fields: dict[str, Any] = Field(default_factory=dict)

    # Always empty, and present so the shape matches a sourced record. A
    # generated field has nothing to cite by definition; a non-empty value here
    # would mean something has gone wrong upstream.
    citations: list[SourceRef] = Field(default_factory=list)

    # review_required stays True even when publication is allowed: publishing
    # ahead of review is a delivery decision, not a statement that the content
    # has been checked.
    review_required: bool = True
    publishable: bool = False
    reviewed_by: Optional[str] = None

    def is_high_risk(self) -> bool:
        return self.segment in HIGH_RISK_SEGMENTS


class GeneratedContentInvalid(Exception):
    """Raised when a generated record claims evidence it cannot have."""


def validate_generated(record: GenerationRecord) -> None:
    """Enforce the two properties that keep generation honest.

    Checked at construction rather than trusted, because the whole risk of a
    fallback is that generated content quietly acquires the standing of
    sourced content somewhere downstream.
    """
    if record.citations:
        raise GeneratedContentInvalid(
            f"{record.course_id}/{record.segment}: a generated record carries "
            f"{len(record.citations)} citation(s). Generated content has no source "
            f"to cite; a citation here means sourced and generated data have been mixed."
        )
    if record.provenance is Provenance.SOURCED:
        raise GeneratedContentInvalid(
            f"{record.course_id}/{record.segment}: provenance 'sourced' on a record "
            f"produced by generation."
        )
    if record.is_high_risk() and record.publishable and not PUBLISH_GENERATED_HIGH_RISK:
        raise GeneratedContentInvalid(
            f"{record.course_id}/{record.segment}: {record.segment} is one of the "
            f"client's Mandatory Human Review categories and cannot be marked "
            f"publishable while generated. Set PUBLISH_GENERATED_HIGH_RISK to "
            f"change this deliberately."
        )


def provenance_for(populated_fields: int, cited_fields: int) -> Provenance:
    if populated_fields == 0 or cited_fields == 0:
        return Provenance.GENERATED if populated_fields else Provenance.SOURCED
    if cited_fields >= populated_fields:
        return Provenance.SOURCED
    return Provenance.PARTIAL
