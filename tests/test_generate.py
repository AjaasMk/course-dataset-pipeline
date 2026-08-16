from __future__ import annotations

import copy
from typing import Any, Callable

import pytest

from coursegen.chunks import CHUNKS, CHUNKS_BY_KEY
from coursegen.config import Settings
from coursegen.generate import apply_derived_fields, generate_chunk, generate_course, slugify
from coursegen.perplexity import ChunkResponse, ProviderOutputError
from coursegen.retry import TransportError
from coursegen.schema_tools import load_root_schema
from coursegen.store import ArtifactStore

COURSE_ID = "crs_bsc_psychology"
COURSE_NAME = "BSc Psychology"
COURSE_CATEGORY = "Health & Behavioural Sciences"


def chunk_payload(document: dict[str, Any], chunk_key: str) -> dict[str, Any]:
    chunk = CHUNKS_BY_KEY[chunk_key]
    payload = {key: copy.deepcopy(document[key]) for key in chunk.properties}
    for derived in chunk.derived_paths:
        node = payload
        parts = derived.split(".")
        for part in parts[:-1]:
            node = node[part]
        node.pop(parts[-1], None)
    return payload


class FakeClient:
    def __init__(self, responder: Callable[[str, str], dict[str, Any]]) -> None:
        self.responder = responder
        self.calls: list[dict[str, str]] = []

    def complete_json(
        self,
        *,
        operation: str,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        search_domains: tuple[str, ...] | None = None,
    ) -> ChunkResponse:
        self.calls.append({"operation": operation, "user_prompt": user_prompt})
        data = self.responder(operation, user_prompt)
        return ChunkResponse(data=data, citations=["https://ugc.gov.in/x"], usage={"total_tokens": 10})


def all_good_responder(document: dict[str, Any]) -> Callable[[str, str], dict[str, Any]]:
    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        return chunk_payload(document, operation.split(":")[-1])

    return responder


def test_slugify() -> None:
    assert slugify("BSc Psychology") == "bsc-psychology"
    assert slugify("B.Tech  Computer Science & Engineering") == "b-tech-computer-science-engineering"


def test_derived_marker_is_computed_not_trusted() -> None:
    document = {"snapshot": {"salary": {"lower_annual": 250000, "typical_annual": 420000, "higher_annual": 800000, "marker_percent": 99}}}
    assert apply_derived_fields(document)["snapshot"]["salary"]["marker_percent"] == 31


def test_happy_path_produces_validated_course(settings: Settings, demo_document: dict) -> None:
    client = FakeClient(all_good_responder(demo_document))
    store = ArtifactStore(settings.artifacts_dir, COURSE_ID)

    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings, store=store
    )

    assert result.status == "validated", result.validation
    assert result.publishable
    assert len(client.calls) == len(CHUNKS)
    assert all(o.accepted and o.attempts == 1 for o in result.chunk_outcomes)
    assert store.course_path.exists()
    assert store.validation_path.exists()
    assert store.load_course()["course_name"] == COURSE_NAME


def test_chunk_retries_then_succeeds(settings: Settings, demo_document: dict) -> None:
    attempts = {"n": 0}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        key = operation.split(":")[-1]
        payload = chunk_payload(demo_document, key)
        if key == "market":
            attempts["n"] += 1
            if attempts["n"] < 3:
                payload["colleges"]["items"][2]["rank"] = 6
        return payload

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings
    )

    market = next(o for o in result.chunk_outcomes if o.chunk_key == "market")
    assert market.accepted
    assert market.attempts == 3
    assert result.status == "validated"


def test_repair_prompt_carries_the_validation_errors(settings: Settings, demo_document: dict) -> None:
    calls: list[str] = []

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        calls.append(user_prompt)
        payload = chunk_payload(demo_document, "market")
        if len(calls) == 1:
            payload["colleges"]["items"][2]["rank"] = 6
        return payload

    client = FakeClient(responder)
    root_schema = load_root_schema(settings.schema_path)
    outcome = generate_chunk(
        CHUNKS_BY_KEY["market"],
        client=client,
        settings=settings,
        root_schema=root_schema,
        base_fields={
            "course_id": COURSE_ID,
            "slug": "bsc-psychology",
            "course_name": COURSE_NAME,
            "category": COURSE_CATEGORY,
            "currency": "INR",
            "region": "India",
        },
        context={},
    )

    assert outcome.accepted
    assert outcome.attempts == 2
    assert "rejected by automated validation" in calls[1]
    assert "college_ranks_not_sequential" not in calls[1]
    assert "colleges.items" in calls[1]


def test_chunk_flagged_after_exhausting_attempts(settings: Settings, demo_document: dict) -> None:
    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        key = operation.split(":")[-1]
        payload = chunk_payload(demo_document, key)
        if key == "outcomes":
            payload["careers"][1]["title"] = payload["careers"][0]["title"]
        return payload

    client = FakeClient(responder)
    store = ArtifactStore(settings.artifacts_dir, COURSE_ID)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings, store=store
    )

    flagged = next(o for o in result.chunk_outcomes if o.chunk_key == "outcomes")
    assert flagged.status == "flagged"
    assert flagged.attempts == settings.generation_max_attempts
    assert result.status == "flagged"
    assert not result.publishable
    assert "duplicate_career" in {
        finding["code"] for report in flagged.reports for finding in report["findings"]
    }


def test_transport_failure_flags_without_burning_attempts(settings: Settings, demo_document: dict) -> None:
    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        if operation.endswith("academics"):
            raise TransportError("HTTP 401", status_code=401, retryable=False)
        return chunk_payload(demo_document, operation.split(":")[-1])

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings
    )

    academics = next(o for o in result.chunk_outcomes if o.chunk_key == "academics")
    assert academics.status == "flagged"
    assert academics.attempts == 1
    assert "HTTP 401" in (academics.transport_error or "")
    assert result.status == "flagged"


def test_unparseable_output_counts_as_a_failed_attempt(settings: Settings, demo_document: dict) -> None:
    calls = {"n": 0}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        key = operation.split(":")[-1]
        if key == "guidance":
            calls["n"] += 1
            if calls["n"] == 1:
                raise ProviderOutputError("provider content was not valid JSON")
        return chunk_payload(demo_document, key)

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings
    )

    guidance = next(o for o in result.chunk_outcomes if o.chunk_key == "guidance")
    assert guidance.accepted
    assert guidance.attempts == 2
    assert guidance.reports[0]["findings"][0]["code"] == "provider_output"


def test_only_chunks_reuses_saved_artifacts(settings: Settings, demo_document: dict) -> None:
    store = ArtifactStore(settings.artifacts_dir, COURSE_ID)
    for chunk in CHUNKS:
        store.save_chunk(chunk.key, chunk_payload(demo_document, chunk.key))

    client = FakeClient(all_good_responder(demo_document))
    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        category=COURSE_CATEGORY,
        client=client,
        settings=settings,
        store=store,
        only_chunks=("market",),
    )

    assert [c["operation"] for c in client.calls] == [f"{COURSE_ID}:market"]
    assert result.status == "validated"


def test_cross_chunk_failure_retries_only_the_owning_chunk(settings: Settings, demo_document: dict) -> None:
    seen: list[str] = []
    broken = {"active": True}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        key = operation.split(":")[-1]
        seen.append(key)
        payload = chunk_payload(demo_document, key)
        if key == "market" and broken["active"]:
            broken["active"] = False
            payload["comparison"][0]["course_name"] = "BA Sociology"
        return payload

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings
    )

    assert result.status == "validated"
    assert seen.count("market") == 2
    assert seen.count("profile") == 1
    assert seen.count("guidance") == 1


def test_repair_seed_drops_derived_fields(demo_document: dict) -> None:
    from coursegen.generate import strip_derived_fields

    snapshot = CHUNKS_BY_KEY["snapshot"]
    seeded = strip_derived_fields(snapshot, {"snapshot": copy.deepcopy(demo_document["snapshot"])})
    assert "marker_percent" not in seeded["snapshot"]["salary"]
    assert demo_document["snapshot"]["salary"]["marker_percent"] == 31


def test_cross_chunk_repair_of_a_chunk_with_derived_fields(settings: Settings, demo_document: dict) -> None:
    broken = {"active": True}
    seen: list[str] = []

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        key = operation.split(":")[-1]
        seen.append(key)
        payload = chunk_payload(demo_document, key)
        if key == "snapshot" and broken["active"]:
            broken["active"] = False
            payload["overview"]["heading"] = "What is this course about?"
        else:
            assert "marker_percent" not in user_prompt
        return payload

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings
    )

    assert result.status == "validated"
    assert seen.count("snapshot") == 2
    assert result.document["snapshot"]["salary"]["marker_percent"] == 31


def test_curriculum_duration_mismatch_is_caught_inside_the_chunk_loop(
    settings: Settings, demo_document: dict
) -> None:
    seen: list[str] = []

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        key = operation.split(":")[-1]
        seen.append(key)
        payload = chunk_payload(demo_document, key)
        if key == "profile":
            payload["quick_facts"]["typical_duration"] = {"min_years": 3, "max_years": 3}
        if key == "academics" and seen.count("academics") > 1:
            payload["curriculum"]["years"] = payload["curriculum"]["years"][:3]
        return payload

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID, course_name=COURSE_NAME, category=COURSE_CATEGORY, client=client, settings=settings
    )

    academics = next(o for o in result.chunk_outcomes if o.chunk_key == "academics")
    assert academics.accepted
    assert academics.attempts == 2
    assert seen.count("profile") == 1
    assert result.status == "validated"
    assert len(result.document["curriculum"]["years"]) == 3
    assert "curriculum_length_mismatch" in {
        finding["code"] for report in academics.reports for finding in report["findings"]
    }


def test_chunk_payloads_never_include_injected_fields(demo_document: dict) -> None:
    for chunk in CHUNKS:
        payload = chunk_payload(demo_document, chunk.key)
        assert "course_id" not in payload
        assert "course_name" not in payload
        assert "currency" not in payload
