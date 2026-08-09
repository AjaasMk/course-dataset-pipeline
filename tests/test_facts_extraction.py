import json
from unittest.mock import Mock

import pytest

from src.extract.facts_extraction import extract_curriculum
from src.extract.models import Chunk
from src.facts.course_facts import Curriculum
from src.retrieve.base import document_id_for
from src.retrieve.models import Segment


def _chunk(chunk_id, text, segment_id=Segment.CURRICULUM, source_url="https://aicte.gov.in/mech.pdf"):
    return Chunk(
        chunk_id=chunk_id, text=text, source_document="mech.pdf", source_url=source_url,
        token_count=len(text.split()), segment_id=segment_id,
    )


def _text_block(text):
    block = Mock()
    block.type = "text"
    block.text = text
    return block


def _mock_client_returning(payload: dict, stop_reason="end_turn"):
    fake_response = Mock()
    fake_response.content = [_text_block(json.dumps(payload))]
    fake_response.stop_reason = stop_reason
    mock_client = Mock()
    mock_client.messages.create.return_value = fake_response
    return mock_client


def _course():
    m = Mock()
    m.course_id = "mechanical_engineering"
    return m


DOC_ID = document_id_for("https://aicte.gov.in/mech.pdf")

VALID_PAYLOAD = {
    "foundation_subjects": ["Mathematics", "Physics"],
    "core_subjects": ["Thermodynamics", "Fluid Mechanics"],
    "electives": [],
    "practical_components": "Workshop practice each semester",
    "laboratory_components": None,
    "internship": None,
    "fieldwork": None,
    "project": "Final year capstone project",
    "dissertation": None,
    "citations": [
        {"field": "foundation_subjects", "document_id": DOC_ID, "quoted_evidence": "Mathematics, Physics"},
        {"field": "core_subjects", "document_id": DOC_ID, "quoted_evidence": "Thermodynamics, Fluid Mechanics"},
        {"field": "practical_components", "document_id": DOC_ID, "quoted_evidence": "Workshop practice each semester"},
        {"field": "project", "document_id": DOC_ID, "quoted_evidence": "Final year capstone project"},
    ],
}


def test_extract_curriculum_only_uses_curriculum_segment_chunks():
    chunks = [
        _chunk(0, "Curriculum content here.", segment_id=Segment.CURRICULUM),
        _chunk(1, "Eligibility content here.", segment_id=Segment.ELIGIBILITY),
    ]
    mock_client = _mock_client_returning(VALID_PAYLOAD)

    extract_curriculum(chunks, _course(), "2024", client=mock_client)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    document_text = call_kwargs["messages"][0]["content"]
    assert "Eligibility content here." not in document_text
    assert "Curriculum content here." in document_text


def test_extract_curriculum_returns_a_populated_model_and_matching_refs():
    chunks = [_chunk(0, "Curriculum content here.")]
    mock_client = _mock_client_returning(VALID_PAYLOAD)

    curriculum, refs = extract_curriculum(chunks, _course(), "2024", client=mock_client)

    assert curriculum.course_id == "mechanical_engineering"
    assert curriculum.curriculum_year == "2024"
    assert curriculum.foundation_subjects == ["Mathematics", "Physics"]
    assert curriculum.project == "Final year capstone project"
    assert curriculum.dissertation is None

    ref_field_ids = {r.field_id for r in refs}
    assert "F041" in ref_field_ids  # foundation_subjects
    assert "F048" in ref_field_ids  # project
    assert all(r.document_id == DOC_ID for r in refs)


def test_extract_curriculum_populates_only_cited_fields_never_fabricates():
    # Every populated field in VALID_PAYLOAD has a matching citation --
    # record_curriculum()'s own check_citations() call is Hard Constraint 2's
    # real enforcement point, but this proves extract_curriculum() produces
    # output that would actually pass it, not just plausible-looking JSON.
    from src.facts.course_facts import CURRICULUM_FIELD_IDS
    from src.facts.engine import check_citations

    chunks = [_chunk(0, "Curriculum content here.")]
    mock_client = _mock_client_returning(VALID_PAYLOAD)

    curriculum, refs = extract_curriculum(chunks, _course(), "2024", client=mock_client)

    check_citations(curriculum, CURRICULUM_FIELD_IDS, refs)  # must not raise


def test_extract_curriculum_raises_if_the_model_populates_a_field_with_no_citation():
    from src.facts.course_facts import CURRICULUM_FIELD_IDS
    from src.facts.engine import check_citations
    from src.facts.models import CitationRequired

    payload = dict(VALID_PAYLOAD)
    payload["dissertation"] = "A dissertation is required in the final year"  # not in citations list
    chunks = [_chunk(0, "Curriculum content here.")]
    mock_client = _mock_client_returning(payload)

    curriculum, refs = extract_curriculum(chunks, _course(), "2024", client=mock_client)

    with pytest.raises(CitationRequired):
        check_citations(curriculum, CURRICULUM_FIELD_IDS, refs)


def test_extract_curriculum_returns_empty_model_when_no_curriculum_chunks_exist():
    chunks = [_chunk(0, "Eligibility content only.", segment_id=Segment.ELIGIBILITY)]
    mock_client = _mock_client_returning(VALID_PAYLOAD)

    curriculum, refs = extract_curriculum(chunks, _course(), "2024", client=mock_client)

    assert refs == []
    assert curriculum.foundation_subjects == []
    mock_client.messages.create.assert_not_called()  # no point spending a call on nothing


def test_extract_curriculum_ignores_a_citation_for_an_unknown_field():
    payload = dict(VALID_PAYLOAD)
    payload["citations"] = payload["citations"] + [
        {"field": "not_a_real_field", "document_id": DOC_ID, "quoted_evidence": "x"}
    ]
    chunks = [_chunk(0, "Curriculum content here.")]
    mock_client = _mock_client_returning(payload)

    _, refs = extract_curriculum(chunks, _course(), "2024", client=mock_client)

    assert "not_a_real_field" not in {r.field_id for r in refs}
