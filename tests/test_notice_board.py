from unittest.mock import Mock, patch

import pytest

from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)
from src.retrieve.notice_board import NoticeBoardAdapter

NOTICE_HTML = """
<html><body>
  <a href="javascript:void(0);">Accessibility Tools</a>
  <a href="/files/202601031633478370.pdf">Information Bulletin</a>
  <a href="/files/20260623268704934.pdf">List of toppers of CUET (UG) - 2026</a>
  <a href="/files/202606231857909583.pdf">Final Answer Keys for CUET(UG) - 2026</a>
  <a href="/files/2026011697237004.pdf">FAQ</a>
  <a href="/files/seat-matrix-2026.pdf"></a>
  <a href="/about">About Us</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return NoticeBoardAdapter(
        source_id="CUET", tiers=[SourceTier.A], listing_page="https://cuet.nta.nic.in/"
    )


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.notice_board.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-090",
        "course_id": "bsc_psychology",
        "segment": Segment.ENTRANCE_ADMISSION,
        "field_ids": ["F031", "F040"],
        "source_id": "CUET",
        "priority": 1,
        "role": IntentRole.PRIMARY,
        "query_terms": ["information bulletin"],
        "required_document_type": [DocumentType.OFFICIAL_PDF],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _html_response(text=NOTICE_HTML):
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def test_adapter_reports_the_identity_it_was_configured_with(adapter):
    assert adapter.source_id == "CUET"
    assert adapter.tiers == [SourceTier.A]


def test_supports_only_its_own_source(adapter):
    assert adapter.supports(_intent())
    assert not adapter.supports(_intent(source_id="JOSAA"))


@patch("src.retrieve.notice_board.requests.get")
def test_index_keeps_only_document_links(mock_get, adapter):
    mock_get.return_value = _html_response()

    index = adapter.build_index()

    assert "Accessibility Tools" not in index
    assert "About Us" not in index
    assert "Information Bulletin" in index


@patch("src.retrieve.notice_board.requests.get")
def test_titles_come_from_anchor_text(mock_get, adapter):
    # These sites name uploads with an opaque timestamp (202601031633478370.pdf),
    # so unlike UGC the filename carries nothing and the anchor carries the label.
    mock_get.return_value = _html_response()

    assert any("toppers" in title for title in adapter.build_index())


@patch("src.retrieve.notice_board.requests.get")
def test_an_untitled_link_falls_back_to_its_filename(mock_get, adapter):
    mock_get.return_value = _html_response()

    assert "seat matrix 2026" in adapter.build_index()


@patch("src.retrieve.notice_board.requests.get")
def test_an_opaque_filename_with_no_anchor_text_is_dropped(mock_get, adapter):
    # A timestamp filename and no label leaves nothing to match on.
    mock_get.return_value = _html_response(
        '<html><body><a href="/files/202601031633478370.pdf"></a></body></html>'
    )

    assert adapter.build_index() == {}


@patch("src.retrieve.notice_board.requests.get")
def test_resolve_ranks_the_matching_notice_first(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent())[0]

    assert best.document_title == "Information Bulletin"


@patch("src.retrieve.notice_board.requests.get")
def test_an_unrelated_query_scores_below_threshold(mock_get, adapter):
    mock_get.return_value = _html_response()

    best = adapter.resolve(_intent(query_terms=["Bharatanatyam"]))[0]

    assert best.match_confidence < 0.80


@patch("src.retrieve.notice_board.requests.get")
def test_one_adapter_class_serves_several_sources(mock_get):
    mock_get.return_value = _html_response()
    josaa = NoticeBoardAdapter(
        source_id="JOSAA", tiers=[SourceTier.A], listing_page="https://josaa.nic.in/"
    )

    assert josaa.supports(_intent(source_id="JOSAA"))
    assert josaa.resolve(_intent(source_id="JOSAA"))[0].document_url.startswith("https://josaa.nic.in/")


def test_a_rendering_fetcher_can_be_supplied():
    # Sources whose documents only exist after JavaScript runs use the same
    # notice-board logic; only the fetch differs.
    rendered = '<html><body><a href="/f/bulletin.pdf">Assessment Guidelines</a></body></html>'
    adapter = NoticeBoardAdapter(
        source_id="NAAC",
        tiers=[SourceTier.A],
        listing_page="https://www.naac.gov.in/",
        fetch_html=lambda url: rendered,
    )

    assert "Assessment Guidelines" in adapter.build_index()


def test_a_supplied_fetcher_replaces_the_plain_request():
    calls = []

    def fetcher(url):
        calls.append(url)
        return '<html><body><a href="/f/x.pdf">Doc</a></body></html>'

    NoticeBoardAdapter(
        source_id="NAAC", tiers=[SourceTier.A],
        listing_page="https://www.naac.gov.in/", fetch_html=fetcher,
    ).build_index()

    assert calls == ["https://www.naac.gov.in/"]
