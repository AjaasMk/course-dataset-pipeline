from __future__ import annotations

import dataclasses
from typing import Any

from coursegen.chunks import CHUNKS, CHUNKS_BY_KEY
from coursegen.config import Settings
from coursegen.generate import _chunks_for_paths, generate_course, merge_usage
from coursegen.perplexity import ProviderOutputError
from coursegen.prompts import build_repair_prompt, build_user_prompt

from test_generate import COURSE_ID, COURSE_NAME, FakeClient, chunk_payload


def total_requests(result) -> int:
    return sum(o.usage.get("requests", 0) for o in result.chunk_outcomes)


def test_unparseable_response_still_counts_as_a_billed_request(
    settings: Settings, demo_document: dict
) -> None:
    made = {"n": 0, "bad": 0}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        made["n"] += 1
        if operation.endswith("guidance") and made["bad"] < 2:
            made["bad"] += 1
            raise ProviderOutputError("truncated JSON")
        return chunk_payload(demo_document, operation.split(":")[-1])

    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=FakeClient(responder),
        settings=settings,
    )
    assert made["n"] == 8
    assert total_requests(result) == made["n"]


def test_validation_retries_are_counted(settings: Settings, demo_document: dict) -> None:
    made = {"n": 0}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        made["n"] += 1
        payload = chunk_payload(demo_document, operation.split(":")[-1])
        if operation.endswith("market") and made["n"] <= 5:
            payload["colleges"]["items"][2]["score"] = 99.9
        return payload

    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=FakeClient(responder),
        settings=settings,
    )
    assert total_requests(result) == made["n"]


def test_document_repair_keeps_the_earlier_rounds_usage(
    settings: Settings, demo_document: dict
) -> None:
    made = {"n": 0}
    broken = {"active": True}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        made["n"] += 1
        payload = chunk_payload(demo_document, operation.split(":")[-1])
        if operation.endswith("market") and broken["active"]:
            broken["active"] = False
            payload["comparison"][0]["course_name"] = "BA Sociology"
        return payload

    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=FakeClient(responder),
        settings=settings,
    )
    assert result.status == "validated"
    assert made["n"] == 7
    assert total_requests(result) == 7


def test_merge_usage_sums_both_sides() -> None:
    assert merge_usage({"requests": 2, "total_tokens": 10}, {"requests": 1, "total_tokens": 5}) == {
        "requests": 3,
        "total_tokens": 15,
    }
    assert merge_usage({}, {"requests": 1}) == {"requests": 1}


def test_repair_order_follows_pipeline_order_not_set_order() -> None:
    paths = {"comparison[0].course_name", "careers", "hero.summary", "fees.rows[0].max"}
    for _ in range(20):
        assert [c.key for c in _chunks_for_paths(paths)] == ["profile", "outcomes", "market"]


def test_repair_order_is_a_subsequence_of_chunk_order() -> None:
    order = [c.key for c in CHUNKS]
    got = [c.key for c in _chunks_for_paths({"faqs", "hero.badge", "skills"})]
    assert got == [k for k in order if k in set(got)]


def test_schema_is_omitted_from_the_prompt_by_default() -> None:
    chunk = CHUNKS_BY_KEY["market"]
    schema = {"type": "object", "properties": {"unmistakable_marker": {"type": "string"}}}
    prompt = build_user_prompt(
        chunk, course_name="B.Tech CSE", region="India", currency="INR", schema=schema
    )
    assert "unmistakable_marker" not in prompt
    assert "fees, colleges, comparison" in prompt.replace(", ", ", ")

    with_schema = build_user_prompt(
        chunk,
        course_name="B.Tech CSE",
        region="India",
        currency="INR",
        schema=schema,
        include_schema=True,
    )
    assert "unmistakable_marker" in with_schema
    assert len(with_schema) > len(prompt)


def test_repair_prompt_honours_the_schema_switch() -> None:
    chunk = CHUNKS_BY_KEY["market"]
    schema = {"type": "object", "properties": {"unmistakable_marker": {"type": "string"}}}
    kwargs = dict(
        course_name="B.Tech CSE",
        region="India",
        currency="INR",
        schema=schema,
        previous_output={"a": 1},
        error_lines=["- fees: bad"],
    )
    assert "unmistakable_marker" not in build_repair_prompt(chunk, **kwargs)
    assert "unmistakable_marker" in build_repair_prompt(chunk, include_schema=True, **kwargs)


def test_settings_switch_reaches_the_prompt(settings: Settings, demo_document: dict) -> None:
    seen: list[str] = []

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        seen.append(user_prompt)
        return chunk_payload(demo_document, operation.split(":")[-1])

    generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=FakeClient(responder),
        settings=dataclasses.replace(settings, include_schema_in_prompt=True),
    )
    assert any("JSON Schema the response must satisfy" in p for p in seen)

    seen.clear()
    generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=FakeClient(responder),
        settings=settings,
    )
    assert not any("JSON Schema the response must satisfy" in p for p in seen)


def test_validate_all_exports_resolve() -> None:
    import coursegen.validate as v

    for name in v.__all__:
        assert hasattr(v, name), name
