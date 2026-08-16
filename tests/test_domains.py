from __future__ import annotations

import pytest

from coursegen.chunks import CHUNKS, MAX_SEARCH_DOMAINS_PER_REQUEST, normalize_domain, normalize_domains


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("nirfindia.org", "nirfindia.org"),
        ("NIRFIndia.org", "nirfindia.org"),
        ("  ugc.gov.in  ", "ugc.gov.in"),
        ("www.nirfindia.org", "nirfindia.org"),
        ("https://www.nirfindia.org", "nirfindia.org"),
        ("https://nirfindia.org/Rankings/2026/", "nirfindia.org"),
        ("http://ugc.gov.in/page?x=1", "ugc.gov.in"),
        ("nirfindia.org:8443", "nirfindia.org"),
        ("info.ugc.gov.in", "info.ugc.gov.in"),
        ("-quora.com", "-quora.com"),
        ("-https://www.quora.com/topic", "-quora.com"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_domain_accepts_pasted_urls(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


def test_normalize_domains_dedupes_and_drops_blanks() -> None:
    assert normalize_domains(
        ("https://www.ugc.gov.in/x", "ugc.gov.in", "", "  ", "nirfindia.org")
    ) == ("ugc.gov.in", "nirfindia.org")


def test_chunk_level_domains_stay_within_the_request_cap() -> None:
    for chunk in CHUNKS:
        assert len(chunk.domains) <= MAX_SEARCH_DOMAINS_PER_REQUEST
