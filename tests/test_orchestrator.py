import logging

from src.retrieve import orchestrator
from src.retrieve.base import SourceMatch
from src.schema import ManifestEntry, SourceCategory, SourceType


def test_load_config_returns_dict_from_real_file():
    config = orchestrator.load_config()

    assert "retrieval_order" in config
    assert config["matching"]["threshold"] == 0.80


def test_load_config_reads_given_path(tmp_path):
    config_path = tmp_path / "fake_sources.yaml"
    config_path.write_text("matching:\n  threshold: 0.5\n", encoding="utf-8")

    config = orchestrator.load_config(path=config_path)

    assert config == {"matching": {"threshold": 0.5}}


class _FakeAdapter:
    def __init__(self, index):
        self._index = index
        self.build_index_calls = 0

    def build_index(self):
        self.build_index_calls += 1
        return self._index

    def match(self, course_name, index):
        raise NotImplementedError

    def download(self, match, tier):
        raise NotImplementedError


def test_build_indices_calls_build_index_once_per_adapter():
    adapter_a = _FakeAdapter(index={"a": "url-a"})
    adapter_b = _FakeAdapter(index={"b": "url-b"})

    indices = orchestrator.build_indices([adapter_a, adapter_b])

    assert indices == {adapter_a: {"a": "url-a"}, adapter_b: {"b": "url-b"}}
    assert adapter_a.build_index_calls == 1
    assert adapter_b.build_index_calls == 1


class _ScriptedAdapter:
    def __init__(self, match_result=None, download_result=None):
        self._match_result = match_result
        self._download_result = download_result
        self.match_calls = []
        self.download_calls = []

    def build_index(self):
        return {}

    def match(self, course_name, index):
        self.match_calls.append(course_name)
        return self._match_result

    def download(self, match, tier):
        self.download_calls.append((match, tier))
        return self._download_result


def _manifest_entry():
    return ManifestEntry(
        course_name="Mechanical Engineering",
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        matched_url="https://example.com/m.pdf",
        match_confidence=0.95,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )


def _match(confidence):
    return SourceMatch(
        course_name="Mechanical Engineering",
        matched_name="Mechanical Engineering",
        matched_url="https://example.com/m.pdf",
        confidence=confidence,
    )


def test_first_source_wins_when_confidence_clears_threshold(caplog):
    winning_entry = _manifest_entry()
    first_adapter = _ScriptedAdapter(match_result=_match(0.95), download_result=winning_entry)
    second_adapter = _ScriptedAdapter(match_result=_match(0.99), download_result=_manifest_entry())

    retrieval_order = {
        "strong_tier": [
            "fact_supplement_independent_writing_required",
            "regulatory_primary",
        ]
    }
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": first_adapter},
        SourceCategory.REGULATORY_PRIMARY: {"engineering": second_adapter},
    }
    indices = {first_adapter: {}, second_adapter: {}}

    with caplog.at_level(logging.INFO):
        result = orchestrator.retrieve_course(
            course_name="Mechanical Engineering",
            category="engineering",
            tier_group="strong_tier",
            retrieval_order=retrieval_order,
            indices=indices,
            registry=registry,
            threshold=0.8,
        )

    assert result == winning_entry
    assert len(first_adapter.match_calls) == 1
    assert len(first_adapter.download_calls) == 1
    assert len(second_adapter.match_calls) == 0
    assert any("Matched" in record.message for record in caplog.records)


def test_falls_through_to_next_source_when_confidence_below_threshold(caplog):
    winning_entry = _manifest_entry()
    low_confidence_adapter = _ScriptedAdapter(match_result=_match(0.69))
    high_confidence_adapter = _ScriptedAdapter(match_result=_match(0.95), download_result=winning_entry)

    retrieval_order = {
        "strong_tier": [
            "fact_supplement_independent_writing_required",
            "regulatory_primary",
        ]
    }
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": low_confidence_adapter},
        SourceCategory.REGULATORY_PRIMARY: {"engineering": high_confidence_adapter},
    }
    indices = {low_confidence_adapter: {}, high_confidence_adapter: {}}

    with caplog.at_level(logging.INFO):
        result = orchestrator.retrieve_course(
            course_name="Aerospace Engineering",
            category="engineering",
            tier_group="strong_tier",
            retrieval_order=retrieval_order,
            indices=indices,
            registry=registry,
            threshold=0.8,
        )

    assert result == winning_entry
    assert len(low_confidence_adapter.download_calls) == 0
    assert len(high_confidence_adapter.match_calls) == 1
    assert any("falling through" in record.message for record in caplog.records)


def test_skips_entry_with_no_registered_adapter():
    fallback_entry = _manifest_entry()
    fallback_adapter = _ScriptedAdapter(match_result=_match(0.9), download_result=fallback_entry)

    # regulatory_primary has no entry in the registry at all — e.g. medicine, no NMC adapter built
    retrieval_order = {"strong_tier": ["regulatory_primary", "fact_supplement_independent_writing_required"]}
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": fallback_adapter},
    }
    indices = {fallback_adapter: {}}

    result = orchestrator.retrieve_course(
        course_name="Cardiology",
        category="medicine",
        tier_group="strong_tier",
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
    )

    assert result == fallback_entry


def test_returns_none_when_every_source_falls_through():
    weak_adapter = _ScriptedAdapter(match_result=_match(0.1))

    retrieval_order = {"strong_tier": ["fact_supplement_independent_writing_required"]}
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": weak_adapter},
    }
    indices = {weak_adapter: {}}

    result = orchestrator.retrieve_course(
        course_name="Nonexistent Course",
        category="engineering",
        tier_group="strong_tier",
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
    )

    assert result is None


def test_returns_none_when_match_is_none():
    # match() returns None only when its index is empty, per SourceAdapter's contract
    empty_index_adapter = _ScriptedAdapter(match_result=None)

    retrieval_order = {"strong_tier": ["fact_supplement_independent_writing_required"]}
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": empty_index_adapter},
    }
    indices = {empty_index_adapter: {}}

    result = orchestrator.retrieve_course(
        course_name="Any Course",
        category="engineering",
        tier_group="strong_tier",
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
    )

    assert result is None
