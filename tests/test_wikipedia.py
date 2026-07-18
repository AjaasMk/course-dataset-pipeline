import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.retrieve.base import SourceMatch
from src.retrieve.wikipedia import WikipediaAdapter
from src.schema import SourceType

HTML_BYTES = b"<html><body>Computer security article content</body></html>"


@pytest.fixture
def adapter():
    return WikipediaAdapter()


def _mock_search_response(pages):
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"pages": pages})
    return response


def _match(
    course_name="Cybersecurity",
    matched_name="Computer security",
    matched_url="https://en.wikipedia.org/wiki/Computer_security",
    confidence=1.0,
):
    return SourceMatch(course_name=course_name, matched_name=matched_name, matched_url=matched_url, confidence=confidence)


def _mock_download_response(content=HTML_BYTES, status_code=200, content_type="text/html; charset=utf-8"):
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


def test_build_index_returns_empty_dict(adapter):
    assert adapter.build_index() == {}


@patch("src.retrieve.wikipedia.requests.get")
def test_match_returns_none_when_no_pages_found(mock_get, adapter):
    mock_get.return_value = _mock_search_response([])

    result = adapter.match("Nonexistent Zzzqqq Course", {})

    assert result is None


@patch("src.retrieve.wikipedia.requests.get")
def test_match_picks_exact_title_match(mock_get, adapter):
    mock_get.return_value = _mock_search_response([
        {"key": "Marketing", "title": "Marketing", "excerpt": "Marketing is the act of acquiring customers"},
        {"key": "Digital_marketing", "title": "Digital marketing", "excerpt": "search engine marketing (SEM)"},
    ])

    result = adapter.match("Marketing", {})

    assert result.matched_name == "Marketing"
    assert result.matched_url == "https://en.wikipedia.org/wiki/Marketing"
    assert result.confidence == 1.0


@patch("src.retrieve.wikipedia.requests.get")
def test_match_falls_back_to_excerpt_score_when_title_score_is_low(mock_get, adapter):
    mock_get.return_value = _mock_search_response([
        {
            "key": "Computer_security",
            "title": "Computer security",
            "excerpt": 'Emerging field of computer security <span class="searchmatch">Cybersecurity</span> information technology',
        },
    ])

    result = adapter.match("Cybersecurity", {})

    assert result.matched_name == "Computer security"
    assert result.confidence == 1.0  # excerpt contains the exact query term; title alone scores ~0.73


@patch("src.retrieve.wikipedia.requests.get")
def test_match_prefers_better_scoring_candidate_over_first_result(mock_get, adapter):
    mock_get.return_value = _mock_search_response([
        {"key": "Unrelated_Page", "title": "Unrelated Page", "excerpt": "nothing relevant here at all"},
        {"key": "Software_engineering", "title": "Software engineering", "excerpt": "the application of engineering to software"},
    ])

    result = adapter.match("Software Engineering", {})

    assert result.matched_name == "Software engineering"


def test_match_calls_search_api_with_course_name_and_limit(adapter):
    with patch("src.retrieve.wikipedia.requests.get") as mock_get:
        mock_get.return_value = _mock_search_response([{"key": "X", "title": "X", "excerpt": ""}])
        adapter.match("Some Course", {})

    called_kwargs = mock_get.call_args.kwargs
    assert called_kwargs["params"]["q"] == "Some Course"
    assert called_kwargs["params"]["limit"] == 5


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.manifest.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.wikipedia.RAW_DIR", tmp_path / "raw")


@patch("src.retrieve.wikipedia.requests.get")
def test_download_writes_html_file_and_manifest_entry(mock_get, adapter):
    mock_get.return_value = _mock_download_response()
    match = _match()

    entry = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert entry.source_type == SourceType.GENERAL_BACKGROUND_WEBPAGE
    assert entry.http_status == 200
    assert entry.content_type == "text/html; charset=utf-8"
    assert entry.file_hash == hashlib.sha256(HTML_BYTES).hexdigest()
    assert Path(entry.local_path).read_bytes() == HTML_BYTES
    assert Path(entry.local_path).suffix == ".html"


@patch("src.retrieve.wikipedia.requests.get")
def test_second_download_for_same_course_and_url_skips_http_call(mock_get, adapter):
    mock_get.return_value = _mock_download_response()
    match = _match()

    first = adapter.download(match, tier="engineering")
    second = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert second == first


@patch("src.retrieve.wikipedia.requests.get")
def test_http_failure_propagates_and_writes_no_manifest_entry(mock_get, adapter):
    match = _match()
    response = _mock_download_response(status_code=404)
    response.raise_for_status.side_effect = Exception("404 Client Error")
    mock_get.return_value = response

    with pytest.raises(Exception, match="404 Client Error"):
        adapter.download(match, tier="engineering")

    from src.retrieve import manifest
    assert manifest.get_entry(match.course_name, match.matched_url) is None
