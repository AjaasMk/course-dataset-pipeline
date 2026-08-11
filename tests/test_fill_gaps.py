import json

from src.extract.fill_gaps import fill_gaps
from src.facts.course_facts import CURRICULUM_FIELD_IDS, Curriculum
from src.facts.generated import GenerationReason, Provenance
from src.facts.models import SourceRef


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [_Block(text)]


class _Client:
    def __init__(self, payload):
        self._text = json.dumps(payload)
        self.messages = self
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.last = kwargs
        return _Response(self._text)


class _Course:
    course_id = "mechanical_engineering"
    name = "Mechanical Engineering"
    field = "Engineering & Applied Technology"
    level = "Undergraduate"


def _record(**overrides):
    base = dict(course_id="mechanical_engineering", curriculum_year="2025-26",
                core_subjects=["Thermodynamics"])
    base.update(overrides)
    return Curriculum(**base)


def _refs():
    return [SourceRef(field_id="F042", document_id="DOC-1", quoted_evidence="Thermodynamics")]


def test_a_complete_record_is_returned_untouched_without_an_api_call():
    listy = {"subjects", "foundation_subjects", "core_subjects", "electives"}
    record = _record(**{name: ([{"name": "x"}] if name == "subjects"
                               else ["x"] if name in listy else "x")
                        for name in CURRICULUM_FIELD_IDS})
    client = _Client({})

    result = fill_gaps(record, CURRICULUM_FIELD_IDS, _refs(), _Course(), "Curriculum", client=client)

    assert client.calls == 0
    assert result.provenance is Provenance.SOURCED
    assert result.generated_fields == set()


def test_missing_fields_are_generated_and_named():
    client = _Client({"electives": ["Robotics"], "project": "A final year project is typical."})

    result = fill_gaps(_record(), CURRICULUM_FIELD_IDS, _refs(), _Course(), "Curriculum",
                       client=client)

    assert result.record.electives == ["Robotics"]
    assert "electives" in result.generated_fields
    assert "project" in result.generated_fields
    assert result.record.core_subjects == ["Thermodynamics"]


def test_generated_fields_never_acquire_a_citation():
    # The guard that keeps provenance honest: refs come back exactly as
    # extraction produced them, so cited_fields can only count real evidence.
    refs = _refs()
    client = _Client({"electives": ["Robotics"], "dissertation": "Not usually required."})

    result = fill_gaps(_record(), CURRICULUM_FIELD_IDS, refs, _Course(), "Curriculum",
                       client=client)

    assert result.refs == refs
    assert len(result.refs) == 1


def test_a_mixed_record_reports_partial_provenance():
    client = _Client({"electives": ["Robotics"]})

    result = fill_gaps(_record(), CURRICULUM_FIELD_IDS, _refs(), _Course(), "Curriculum",
                       client=client)

    assert result.provenance is Provenance.PARTIAL
    assert result.reason is GenerationReason.SOURCE_SILENT


def test_documents_that_said_nothing_are_not_recorded_as_no_source_found():
    # Chunks existed and were silent. Calling that NO_SOURCE_FOUND would hide a
    # sourcing signal behind a retrieval one; they need different fixes.
    empty = Curriculum(course_id="mechanical_engineering", curriculum_year="2025-26")
    client = _Client({"core_subjects": ["Thermodynamics"], "electives": ["Robotics"]})

    result = fill_gaps(empty, CURRICULUM_FIELD_IDS, [], _Course(), "Curriculum", client=client)

    assert result.reason is GenerationReason.SOURCE_SILENT
    assert result.provenance is Provenance.GENERATED
    assert result.refs == []


def test_fields_the_model_declines_to_write_stay_empty_and_are_reported():
    client = _Client({"electives": ["Robotics"], "dissertation": None})

    result = fill_gaps(_record(), CURRICULUM_FIELD_IDS, _refs(), _Course(), "Curriculum",
                       client=client)

    assert "dissertation" not in result.generated_fields
    assert "dissertation" in result.empty_fields
    assert not result.is_complete


def test_the_prompt_shows_the_model_what_is_already_established():
    client = _Client({"electives": ["Robotics"]})

    fill_gaps(_record(), CURRICULUM_FIELD_IDS, _refs(), _Course(), "Curriculum", client=client)

    system = client.last["system"][0]["text"]
    assert "Thermodynamics" in system
    assert "core_subjects" not in json.loads(
        system.split("into this JSON schema:")[1].split("Rules:")[0].strip()
    )
