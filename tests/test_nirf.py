from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.nirf import NIRFAdapter

YEAR_INDEX_HTML = """
<html><body>
  <a href="/Rankings/2025/Ranking.html">2025</a>
  <a href="/Rankings/2024/Ranking.html">2024</a>
  <a href="/Rankings/2023/Ranking.html">2023</a>
</body></html>
"""

CATEGORY_INDEX_HTML = """
<html><body>
  <a href="OverallRanking.html"></a>
  <a href="UniversityRanking.html"></a>
  <a href="EngineeringRanking.html"></a>
  <a href="ManagementRanking.html"></a>
  <a href="MedicalRanking.html"></a>
  <a href="LawRanking.html"></a>
  <a href="ArchitectureRanking.html"></a>
</body></html>
"""


@pytest.fixture
def adapter():
    return NIRFAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.nirf.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-020",
        "course_id": "mechanical_engineering",
        "segment": Segment.RANKING_ACCREDITATION,
        "field_ids": ["F072", "F073", "F075"],
        "source_id": "NIRF",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["Mechanical Engineering"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_a():
    assert NIRFAdapter.source_id == "NIRF"
    assert NIRFAdapter.tiers == [SourceTier.A]


@patch("src.retrieve.nirf.requests.get")
def test_uses_the_most_recent_ranking_year(mock_get, adapter):
    mock_get.side_effect = [_html_response(YEAR_INDEX_HTML), _html_response(CATEGORY_INDEX_HTML)]

    documents = adapter.resolve(_intent())

    assert all("/2025/" in d.document_url for d in documents)


@patch("src.retrieve.nirf.requests.get")
def test_maps_an_engineering_course_to_the_engineering_category(mock_get, adapter):
    mock_get.side_effect = [_html_response(YEAR_INDEX_HTML), _html_response(CATEGORY_INDEX_HTML)]

    best = adapter.resolve(_intent())[0]

    assert best.document_url.endswith("EngineeringRanking.html")
    assert best.academic_year == "2025"


@patch("src.retrieve.nirf.requests.get")
def test_maps_a_law_course_to_the_law_category(mock_get, adapter):
    mock_get.side_effect = [_html_response(YEAR_INDEX_HTML), _html_response(CATEGORY_INDEX_HTML)]

    best = adapter.resolve(_intent(query_terms=["Criminal Law"]))[0]

    assert best.document_url.endswith("LawRanking.html")


@patch("src.retrieve.nirf.requests.get")
def test_category_titles_come_from_the_href_not_the_empty_link_text(mock_get, adapter):
    mock_get.side_effect = [_html_response(YEAR_INDEX_HTML), _html_response(CATEGORY_INDEX_HTML)]

    titles = {d.document_title for d in adapter.resolve(_intent())}

    assert "NIRF 2025 Engineering Ranking" in titles
