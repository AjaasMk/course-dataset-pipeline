from __future__ import annotations

from typing import Any

import httpx
import pytest

from coursegen.config import Settings
from coursegen.perplexity import PerplexityClient, ProviderOutputError


def agent_body(text: str, urls: list[str] | None = None) -> dict[str, Any]:
    output: list[dict[str, Any]] = [
        {"type": "message", "content": [{"type": "output_text", "text": text}]}
    ]
    if urls is not None:
        output.insert(
            0,
            {
                "type": "search_results",
                "queries": ["b tech fees"],
                "results": [{"url": u, "title": "t", "snippet": "s"} for u in urls],
            },
        )
    return {"status": "completed", "output": output, "usage": {"total_tokens": 42}}


def client_for(settings: Settings, handler) -> PerplexityClient:
    transport = httpx.MockTransport(handler)
    return PerplexityClient(settings, client=httpx.Client(transport=transport))


def test_payload_targets_the_agent_endpoint_with_preset(settings: Settings) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=agent_body('{"ok": true}', ["https://ugc.gov.in/a"]))

    with client_for(settings, handler) as client:
        result = client.complete_json(
            operation="crs_x:market",
            system_prompt="SYS",
            user_prompt="USER",
            json_schema={"type": "object"},
            search_domains=("ugc.gov.in", "nirfindia.org"),
        )

    assert seen["url"] == "https://api.perplexity.ai/v1/agent"
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"]
    assert body["preset"] == "fast"
    assert "model" not in body
    assert body["input"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert body["tools"] == [
        {
            "type": "web_search",
            "filters": {
                "search_domain_filter": ["ugc.gov.in", "nirfindia.org"],
                "search_recency_filter": "year",
            },
        }
    ]
    assert body["response_format"]["json_schema"]["name"] == "market"
    assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert result.data == {"ok": True}
    assert result.citations == ["https://ugc.gov.in/a"]
    assert result.usage == {"total_tokens": 42}


def test_explicit_model_replaces_preset(settings: Settings) -> None:
    import dataclasses

    scoped = dataclasses.replace(settings, perplexity_model="sonar-pro")
    payload = PerplexityClient(scoped).build_payload(
        system_prompt="s", user_prompt="u", json_schema={}, schema_name="market"
    )
    assert payload["model"] == "sonar-pro"
    assert "preset" not in payload


def test_no_domains_sends_no_domain_filter(settings: Settings) -> None:
    payload = PerplexityClient(settings).build_payload(
        system_prompt="s", user_prompt="u", json_schema={}, schema_name="x", search_domains=()
    )
    assert "search_domain_filter" not in payload["tools"][0].get("filters", {})


def test_citations_come_from_search_results_and_dedupe(settings: Settings) -> None:
    client = PerplexityClient(settings)
    parsed = client.parse(agent_body('{"a": 1}', ["https://x.gov.in/1", "https://x.gov.in/1"]))
    assert parsed.citations == ["https://x.gov.in/1"]
    assert len(parsed.search_results) == 2


def test_no_search_results_yields_no_citations(settings: Settings) -> None:
    parsed = PerplexityClient(settings).parse(agent_body('{"a": 1}'))
    assert parsed.citations == []


def test_fenced_json_is_unwrapped(settings: Settings) -> None:
    parsed = PerplexityClient(settings).parse(agent_body('```json\n{"a": 1}\n```'))
    assert parsed.data == {"a": 1}


@pytest.mark.parametrize(
    "body",
    [
        {"status": "completed", "output": []},
        {"status": "completed"},
        {"status": "completed", "output": [{"type": "message", "content": []}]},
    ],
)
def test_missing_output_raises(settings: Settings, body: dict[str, Any]) -> None:
    with pytest.raises(ProviderOutputError):
        PerplexityClient(settings).parse(body)


def test_incomplete_status_raises(settings: Settings) -> None:
    body = agent_body('{"a": 1')
    body["status"] = "incomplete"
    with pytest.raises(ProviderOutputError, match="incomplete"):
        PerplexityClient(settings).parse(body)


def test_non_json_text_raises(settings: Settings) -> None:
    with pytest.raises(ProviderOutputError, match="not valid JSON"):
        PerplexityClient(settings).parse(agent_body("here is your answer"))


def test_requests_are_throttled_to_the_configured_interval(settings: Settings) -> None:
    import dataclasses

    slept: list[float] = []
    now = {"t": 0.0}

    def sleep(seconds: float) -> None:
        slept.append(round(seconds, 3))
        now["t"] += seconds

    scoped = dataclasses.replace(settings, request_interval_seconds=2.0)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=agent_body('{"ok": true}'))
    )
    client = PerplexityClient(
        scoped, client=httpx.Client(transport=transport), sleep=sleep, clock=lambda: now["t"]
    )
    for _ in range(3):
        client.complete_json(
            operation="c:market", system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )
    assert slept == [2.0, 2.0]


def test_zero_interval_disables_throttling(settings: Settings) -> None:
    slept: list[float] = []
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=agent_body('{"ok": true}'))
    )
    client = PerplexityClient(
        settings, client=httpx.Client(transport=transport), sleep=lambda s: slept.append(s)
    )
    for _ in range(3):
        client.complete_json(
            operation="c:market", system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )
    assert slept == []
