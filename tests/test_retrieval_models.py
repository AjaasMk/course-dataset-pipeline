import pytest
from pydantic import ValidationError

from src.retrieve.models import DocumentType, RetrievalIntent, Segment


def _intent(**overrides):
    fields = {
        "intent_id": "RI-001",
        "course_id": "bsc_psychology",
        "segment": Segment.ELIGIBILITY,
        "field_ids": ["F019", "F020"],
        "source_id": "UGC",
        "priority": 1,
        "query_terms": ["BSc Psychology", "eligibility"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def test_intent_rejects_a_document_url():
    with pytest.raises(ValidationError):
        _intent(document_url="https://www.ugc.gov.in/some-page")
