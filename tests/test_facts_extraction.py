import json
from unittest.mock import Mock

import pytest

from src.extract.facts_extraction import (
    extract_course,
    extract_curriculum,
    extract_eligibility,
    extract_specialisation,
)
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


def test_extract_curriculum_nulls_a_field_the_model_populated_without_a_citation():
    # The uncited field is dropped rather than raising. Both end states satisfy
    # Hard Constraint 2 -- nothing uncited survives -- but dropping keeps the
    # record's cited fields instead of losing the whole extraction to one bad
    # field, which is what happened on real data.
    from src.facts.course_facts import CURRICULUM_FIELD_IDS
    from src.facts.engine import check_citations

    payload = dict(VALID_PAYLOAD)
    payload["dissertation"] = "A dissertation is required in the final year"  # not in citations list
    chunks = [_chunk(0, "Curriculum content here.")]
    mock_client = _mock_client_returning(payload)

    curriculum, refs = extract_curriculum(chunks, _course(), "2024", client=mock_client)

    assert curriculum.dissertation is None
    assert curriculum.core_subjects  # the cited fields survive
    check_citations(curriculum, CURRICULUM_FIELD_IDS, refs)  # must not raise


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


ELIGIBILITY_PAYLOAD = {
    "minimum_qualification": "10+2 with Physics, Chemistry, Mathematics",
    "accepted_streams": ["Science"],
    "compulsory_subjects": ["Physics", "Chemistry", "Mathematics"],
    "recommended_subjects": [],
    "minimum_percentage": "75% aggregate",
    "age_requirement": None,
    "medical_requirement": None,
    "portfolio_required": None,
    "interview_required": None,
    "lateral_entry_available": True,
    "international_equivalence": None,
    "citations": [
        {"field": "minimum_qualification", "document_id": DOC_ID, "quoted_evidence": "10+2 with PCM"},
        {"field": "accepted_streams", "document_id": DOC_ID, "quoted_evidence": "Science stream"},
        {"field": "compulsory_subjects", "document_id": DOC_ID, "quoted_evidence": "Physics, Chemistry, Mathematics"},
        {"field": "minimum_percentage", "document_id": DOC_ID, "quoted_evidence": "75% aggregate marks"},
        {"field": "lateral_entry_available", "document_id": DOC_ID, "quoted_evidence": "lateral entry permitted"},
    ],
}


def test_extract_eligibility_only_uses_eligibility_segment_chunks():
    chunks = [
        _chunk(0, "Eligibility content here.", segment_id=Segment.ELIGIBILITY),
        _chunk(1, "Curriculum content here.", segment_id=Segment.CURRICULUM),
    ]
    mock_client = _mock_client_returning(ELIGIBILITY_PAYLOAD)

    extract_eligibility(chunks, _course(), "2026", client=mock_client)

    document_text = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Curriculum content here." not in document_text
    assert "Eligibility content here." in document_text


def test_extract_eligibility_returns_a_populated_model_and_matching_refs():
    chunks = [_chunk(0, "Eligibility content.", segment_id=Segment.ELIGIBILITY)]
    mock_client = _mock_client_returning(ELIGIBILITY_PAYLOAD)

    rule, refs = extract_eligibility(chunks, _course(), "2026", client=mock_client)

    assert rule.course_id == "mechanical_engineering"
    assert rule.eligibility_year == "2026"
    assert rule.minimum_qualification == "10+2 with Physics, Chemistry, Mathematics"
    assert rule.compulsory_subjects == ["Physics", "Chemistry", "Mathematics"]
    assert rule.lateral_entry_available is True
    assert rule.age_requirement is None

    from src.facts.course_facts import ELIGIBILITY_FIELD_IDS
    from src.facts.engine import check_citations

    check_citations(rule, ELIGIBILITY_FIELD_IDS, refs)  # must not raise


def test_extract_eligibility_returns_empty_model_when_no_eligibility_chunks_exist():
    chunks = [_chunk(0, "Curriculum only.", segment_id=Segment.CURRICULUM)]
    mock_client = _mock_client_returning(ELIGIBILITY_PAYLOAD)

    rule, refs = extract_eligibility(chunks, _course(), "2026", client=mock_client)

    assert refs == []
    assert rule.minimum_qualification is None
    mock_client.messages.create.assert_not_called()


COURSE_PAYLOAD = {
    "standard_course_name": "Mechanical Engineering",
    "common_course_name": None,
    "abbreviation": None,
    "qualification_level": None,
    "qualification_type": None,
    "academic_or_vocational": None,
    "regulating_body": "AICTE",
    "course_aliases": [],
    "minimum_duration": "4 years",
    "maximum_duration": None,
    "semester_count": 8,
    "credit_count": 160,
    "study_mode": "Full-time",
    "full_time_available": True,
    "part_time_available": False,
    "online_available": False,
    "distance_available": False,
    "exit_options": [],
    "citations": [
        {"field": "standard_course_name", "document_id": DOC_ID, "quoted_evidence": "Mechanical Engineering"},
        {"field": "regulating_body", "document_id": DOC_ID, "quoted_evidence": "AICTE approved"},
        {"field": "minimum_duration", "document_id": DOC_ID, "quoted_evidence": "4 year programme"},
        {"field": "semester_count", "document_id": DOC_ID, "quoted_evidence": "8 semesters"},
        {"field": "credit_count", "document_id": DOC_ID, "quoted_evidence": "160 credits"},
        {"field": "study_mode", "document_id": DOC_ID, "quoted_evidence": "full-time programme"},
        {"field": "full_time_available", "document_id": DOC_ID, "quoted_evidence": "offered full-time"},
        {"field": "part_time_available", "document_id": DOC_ID, "quoted_evidence": "no part-time option"},
        {"field": "online_available", "document_id": DOC_ID, "quoted_evidence": "not offered online"},
        {"field": "distance_available", "document_id": DOC_ID, "quoted_evidence": "not offered via distance mode"},
    ],
}


def test_extract_course_pulls_from_both_course_identity_and_duration_mode_segments():
    chunks = [
        _chunk(0, "Course identity content.", segment_id=Segment.COURSE_IDENTITY),
        _chunk(1, "Duration content.", segment_id=Segment.DURATION_MODE),
        _chunk(2, "Curriculum content.", segment_id=Segment.CURRICULUM),
    ]
    mock_client = _mock_client_returning(COURSE_PAYLOAD)

    extract_course(chunks, _course(), client=mock_client)

    document_text = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Course identity content." in document_text
    assert "Duration content." in document_text
    assert "Curriculum content." not in document_text


def test_extract_course_returns_a_populated_model_and_matching_refs():
    chunks = [_chunk(0, "Course content.", segment_id=Segment.COURSE_IDENTITY)]
    mock_client = _mock_client_returning(COURSE_PAYLOAD)

    course, refs = extract_course(chunks, _course(), client=mock_client)

    assert course.course_id == "mechanical_engineering"
    assert course.standard_course_name == "Mechanical Engineering"
    assert course.semester_count == 8
    assert course.full_time_available is True
    assert course.common_course_name is None  # not in the citations list -- correctly excluded

    from src.facts.course_facts import COURSE_FIELD_IDS
    from src.facts.engine import check_citations

    check_citations(course, COURSE_FIELD_IDS, refs)  # must not raise


def test_extract_course_returns_none_when_no_relevant_chunks_exist():
    chunks = [_chunk(0, "Eligibility only.", segment_id=Segment.ELIGIBILITY)]
    mock_client = _mock_client_returning(COURSE_PAYLOAD)

    course, refs = extract_course(chunks, _course(), client=mock_client)

    assert course is None
    assert refs == []
    mock_client.messages.create.assert_not_called()


SPECIALISATION_PAYLOAD = {
    "specialisations": [
        {
            "specialisation_name": "Thermal Engineering",
            "available_at_level": "Undergraduate",
            "parent_course": "Mechanical Engineering",
            "typical_subjects": ["Heat Transfer", "Refrigeration"],
            "career_focus": "Power plants and HVAC",
            "specialisation_type": "Elective track",
            "citations": [
                {"field": "available_at_level", "document_id": DOC_ID, "quoted_evidence": "offered at UG level"},
                {"field": "parent_course", "document_id": DOC_ID, "quoted_evidence": "under Mechanical Engineering"},
                {"field": "typical_subjects", "document_id": DOC_ID, "quoted_evidence": "Heat Transfer, Refrigeration"},
                {"field": "career_focus", "document_id": DOC_ID, "quoted_evidence": "careers in power plants and HVAC"},
                {"field": "specialisation_type", "document_id": DOC_ID, "quoted_evidence": "an elective track"},
            ],
        },
        {
            "specialisation_name": "Manufacturing Engineering",
            "available_at_level": "Undergraduate",
            "parent_course": "Mechanical Engineering",
            "typical_subjects": ["CAD/CAM", "Automation"],
            "career_focus": None,
            "specialisation_type": "Elective track",
            "citations": [
                {"field": "available_at_level", "document_id": DOC_ID, "quoted_evidence": "offered at UG level"},
                {"field": "parent_course", "document_id": DOC_ID, "quoted_evidence": "under Mechanical Engineering"},
                {"field": "typical_subjects", "document_id": DOC_ID, "quoted_evidence": "CAD/CAM, Automation"},
                {"field": "specialisation_type", "document_id": DOC_ID, "quoted_evidence": "an elective track"},
            ],
        },
    ]
}


def test_extract_specialisation_returns_one_entry_per_specialisation():
    chunks = [_chunk(0, "Specialisation content.", segment_id=Segment.SPECIALISATION)]
    mock_client = _mock_client_returning(SPECIALISATION_PAYLOAD)

    results = extract_specialisation(chunks, _course(), client=mock_client)

    assert len(results) == 2
    names = {spec.specialisation_name for spec, _ in results}
    assert names == {"Thermal Engineering", "Manufacturing Engineering"}


def test_extract_specialisation_each_entry_has_its_own_valid_citations():
    chunks = [_chunk(0, "Specialisation content.", segment_id=Segment.SPECIALISATION)]
    mock_client = _mock_client_returning(SPECIALISATION_PAYLOAD)

    from src.facts.course_facts import SPECIALISATION_FIELD_IDS
    from src.facts.engine import check_citations

    results = extract_specialisation(chunks, _course(), client=mock_client)
    for spec, refs in results:
        check_citations(spec, SPECIALISATION_FIELD_IDS, refs)  # must not raise for either entry


def test_extract_specialisation_returns_empty_list_when_no_relevant_chunks_exist():
    chunks = [_chunk(0, "Curriculum only.", segment_id=Segment.CURRICULUM)]
    mock_client = _mock_client_returning(SPECIALISATION_PAYLOAD)

    results = extract_specialisation(chunks, _course(), client=mock_client)

    assert results == []
    mock_client.messages.create.assert_not_called()


def test_uncited_populated_fields_are_nulled_not_kept():
    # Hard Constraint 4: a field the model could not quote evidence for is a
    # guess. Nulling it keeps the rest of the record -- the alternative,
    # measured live, lost two whole Course extractions and 8 cited fields
    # with them because one field arrived uncited.
    from src.extract.facts_extraction import _Citation, _drop_uncited

    values = {"common_course_name": "B.Tech", "abbreviation": "BT", "course_aliases": ["x"]}
    citations = [_Citation(field="abbreviation", document_id="DOC-1", quoted_evidence="BT")]
    field_ids = {"common_course_name": "F002", "abbreviation": "F003", "course_aliases": "F008"}

    cleaned = _drop_uncited(values, citations, field_ids)

    assert cleaned["abbreviation"] == "BT"
    assert cleaned["common_course_name"] is None
    assert cleaned["course_aliases"] == []


def test_drop_uncited_leaves_fields_outside_the_field_id_map_alone():
    from src.extract.facts_extraction import _drop_uncited

    values = {"course_id": "mechanical_engineering", "abbreviation": "BT"}
    cleaned = _drop_uncited(values, [], {"abbreviation": "F003"})

    assert cleaned["course_id"] == "mechanical_engineering"
    assert cleaned["abbreviation"] is None
