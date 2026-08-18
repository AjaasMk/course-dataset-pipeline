from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import httpx
import pytest

from coursegen.config import ConfigError, Settings
from coursegen.publish import (
    Ledger,
    PublishAborted,
    build_headers,
    build_payload,
    checksum,
    collect_publishable,
    extract_remote_id,
    publish_all,
    publish_document,
    target_url,
)


def seed_course(root: Path, course_id: str, name: str, status: str = "validated") -> dict:
    folder = root / course_id
    folder.mkdir(parents=True, exist_ok=True)
    document = {"course_id": course_id, "course_name": name, "slug": name.lower(), "fees": {}}
    (folder / "course.json").write_text(json.dumps(document), encoding="utf-8")
    (folder / "run.json").write_text(
        json.dumps({"course_id": course_id, "course_name": name, "status": status}),
        encoding="utf-8",
    )
    return document


def live(settings: Settings, tmp_path: Path, **overrides) -> Settings:
    base = dict(
        artifacts_dir=tmp_path,
        laravel_endpoint="https://portal.test/api/courses",
        laravel_token="secret-token",
        transport_max_retries=1,
    )
    base.update(overrides)
    return dataclasses.replace(settings, **base)


def transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_bare_payload_by_default(settings: Settings) -> None:
    assert build_payload({"a": 1}, settings) == {"a": 1}


def test_payload_can_be_wrapped(settings: Settings) -> None:
    scoped = dataclasses.replace(settings, laravel_payload_key="course")
    assert build_payload({"a": 1}, scoped) == {"course": {"a": 1}}


def test_auth_header_is_configurable(settings: Settings) -> None:
    assert build_headers(settings, "t")["Authorization"] == "Bearer t"
    scoped = dataclasses.replace(settings, laravel_auth_header="X-Api-Key", laravel_auth_scheme="")
    headers = build_headers(scoped, "t")
    assert headers["X-Api-Key"] == "t"
    assert "Authorization" not in headers


def test_put_targets_the_course_resource(settings: Settings) -> None:
    post = dataclasses.replace(settings, laravel_endpoint="https://x/api/courses")
    assert target_url(post, "crs_a") == "https://x/api/courses"
    put = dataclasses.replace(post, laravel_method="PUT")
    assert target_url(put, "crs_a") == "https://x/api/courses/crs_a"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"id": 7}, "7"),
        ({"data": {"id": "abc"}}, "abc"),
        ({"course_id": "crs_x"}, "crs_x"),
        ({"message": "ok"}, None),
        (None, None),
    ],
)
def test_remote_id_extraction(body, expected) -> None:
    assert extract_remote_id(body) == expected


def test_only_validated_courses_are_publishable(tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_ok", "Good")
    seed_course(tmp_path, "crs_bad", "Flagged", status="flagged")
    found = collect_publishable(tmp_path)
    assert [c[0] for c in found] == ["crs_ok"]


def test_successful_publish_records_the_ledger(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["url"] = str(request.url)
        sent["auth"] = request.headers.get("authorization")
        sent["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 42})

    summary = publish_all(
        live(settings, tmp_path), client_factory=lambda: transport(handler)
    )
    assert summary["published"] == 1
    assert summary["results"][0]["remote_id"] == "42"
    assert sent["url"] == "https://portal.test/api/courses"
    assert sent["auth"] == "Bearer secret-token"
    assert sent["body"]["course_id"] == "crs_a"

    ledger = Ledger.load(tmp_path / "_published.json")
    assert ledger.entries["crs_a"]["remote_id"] == "42"


def test_republishing_is_skipped_when_nothing_changed(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"id": 1})

    scoped = live(settings, tmp_path)
    publish_all(scoped, client_factory=lambda: transport(handler))
    second = publish_all(scoped, client_factory=lambda: transport(handler))

    assert calls["n"] == 1
    assert second["already_published"] == 1
    assert second["queued"] == 0


def test_an_edited_course_is_sent_again(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"id": 1})

    scoped = live(settings, tmp_path)
    publish_all(scoped, client_factory=lambda: transport(handler))
    path = tmp_path / "crs_a" / "course.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["course_name"] = "B.Com (revised)"
    path.write_text(json.dumps(document), encoding="utf-8")

    publish_all(scoped, client_factory=lambda: transport(handler))
    assert calls["n"] == 2


def test_force_resends_even_when_unchanged(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"id": 1})

    scoped = live(settings, tmp_path)
    publish_all(scoped, client_factory=lambda: transport(handler))
    publish_all(scoped, force=True, client_factory=lambda: transport(handler))
    assert calls["n"] == 2


def test_422_is_a_contract_mismatch_and_is_not_retried(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(422, json={"errors": {"fees": ["required"]}})

    summary = publish_all(
        live(settings, tmp_path), client_factory=lambda: transport(handler)
    )
    assert calls["n"] == 1
    assert summary["rejected"] == 1
    assert summary["published"] == 0
    assert "fees" in summary["results"][0]["body"]
    assert not (tmp_path / "_published.json").exists() or not Ledger.load(
        tmp_path / "_published.json"
    ).entries


def test_500_is_retried_then_reported(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    summary = publish_all(
        live(settings, tmp_path, transport_backoff_base_seconds=0.0),
        client_factory=lambda: transport(handler),
    )
    assert calls["n"] == 2
    assert summary["failed"] == 1


def test_401_aborts_the_whole_run(settings: Settings, tmp_path: Path) -> None:
    for i in range(3):
        seed_course(tmp_path, f"crs_{i}", f"Course {i}")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"message": "Unauthenticated."})

    summary = publish_all(
        live(settings, tmp_path), client_factory=lambda: transport(handler)
    )
    assert calls["n"] == 1
    assert summary["published"] == 0
    assert "credential was rejected" in summary["aborted"]


def test_dry_run_sends_nothing(settings: Settings, tmp_path: Path) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("dry run must not make a request")

    summary = publish_all(
        live(settings, tmp_path), dry_run=True, client_factory=lambda: transport(handler)
    )
    assert summary["status"] == "dry_run"
    assert summary["queued"] == 1
    assert summary["courses"][0]["course_id"] == "crs_a"


def test_publishing_without_a_configured_endpoint_fails_clearly(
    settings: Settings, tmp_path: Path
) -> None:
    seed_course(tmp_path, "crs_a", "B.Com")
    scoped = dataclasses.replace(settings, artifacts_dir=tmp_path)
    with pytest.raises(ConfigError, match="LARAVEL_ENDPOINT"):
        publish_all(scoped)


def test_abort_propagates_from_publish_document(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    scoped = dataclasses.replace(
        settings, laravel_endpoint="https://x/api", laravel_token="t"
    )
    with pytest.raises(PublishAborted):
        publish_document(
            {"a": 1},
            settings=scoped,
            client=transport(handler),
            course_id="crs_a",
            course_name="X",
        )


def test_checksum_is_stable_and_order_independent() -> None:
    assert checksum({"a": 1, "b": 2}) == checksum({"b": 2, "a": 1})
    assert checksum({"a": 1}) != checksum({"a": 2})
