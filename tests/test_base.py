from pathlib import Path
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


@patch("src.retrieve.base.requests.get")
def test_fetch_and_store_defaults_to_plain_tls_verification(mock_get, tmp_path):
    mock_get.return_value = _page_response()

    fetch_and_store(_document(), source_id="X", source_tier=SourceTier.D, raw_dir=tmp_path, extension="html")

    assert mock_get.call_args.kwargs["verify"] is True


@patch("src.retrieve.base.requests.get")
def test_fetch_and_store_uses_a_caller_supplied_verify_bundle(mock_get, tmp_path):
    # Confirmed live 2026-08-09: CEE_KERALA's own listing-page fetch
    # (NoticeBoardAdapter._get_html) already repairs its incomplete TLS
    # chain via tls.verify_arg(), but download() -- this function -- never
    # did, so the homepage loaded fine while every real document download
    # from the same host failed with the exact same certificate error.
    mock_get.return_value = _page_response()

    fetch_and_store(
        _document(), source_id="X", source_tier=SourceTier.D, raw_dir=tmp_path,
        extension="html", verify="data/ca_bundles/cee.kerala.gov.in.pem",
    )

    assert mock_get.call_args.kwargs["verify"] == "data/ca_bundles/cee.kerala.gov.in.pem"


@patch("src.retrieve.base.requests.get")
def test_fetch_and_store_truncates_an_overlong_document_title_into_a_valid_filename(mock_get, tmp_path):
    # Confirmed live 2026-08-09: a real NAPS/NSP document title ~280 chars
    # long produced a local_path exceeding the filesystem's path-component
    # limit, crashing the download with [Errno 22] Invalid argument.
    mock_get.return_value = _page_response()
    overlong_title = "OM dated 23.04.2026 - " + ("Interim Extension of schemes " * 12)
    document = DiscoveredDocument(
        document_url="https://example.com/naps.pdf", document_title=overlong_title,
        match_confidence=0.9, match_type=MatchType.FUZZY,
    )

    record = fetch_and_store(document, source_id="X", source_tier=SourceTier.D, raw_dir=tmp_path, extension="pdf")

    filename = Path(record.local_path).name
    assert len(filename) <= 200  # real limit is 255; comfortable margin, not a tight bound
    # Still opens for real -- the whole point is a filesystem-writable path.
    assert Path(record.local_path).exists()
