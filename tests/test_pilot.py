from __future__ import annotations

from typing import Any

from coursegen.config import Settings
from coursegen.courselist import CourseEntry
from coursegen.pilot import PilotReport, run_pilot, stratified_sample

from test_generate import FakeClient, chunk_payload


def entry(name: str, discipline: str, index: int) -> CourseEntry:
    return CourseEntry(
        course_id=f"crs_{index}",
        slug=f"slug-{index}",
        course_name=name,
        category="Health & Behavioural Sciences",
        categories=("Health & Behavioural Sciences",),
        discipline=discipline,
    )


def test_sample_spreads_across_disciplines() -> None:
    entries = [entry(f"C{i}", f"d{i % 4}", i) for i in range(40)]
    picked = stratified_sample(entries, 8)
    assert len(picked) == 8
    assert len({e.discipline for e in picked}) == 4


def test_sample_stops_when_pool_is_smaller_than_count() -> None:
    entries = [entry("A", "d0", 0), entry("B", "d1", 1)]
    assert len(stratified_sample(entries, 10)) == 2


def test_pilot_aggregates_status_and_usage(settings: Settings, demo_document: dict) -> None:
    entries = [entry("BSc Psychology", "science", i) for i in range(3)]
    client = FakeClient(lambda op, _: chunk_payload(demo_document, op.split(":")[-1]))
    report = run_pilot(entries, settings=settings, client_factory=lambda: client)
    payload = report.to_dict()

    assert payload["courses_attempted"] == 3
    assert payload["validated"] == 3
    assert payload["flagged"] == 0
    assert payload["flag_rate"] == 0.0
    assert payload["requests"]["total"] == 18
    assert payload["requests"]["per_course"] == 6.0
    assert payload["requests"]["retry_overhead"] == 0.0


def test_pilot_records_flags_and_failure_codes(settings: Settings, demo_document: dict) -> None:
    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        payload = chunk_payload(demo_document, operation.split(":")[-1])
        if "careers" in payload:
            payload["careers"][1]["title"] = payload["careers"][0]["title"]
        return payload

    entries = [entry("BSc Psychology", "science", 0)]
    report = run_pilot(entries, settings=settings, client_factory=lambda: FakeClient(responder))
    payload = report.to_dict()

    assert payload["flagged"] == 1
    assert payload["flag_rate"] == 1.0
    assert payload["flagged_chunks"] == {"outcomes": 1}
    assert "duplicate_career" in payload["top_validation_failures"]
    assert payload["requests"]["retry_overhead"] > 0


def test_pilot_survives_a_course_that_raises(settings: Settings, demo_document: dict) -> None:
    calls = {"n": 0}

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        calls["n"] += 1
        if operation.startswith("crs_0:"):
            raise RuntimeError("boom")
        return chunk_payload(demo_document, operation.split(":")[-1])

    entries = [entry("BSc Psychology", "d0", 0), entry("BSc Psychology", "d1", 1)]
    report = run_pilot(entries, settings=settings, client_factory=lambda: FakeClient(responder))
    payload = report.to_dict()

    assert payload["errored"] == 1
    assert payload["validated"] == 1
    assert payload["errors"][0]["error_type"] == "RuntimeError"


def test_empty_report_is_safe() -> None:
    payload = PilotReport().to_dict()
    assert payload["courses_attempted"] == 0
    assert payload["flag_rate"] == 0.0


def test_nested_cost_is_flattened_and_aggregated(settings: Settings, demo_document: dict) -> None:
    from coursegen.generate import flatten_usage
    from coursegen.perplexity import ChunkResponse

    live = {
        "cost": {
            "currency": "USD",
            "input_cost": 0.00162,
            "output_cost": 0.00083,
            "tool_calls_cost": 0.0025,
            "tool_calls_cost_details": {"search_web": 0.0025},
            "total_cost": 0.00495,
        },
        "input_tokens": 2158,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 184,
        "output_tokens_details": {"reasoning_tokens": 140},
        "total_tokens": 2342,
    }
    flat = flatten_usage(live)
    assert flat["cost.total_cost"] == 0.00495
    assert flat["cost.tool_calls_cost_details.search_web"] == 0.0025
    assert flat["input_tokens"] == 2158
    assert flat["output_tokens_details.reasoning_tokens"] == 140
    assert "cost.currency" not in flat

    class CostClient(FakeClient):
        def complete_json(self, *, operation: str, search_domains=None, **kwargs: Any):
            response = super().complete_json(operation=operation, **kwargs)
            return ChunkResponse(
                data=response.data, citations=response.citations, usage=live
            )

    entries = [entry("BSc Psychology", "science", i) for i in range(2)]
    payload = run_pilot(
        entries,
        settings=settings,
        client_factory=lambda: CostClient(lambda op, _: chunk_payload(demo_document, op.split(":")[-1])),
    ).to_dict()

    assert payload["requests"]["total"] == 12
    assert payload["cost"]["total_usd"] == round(0.00495 * 12, 4)
    assert payload["cost"]["per_course_usd"] == round(0.00495 * 6, 4)
    assert payload["cost"]["projected_166_courses_usd"] == round(0.00495 * 6 * 166, 2)
    assert payload["cost"]["breakdown_usd"]["tool_calls_cost"] == round(0.0025 * 12, 4)
    assert payload["tokens"]["total_tokens"] == 2342 * 12
    assert "currency" not in str(payload["tokens"])


def test_named_courses_are_guaranteed_in_the_sample() -> None:
    from coursegen.pilot import resolve_names

    entries = [entry(f"C{i}", f"d{i % 4}", i) for i in range(40)]
    entries.append(entry("MBBS", "medical", 99))
    seed, missing = resolve_names(entries, ["mbbs"])
    assert missing == []
    picked = stratified_sample(entries, 6, seed=seed)
    assert picked[0].course_name == "MBBS"
    assert len(picked) == 6
    assert len({e.course_id for e in picked}) == 6


def test_unknown_included_name_is_reported() -> None:
    from coursegen.pilot import resolve_names

    entries = [entry("MBBS", "medical", 0)]
    seed, missing = resolve_names(entries, ["MBBS", "Nonexistent Course"])
    assert [e.course_name for e in seed] == ["MBBS"]
    assert missing == ["Nonexistent Course"]


def test_seed_does_not_duplicate_into_the_stratified_fill() -> None:
    entries = [entry(f"C{i}", f"d{i % 3}", i) for i in range(9)]
    seed = [entries[0], entries[1]]
    picked = stratified_sample(entries, 5, seed=seed)
    assert len({e.course_id for e in picked}) == 5
    assert picked[:2] == seed
