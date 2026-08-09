import pytest

from src.retrieve.models import DocumentType, IntentRole, RetrievalIntent, Segment, SourceTier
from src.retrieve.registry import SourceAuthorityError, load_registry


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-001",
        "course_id": "bsc_psychology",
        "segment": Segment.ELIGIBILITY,
        "field_ids": ["F019"],
        "source_id": "UGC",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["BSc Psychology", "eligibility"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def test_registry_loads_44_sources():
    assert len(load_registry().sources) == 44


def test_tier_counts_match_the_client_directory():
    registry = load_registry()
    counts = {
        tier: sum(1 for s in registry.sources.values() if tier in s.tiers)
        for tier in (SourceTier.A, SourceTier.B, SourceTier.C, SourceTier.D)
    }
    assert counts == {
        SourceTier.A: 35,
        SourceTier.B: 5,
        SourceTier.C: 1,
        SourceTier.D: 8,
    }


def test_tier_d_source_cannot_hold_a_primary_role():
    registry = load_registry()
    with pytest.raises(SourceAuthorityError):
        registry.validate_intent(_intent(source_id="CAREERS360", role=IntentRole.PRIMARY))


def test_tier_d_source_may_hold_a_discovery_role():
    registry = load_registry()
    registry.validate_intent(_intent(source_id="CAREERS360", role=IntentRole.DISCOVERY))


def test_unknown_source_id_is_rejected():
    registry = load_registry()
    with pytest.raises(SourceAuthorityError):
        registry.validate_intent(_intent(source_id="WIKIPEDIA"))


def test_threshold_falls_back_to_the_global_default():
    registry = load_registry()
    assert registry.threshold_for("AICTE") == registry.threshold


def test_a_source_may_override_the_global_threshold():
    registry = load_registry()
    assert registry.threshold_for("UGC") < registry.threshold


def test_unknown_source_threshold_is_rejected():
    with pytest.raises(SourceAuthorityError):
        load_registry().threshold_for("WIKIPEDIA")


def test_every_regulator_map_reference_is_a_real_source():
    registry = load_registry()
    assert registry.unknown_regulator_map_references() == []


def test_every_segment_source_reference_is_a_real_source():
    registry = load_registry()
    assert registry.unknown_segment_source_references() == []
