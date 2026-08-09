from unittest.mock import Mock, patch

import pytest

from src.retrieve.collegedunia import CollegeDuniaAdapter
from src.retrieve.models import (
    DocumentType,
    IntentRole,
    RetrievalIntent,
    Segment,
    SourceTier,
)

PAGE_BYTES = b"<html><body>fees: INR 2 Lakh</body></html>"

# CollegeDunia's /courses page mixes a handful of real course-category
# listing pages (the ones this adapter should index) with primary-nav and
# footer links that share nothing but an href pattern -- confirmed live
# 2026-08-09: /bsc-colleges is real, /courses/b-sc and /write-review are not.
LISTING_HTML = """
<html><body>
  <a href="/bsc-colleges">B.Sc</a>
  <a href="/btech-colleges">B.Tech</a>
  <a href="/bsc-colleges">bsc</a>
  <a href="/write-review">Write a Review</a>
  <a href="/courses">Top Courses</a>
</body></html>
"""


@pytest.fixture
def adapter():
    return CollegeDuniaAdapter()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.collegedunia.RAW_DIR", tmp_path / "raw")


def _intent(**overrides) -> RetrievalIntent:
    fields = {
        "intent_id": "RI-010",
        "course_id": "bsc_physics",
        "segment": Segment.FEES,
        "field_ids": ["F080"],
        "source_id": "COLLEGEDUNIA",
        "priority": 3,
        "role": IntentRole.DISCOVERY,
        "query_terms": ["Physics (Core)", "B.Sc. in Physics"],
        "required_document_type": [DocumentType.OFFICIAL_WEBPAGE],
        "qualification_level": "Undergraduate",
    }
    fields.update(overrides)
    return RetrievalIntent(**fields)


def _listing_response():
    response = Mock()
    response.text = LISTING_HTML
    response.raise_for_status = Mock()
    return response


def _page_response():
    response = Mock()
    response.content = PAGE_BYTES
    response.status_code = 200
    response.headers = {"Content-Type": "text/html"}
    response.raise_for_status = Mock()
    return response


def test_adapter_is_declared_tier_d():
    assert CollegeDuniaAdapter.source_id == "COLLEGEDUNIA"
    assert CollegeDuniaAdapter.tiers == [SourceTier.D]


@patch("src.retrieve.collegedunia.requests.get")
def test_resolve_matches_course_name_against_category_pages(mock_get, adapter):
    mock_get.return_value = _listing_response()

    documents = adapter.resolve(_intent())

    assert documents
    assert documents[0].document_title == "B.Sc"
    assert documents[0].document_url.endswith("/bsc-colleges")


@patch("src.retrieve.collegedunia.requests.get")
def test_resolve_deduplicates_the_same_category_page_by_url(mock_get, adapter):
    mock_get.return_value = _listing_response()

    documents = adapter.resolve(_intent())

    urls = [d.document_url for d in documents]
    assert len(urls) == len(set(urls))


@patch("src.retrieve.collegedunia.requests.get")
def test_resolve_ignores_navigation_and_non_category_links(mock_get, adapter):
    mock_get.return_value = _listing_response()

    titles = {d.document_title for d in adapter.resolve(_intent())}

    assert "Write a Review" not in titles
    assert "Top Courses" not in titles


def test_intent_carries_no_document_url_before_resolve():
    intent = _intent()
    assert not hasattr(intent, "document_url")


@patch("src.retrieve.collegedunia.requests.get")
def test_download_records_the_document_at_tier_d(mock_get, adapter):
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]
    mock_get.return_value = _page_response()

    record = adapter.download(document)

    assert record.source_tier == SourceTier.D


@patch("src.retrieve.collegedunia.requests.get")
def test_download_uses_realistic_browser_headers_not_the_identifying_ua(mock_get, adapter):
    # The identifying UA (base.USER_AGENT) is edge-blocked outright by
    # CollegeDunia (confirmed live 2026-08-09) -- resolve() already needs
    # realistic headers to see real content; download() must use the same
    # headers for the actual fetch, or it 403s even after a successful
    # resolve(). This is exactly the gap that was missed on the first pass.
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]
    mock_get.return_value = _page_response()

    adapter.download(document)

    download_call_headers = mock_get.call_args.kwargs["headers"]
    assert download_call_headers["User-Agent"] != "course-dataset-pipeline/0.1 (educational course dataset project)"
    assert "Chrome" in download_call_headers["User-Agent"]


@patch("src.retrieve.collegedunia.requests.get")
def test_download_is_idempotent_on_document_url(mock_get, adapter):
    mock_get.return_value = _listing_response()
    document = adapter.resolve(_intent())[0]

    mock_get.return_value = _page_response()
    first = adapter.download(document)
    calls_after_first = mock_get.call_count

    second = adapter.download(document)

    assert mock_get.call_count == calls_after_first
    assert second.document_id == first.document_id
