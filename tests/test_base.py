from unittest.mock import Mock, patch

import pytest

from src.retrieve.base import USER_AGENT, fetch_and_store
from src.retrieve.models import DiscoveredDocument, MatchType, SourceTier

PAGE_BYTES = b"<html><body>page</body></html>"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.store.DEFAULT_DB_PATH", tmp_path / "manifest.db")


def _document():
    return DiscoveredDocument(
        document_url="https://example.com/page",
        document_title="Example Page",
        match_confidence=0.9,
        match_type=MatchType.FUZZY,
    )


def _page_response():
    response = Mock()
    response.content = PAGE_BYTES
    response.status_code = 200
    response.headers = {"Content-Type": "text/html"}
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.base.requests.get")
def test_fetch_and_store_defaults_to_the_identifying_user_agent(mock_get, tmp_path):
    mock_get.return_value = _page_response()

    fetch_and_store(_document(), source_id="X", source_tier=SourceTier.D, raw_dir=tmp_path, extension="html")

    call_headers = mock_get.call_args.kwargs["headers"]
    assert call_headers == {"User-Agent": USER_AGENT}


@patch("src.retrieve.base.requests.get")
def test_fetch_and_store_uses_caller_supplied_headers_when_given(mock_get, tmp_path):
    mock_get.return_value = _page_response()
    custom_headers = {"User-Agent": "some-browser-ua", "Referer": "https://example.com/"}

    fetch_and_store(
        _document(), source_id="X", source_tier=SourceTier.D, raw_dir=tmp_path,
        extension="html", headers=custom_headers,
    )

    call_headers = mock_get.call_args.kwargs["headers"]
    assert call_headers == custom_headers
