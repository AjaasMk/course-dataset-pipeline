import pytest

from src.facts import generated
from src.facts.generated import (
    HIGH_RISK_SEGMENTS,
    GeneratedContentInvalid,
    GenerationReason,
    GenerationRecord,
    Provenance,
    provenance_for,
    validate_generated,
)
from src.facts.models import SourceRef


def _record(**overrides):
    base = dict(
        course_id="mechanical_engineering",
        segment="Career Mapping",
        generator_model="claude-sonnet-5",
        sources_attempted=["NCS", "NQR"],
        fields={"career_titles": ["Design Engineer"]},
    )
    base.update(overrides)
    return GenerationRecord(**base)


def test_a_generated_record_defaults_to_unpublishable_and_needing_review():
    record = _record()

    assert record.provenance is Provenance.GENERATED
    assert record.review_required is True
    assert record.publishable is False
    assert record.citations == []


def test_a_generated_record_carrying_a_citation_is_rejected():
    # The single most important guard here. Generated content has no source to
    # cite; a citation on it means sourced and generated data have been mixed,
    # which is exactly how invented content acquires the standing of fact.
    record = _record(
        citations=[SourceRef(field_id="F102", document_id="DOC-1", quoted_evidence="x")]
    )

    with pytest.raises(GeneratedContentInvalid) as raised:
        validate_generated(record)

    assert "citation" in str(raised.value).lower()


def test_a_generated_record_cannot_claim_sourced_provenance():
    record = _record(provenance=Provenance.SOURCED)

    with pytest.raises(GeneratedContentInvalid):
        validate_generated(record)


@pytest.mark.parametrize("segment", sorted(HIGH_RISK_SEGMENTS))
def test_high_risk_generated_content_is_blocked_when_the_policy_is_off(segment, monkeypatch):
    # The client's Mandatory Human Review Matrix names these categories as
    # requiring quoted evidence and human sign-off. This asserts the guard
    # still works, so the current policy is a deliberate setting rather than
    # a capability that was quietly removed.
    monkeypatch.setattr(generated, "PUBLISH_GENERATED_HIGH_RISK", False)
    record = _record(segment=segment, publishable=True)

    with pytest.raises(GeneratedContentInvalid) as raised:
        validate_generated(record)

    assert segment in str(raised.value)


@pytest.mark.parametrize("segment", sorted(HIGH_RISK_SEGMENTS))
def test_high_risk_generated_content_publishes_when_the_policy_is_on(segment, monkeypatch):
    # The policy set on 2026-08-11. Publication is allowed; provenance,
    # review_required and the citation ban are all unaffected.
    monkeypatch.setattr(generated, "PUBLISH_GENERATED_HIGH_RISK", True)
    record = _record(segment=segment, publishable=True)

    validate_generated(record)

    assert record.provenance is Provenance.GENERATED
    assert record.review_required is True
    assert record.citations == []


def test_publishing_a_generated_record_never_makes_it_look_sourced(monkeypatch):
    # The property that must hold under either policy: allowing publication is
    # a delivery decision and must not touch how the record describes itself.
    monkeypatch.setattr(generated, "PUBLISH_GENERATED_HIGH_RISK", True)
    record = _record(segment="Fees", publishable=True)

    validate_generated(record)

    assert record.provenance is not Provenance.SOURCED
    assert record.reason is GenerationReason.NO_SOURCE_FOUND
    assert record.sources_attempted


def test_a_low_risk_generated_segment_may_be_marked_publishable(monkeypatch):
    monkeypatch.setattr(generated, "PUBLISH_GENERATED_HIGH_RISK", False)
    record = _record(segment="Course Overview", publishable=True)

    validate_generated(record)  # does not raise


def test_the_record_names_which_sources_were_actually_checked():
    # What makes a generated record auditable: it asserts the gap was real and
    # checked, not merely unexamined.
    record = _record(sources_attempted=["NCS", "NQR", "SKILL_INDIA_DIGITAL"])

    assert record.sources_attempted == ["NCS", "NQR", "SKILL_INDIA_DIGITAL"]
    assert record.reason is GenerationReason.NO_SOURCE_FOUND


def test_generated_record_is_not_substitutable_for_a_fact_model():
    # Deliberately not a subclass of the fact models: code expecting a cited
    # record must not silently accept a generated one.
    from src.facts.course_facts import Curriculum

    assert not issubclass(GenerationRecord, Curriculum)


@pytest.mark.parametrize(
    "populated,cited,expected",
    [
        (5, 5, Provenance.SOURCED),
        (5, 2, Provenance.PARTIAL),
        (5, 0, Provenance.GENERATED),
        (0, 0, Provenance.SOURCED),
    ],
)
def test_provenance_is_derived_from_how_many_fields_are_cited(populated, cited, expected):
    assert provenance_for(populated, cited) is expected


def test_generated_at_is_recorded():
    assert _record().generated_at
