from src.retrieve import manifest
from src.schema import ManifestEntry, SourceType


def _entry(course_name="Mechanical Engineering", matched_url="https://example.com/mech.pdf"):
    return ManifestEntry(
        course_name=course_name,
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        matched_url=matched_url,
        local_path="data/raw/engineering/regulator_pdf/mechanical_engineering.pdf",
        file_hash="abc123",
        match_confidence=0.92,
        retrieved_at="2026-07-17T12:00:00+00:00",
        content_type="application/pdf",
        content_length=1024,
        http_status=200,
    )


def test_get_entry_returns_none_when_missing(tmp_path):
    db_path = tmp_path / "manifest.db"
    result = manifest.get_entry(
        "Mechanical Engineering", "https://example.com/mech.pdf", db_path=db_path
    )
    assert result is None


def test_insert_then_get_round_trips_all_fields(tmp_path):
    db_path = tmp_path / "manifest.db"
    entry = _entry()

    manifest.insert_entry(entry, db_path=db_path)
    result = manifest.get_entry(entry.course_name, entry.matched_url, db_path=db_path)

    assert result == entry


def test_get_entry_keys_on_course_name_and_url(tmp_path):
    db_path = tmp_path / "manifest.db"
    manifest.insert_entry(_entry(), db_path=db_path)

    assert manifest.get_entry(
        "Mechanical Engineering", "https://example.com/other.pdf", db_path=db_path
    ) is None
    assert manifest.get_entry(
        "Civil Engineering", "https://example.com/mech.pdf", db_path=db_path
    ) is None


def test_get_entry_creates_db_file_if_missing(tmp_path):
    db_path = tmp_path / "nested" / "manifest.db"
    result = manifest.get_entry("X", "https://example.com/x.pdf", db_path=db_path)
    assert result is None
    assert db_path.exists()
