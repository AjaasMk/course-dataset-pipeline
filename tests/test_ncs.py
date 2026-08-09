from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.ncs import NCSAdapter, sector_from_href

SECTORS_HTML = """
<html><body>
  <a href="/content-repository/Pages/ViewNcos.aspx?FilterField1=Industry&FilterValue1=Agriculture"></a>
  <a href="/content-repository/Pages/ViewNcos.aspx?FilterField1=Industry&FilterValue1=Automotive"></a>
  <a href="/content-repository/Pages/ViewNcos.aspx?FilterField1=Industry&FilterValue1=Capital%20Goods%20and%20Manufacturing"></a>
  <a href="/content-repository/Pages/ViewNcos.aspx?FilterField1=Industry&FilterValue1=Healthcare"></a>
  <a href="/content-repository/Pages/ViewNcos.aspx?FilterField1=Industry&FilterValue1=IT-ITeS"></a>
  <a href="/content-repository/Pages/BrowseBySectors.aspx">Career Information</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return NCSAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.ncs.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-050",
        "course_id": "mechanical_engineering",
        "segment": Segment.CAREER_MAPPING,
        "field_ids": ["F102", "F108"],
        "source_id": "NCS",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["Capital Goods and Manufacturing", "Automotive"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text=SECTORS_HTML):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_a():
    assert NCSAdapter.source_id == "NCS"
    assert NCSAdapter.tiers == [SourceTier.A]


def test_sector_name_is_read_from_the_query_string():
    href = "/Pages/ViewNcos.aspx?FilterField1=Industry&FilterValue1=Capital%20Goods%20and%20Manufacturing"
    assert sector_from_href(href) == "Capital Goods and Manufacturing"


def test_non_sector_href_yields_no_sector():
    assert sector_from_href("/content-repository/Pages/BrowseBySectors.aspx") == ""


@patch("src.retrieve.ncs.requests.get")
def test_index_is_keyed_by_sector_name(mock_get, adapter):
    mock_get.return_value = _html_response()

    index = adapter.build_index()

    assert "Capital Goods and Manufacturing" in index
    assert "Career Information" not in index
    assert len(index) == 5


@patch("src.retrieve.ncs.requests.get")
def test_planner_supplied_sector_terms_resolve(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent())[0]

    assert best.document_title == "Capital Goods and Manufacturing"


@patch("src.retrieve.ncs.requests.get")
def test_a_raw_course_name_does_not_resolve_to_a_sector(mock_get, adapter):
    # NCS sectors share no vocabulary with course names -- "Mechanical
    # Engineering" is served by Automotive and Capital Goods, neither of which
    # it resembles. The planner must translate; the adapter must not guess.
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["Mechanical Engineering"]))[0]

    assert best.match_confidence < 0.80
