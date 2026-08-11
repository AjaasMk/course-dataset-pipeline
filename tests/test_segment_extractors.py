import json

import pytest

from src.extract.facts_extraction import _entry_model_for, extract_segment_facts
from src.extract.models import Chunk
from src.facts.engine import check_citations
from src.facts.segment_facts import SEGMENT_FACTS
from src.retrieve.models import Segment


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    stop_reason = "end_turn"
    usage = type("U", (), {"output_tokens": 100})()

    def __init__(self, text):
        self.content = [_Block(text)]


class _Client:
    def __init__(self, payload):
        self._text = json.dumps(payload)
        self.messages = self

    def create(self, **kwargs):
        self.last = kwargs
        return _Response(self._text)


class _Course:
    course_id = "mechanical_engineering"
    name = "Mechanical Engineering"
    field = "Engineering & Applied Technology"


def _chunk(segment):
    return Chunk(
        chunk_id=0,
        text="Evidence text for the segment.",
        source_document="DOC-1",
        source_url="DOC-1",
        token_count=5,
        segment_id=segment,
        segment_match_confidence=1.0,
    )


@pytest.mark.parametrize("segment", sorted(SEGMENT_FACTS))
def test_every_segment_has_a_generated_entry_model_matching_its_fact_model(segment):
    fact_model, field_ids = SEGMENT_FACTS[segment]
    entry = _entry_model_for(fact_model, "X")

    assert set(field_ids) <= set(entry.model_fields)
    assert "citations" in entry.model_fields
    for bookkeeping in ("record_id", "course_id", "recorded_at", "superseded_at"):
        assert bookkeeping not in entry.model_fields


@pytest.mark.parametrize("segment", sorted(SEGMENT_FACTS))
def test_a_cited_entry_extracts_and_passes_the_citation_gate(segment):
    fact_model, field_ids = SEGMENT_FACTS[segment]
    required = [n for n, i in fact_model.model_fields.items()
                if i.is_required() and n != "course_id"]
    def sample(name):
        annotation = str(fact_model.model_fields[name].annotation)
        if "list" in annotation:
            return ["Evidence"]
        if "int" in annotation:
            return 1
        if "bool" in annotation:
            return True
        return "Evidence"

    values = {name: sample(name) for name in required}
    first = sorted(field_ids)[0]
    values.setdefault(first, sample(first))
    payload = {"entries": [{
        **values,
        "citations": [{"field": name, "document_id": "DOC-1",
                       "quoted_evidence": "Evidence text"} for name in values],
    }]}

    results = extract_segment_facts(
        segment, [_chunk(Segment(segment))], _Course(), client=_Client(payload))

    assert len(results) == 1
    record, refs = results[0]
    assert record.course_id == "mechanical_engineering"
    check_citations(record, field_ids, refs)


def test_an_entry_missing_its_key_field_is_dropped_not_fatal():
    # One malformed entry must not cost the entries that were fine.
    payload = {"entries": [
        {"exam_name": None, "conducting_body": "NTA", "citations": []},
        {"exam_name": "JEE Main", "citations": [
            {"field": "exam_name", "document_id": "DOC-1", "quoted_evidence": "JEE Main"}]},
    ]}

    results = extract_segment_facts(
        "Entrance & Admission", [_chunk(Segment.ENTRANCE_ADMISSION)], _Course(),
        client=_Client(payload))

    assert len(results) == 1
    assert results[0][0].exam_name == "JEE Main"


def test_an_uncited_field_is_nulled_so_the_gate_still_passes():
    from src.facts.segment_facts import FEES_FIELD_IDS

    payload = {"entries": [{
        "fee_year": "2025-26",
        "tuition_fee": "Rs 45,000",
        "hostel_fee": "Rs 60,000",
        "citations": [{"field": "fee_year", "document_id": "DOC-1",
                       "quoted_evidence": "2025-26"},
                      {"field": "tuition_fee", "document_id": "DOC-1",
                       "quoted_evidence": "Rs 45,000"}],
    }]}

    results = extract_segment_facts(
        "Fees", [_chunk(Segment.FEES)], _Course(), client=_Client(payload))

    record, refs = results[0]
    assert record.tuition_fee == "Rs 45,000"
    assert record.hostel_fee is None
    check_citations(record, FEES_FIELD_IDS, refs)


def test_no_chunks_for_the_segment_returns_nothing_without_calling_the_model():
    results = extract_segment_facts(
        "Salary", [_chunk(Segment.CURRICULUM)], _Course(), client=_Client({}))

    assert results == []


def test_several_entries_all_survive():
    payload = {"entries": [
        {"recruiter_name": n, "citations": [
            {"field": "recruiter_name", "document_id": "DOC-1", "quoted_evidence": n}]}
        for n in ("Tata Motors", "L&T", "Mahindra")
    ]}

    results = extract_segment_facts(
        "Recruiters & Placement", [_chunk(Segment.RECRUITERS_PLACEMENT)], _Course(),
        client=_Client(payload))

    assert [r.recruiter_name for r, _ in results] == ["Tata Motors", "L&T", "Mahindra"]
