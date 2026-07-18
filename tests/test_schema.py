from src.schema import ManifestEntry, SourceType


def test_manifest_entry_defaults_new_fields_to_none():
    entry = ManifestEntry(
        course_name="Mechanical Engineering",
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        match_confidence=0.92,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )
    assert entry.content_type is None
    assert entry.content_length is None
    assert entry.http_status is None


def test_source_type_has_aggregator_webpage_value():
    assert SourceType.AGGREGATOR_WEBPAGE.value == "aggregator_webpage"


def test_source_type_has_general_background_webpage_value():
    assert SourceType.GENERAL_BACKGROUND_WEBPAGE.value == "general_background_webpage"


def test_manifest_entry_accepts_source_type_enum():
    entry = ManifestEntry(
        course_name="Some Course",
        tier="engineering",
        source_type=SourceType.AGGREGATOR_WEBPAGE,
        match_confidence=0.5,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )
    assert entry.source_type == SourceType.AGGREGATOR_WEBPAGE
