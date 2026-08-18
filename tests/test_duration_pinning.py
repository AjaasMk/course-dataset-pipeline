from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from coursegen.chunks import CHUNKS_BY_KEY
from coursegen.config import Settings
from coursegen.durations import Duration
from coursegen.generate import (
    apply_duration,
    duration_aware_chunk,
    duration_constraints,
    generate_course,
)
from coursegen.schema_tools import SchemaError, chunk_schema, load_root_schema, pin_curriculum_years
from coursegen.validate import RuleContext
from coursegen.validate.rules import rule_curriculum_length_matches_duration

from test_generate import COURSE_ID, COURSE_NAME, FakeClient, chunk_payload

MBBS = Duration(min_years=5.5, max_years=5.5, academic_years=4, source="test")
BSC = Duration(min_years=3, max_years=4, academic_years=4, source="test")


@pytest.fixture()
def pinned(settings: Settings, tmp_path: Path) -> Settings:
    path = tmp_path / "durations.json"
    path.write_text(
        json.dumps(
            {"exact": {COURSE_NAME.casefold(): {"min_years": 5.5, "max_years": 5.5, "academic_years": 4}}}
        ),
        encoding="utf-8",
    )
    return dataclasses.replace(settings, durations_path=path)


def test_pinning_fixes_the_year_count(schema_path: Path) -> None:
    schema = chunk_schema(load_root_schema(schema_path), CHUNKS_BY_KEY["academics"])
    pin_curriculum_years(schema, 4)
    years = schema["properties"]["curriculum"]["properties"]["years"]
    assert years["minItems"] == years["maxItems"] == 4
    assert years["items"]["properties"]["year"]["maximum"] == 4


def test_pinning_outside_the_schema_bounds_is_refused(schema_path: Path) -> None:
    schema = chunk_schema(load_root_schema(schema_path), CHUNKS_BY_KEY["academics"])
    ceiling = schema["properties"]["curriculum"]["properties"]["years"]["maxItems"]
    with pytest.raises(SchemaError, match="at most"):
        pin_curriculum_years(schema, ceiling + 1)


def test_duration_leaves_the_profile_chunk_schema(schema_path: Path) -> None:
    profile = CHUNKS_BY_KEY["profile"]
    aware = duration_aware_chunk(profile, MBBS)
    root = load_root_schema(schema_path)
    assert "typical_duration" in chunk_schema(root, profile)["properties"]["quick_facts"]["properties"]
    assert "typical_duration" not in chunk_schema(root, aware)["properties"]["quick_facts"]["properties"]


def test_an_unpinned_course_keeps_generating_its_own_duration() -> None:
    profile = CHUNKS_BY_KEY["profile"]
    assert duration_aware_chunk(profile, None) is profile
    assert duration_constraints(profile, None) == []


def test_only_the_owning_chunks_are_told(schema_path: Path) -> None:
    assert duration_aware_chunk(CHUNKS_BY_KEY["market"], MBBS) is CHUNKS_BY_KEY["market"]
    assert duration_constraints(CHUNKS_BY_KEY["market"], MBBS) == []


def test_the_curriculum_constraint_names_the_taught_year_count() -> None:
    line = " ".join(duration_constraints(CHUNKS_BY_KEY["academics"], MBBS))
    assert "exactly 4 curriculum entries" in line
    assert "5.5 years" in line
    assert "internship" in line


def test_a_variable_length_course_states_both_ends() -> None:
    line = " ".join(duration_constraints(CHUNKS_BY_KEY["academics"], BSC))
    assert "3 to 4 years" in line


def test_apply_duration_overwrites_whatever_the_model_said() -> None:
    document = {"quick_facts": {"typical_duration": {"min_years": 99, "max_years": 99}}}
    apply_duration(document, MBBS)
    assert document["quick_facts"]["typical_duration"] == {"min_years": 5.5, "max_years": 5.5}


def test_apply_duration_is_a_no_op_without_one() -> None:
    document = {"quick_facts": {"typical_duration": {"min_years": 3, "max_years": 4}}}
    apply_duration(document, None)
    assert document["quick_facts"]["typical_duration"] == {"min_years": 3, "max_years": 4}


def test_the_length_rule_accepts_fewer_tabs_than_years_when_pinned() -> None:
    document = {
        "quick_facts": {"typical_duration": {"min_years": 5.5, "max_years": 5.5}},
        "curriculum": {"years": [{"year": n} for n in range(1, 5)]},
    }
    pinned_ctx = RuleContext(currency="INR", allowed_domains=(), academic_years=4)
    assert list(rule_curriculum_length_matches_duration(document, pinned_ctx)) == []

    unpinned_ctx = RuleContext(currency="INR", allowed_domains=())
    findings = list(rule_curriculum_length_matches_duration(document, unpinned_ctx))
    assert [f.code for f in findings] == ["curriculum_length_mismatch"]


def test_the_length_rule_still_catches_a_wrong_count_when_pinned() -> None:
    document = {
        "quick_facts": {"typical_duration": {"min_years": 5.5, "max_years": 5.5}},
        "curriculum": {"years": [{"year": n} for n in range(1, 4)]},
    }
    ctx = RuleContext(currency="INR", allowed_domains=(), academic_years=4)
    findings = list(rule_curriculum_length_matches_duration(document, ctx))
    assert [f.code for f in findings] == ["curriculum_length_mismatch"]
    assert "4 taught years" in findings[0].message


def test_a_pinned_course_ignores_the_model_duration_end_to_end(
    pinned: Settings, demo_document: dict
) -> None:
    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        chunk_key = operation.split(":")[-1]
        payload = chunk_payload(demo_document, chunk_key)
        if chunk_key == "profile":
            payload["quick_facts"]["typical_duration"] = {"min_years": 1, "max_years": 1}
        return payload

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=client,
        settings=pinned,
        category="Health & Behavioural Sciences",
    )
    assert result.status == "validated"
    assert result.document["quick_facts"]["typical_duration"] == {"min_years": 5.5, "max_years": 5.5}


def test_the_pinned_year_count_reaches_the_schema_the_provider_sees(
    pinned: Settings, demo_document: dict
) -> None:
    client = FakeClient(lambda op, _: chunk_payload(demo_document, op.split(":")[-1]))
    original = client.complete_json
    seen: dict[str, Any] = {}

    def capture(*, operation: str, json_schema: dict[str, Any], **kwargs: Any):
        if operation.endswith(":academics"):
            seen["years"] = json_schema["properties"]["curriculum"]["properties"]["years"]
        if operation.endswith(":profile"):
            seen["quick_facts"] = json_schema["properties"]["quick_facts"]["properties"]
        return original(operation=operation, json_schema=json_schema, **kwargs)

    client.complete_json = capture
    generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=client,
        settings=pinned,
        category="Health & Behavioural Sciences",
    )
    assert seen["years"]["minItems"] == seen["years"]["maxItems"] == 4
    assert "typical_duration" not in seen["quick_facts"]


def test_the_constraint_reaches_the_prompt(pinned: Settings, demo_document: dict) -> None:
    client = FakeClient(lambda op, _: chunk_payload(demo_document, op.split(":")[-1]))
    generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=client,
        settings=pinned,
        category="Health & Behavioural Sciences",
    )
    academics = next(c for c in client.calls if c["operation"].endswith(":academics"))
    assert "exactly 4 curriculum entries" in academics["user_prompt"]


def test_a_chunk_with_the_wrong_number_of_years_is_rejected(
    pinned: Settings, demo_document: dict
) -> None:
    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        chunk_key = operation.split(":")[-1]
        payload = chunk_payload(demo_document, chunk_key)
        if chunk_key == "academics":
            years = payload["curriculum"]["years"]
            extra = copy.deepcopy(years[-1])
            extra["year"] = len(years) + 1
            years.append(extra)
        return payload

    client = FakeClient(responder)
    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        client=client,
        settings=pinned,
        category="Health & Behavioural Sciences",
    )
    assert result.status == "flagged"
    academics = next(o for o in result.chunk_outcomes if o.chunk_key == "academics")
    assert not academics.accepted
    assert academics.attempts == pinned.generation_max_attempts
