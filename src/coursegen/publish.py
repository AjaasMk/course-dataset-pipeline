from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import Settings
from .retry import TransportError, call_with_retry, transport_error_from_response
from .store import read_json, write_json

logger = logging.getLogger("coursegen.publish")

CONTRACT_MISMATCH: frozenset[int] = frozenset({400, 404, 409, 422})
ABORT_STATUSES: frozenset[int] = frozenset({401, 403})


def _log(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, default=str, sort_keys=True))


class PublishAborted(RuntimeError):
    pass


@dataclass
class PublishOutcome:
    course_id: str
    course_name: str
    status: str
    http_status: int | None = None
    remote_id: str | None = None
    error: str | None = None
    body: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "published"

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "course_name": self.course_name,
            "status": self.status,
            "http_status": self.http_status,
            "remote_id": self.remote_id,
            "error": self.error,
            "body": self.body,
        }


@dataclass
class Ledger:
    path: Path
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        try:
            raw = read_json(path)
        except (json.JSONDecodeError, OSError):
            return cls(path=path)
        entries = raw.get("published") if isinstance(raw, dict) else None
        return cls(path=path, entries=entries if isinstance(entries, dict) else {})

    def unchanged_since_publish(self, course_id: str, digest: str) -> bool:
        entry = self.entries.get(course_id)
        return bool(entry) and entry.get("checksum") == digest

    def mark(self, outcome: PublishOutcome, digest: str) -> None:
        self.entries[outcome.course_id] = {
            "course_name": outcome.course_name,
            "http_status": outcome.http_status,
            "remote_id": outcome.remote_id,
            "checksum": digest,
        }

    def save(self) -> None:
        write_json(self.path, {"published": self.entries})


def checksum(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


def build_payload(document: dict[str, Any], settings: Settings) -> dict[str, Any]:
    key = settings.laravel_payload_key
    return {key: document} if key else document


def build_headers(settings: Settings, token: str) -> dict[str, str]:
    credential = f"{settings.laravel_auth_scheme} {token}".strip()
    return {
        settings.laravel_auth_header: credential,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def target_url(settings: Settings, course_id: str) -> str:
    url = settings.laravel_endpoint.rstrip("/")
    return f"{url}/{course_id}" if settings.laravel_method == "PUT" else url


def extract_remote_id(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("id", "course_id", "uuid"):
        value = body.get(key)
        if isinstance(value, (str, int)):
            return str(value)
    return extract_remote_id(body.get("data"))


def publish_document(
    document: dict[str, Any],
    *,
    settings: Settings,
    client: httpx.Client,
    course_id: str,
    course_name: str,
) -> PublishOutcome:
    _, token = settings.require_publish_target()
    url = target_url(settings, course_id)
    headers = build_headers(settings, token)
    payload = build_payload(document, settings)

    def send() -> httpx.Response:
        response = client.request(settings.laravel_method, url, headers=headers, json=payload)
        if response.status_code in ABORT_STATUSES:
            raise PublishAborted(
                f"HTTP {response.status_code} from {url}: the API credential was rejected"
            )
        if response.status_code in CONTRACT_MISMATCH:
            raise TransportError(
                f"HTTP {response.status_code} from {url}",
                status_code=response.status_code,
                retryable=False,
                body=response.text[:800],
            )
        if response.status_code >= 400:
            raise transport_error_from_response(response)
        return response

    try:
        response = call_with_retry(
            f"publish:{course_id}",
            send,
            max_retries=settings.transport_max_retries,
            base_delay_seconds=settings.transport_backoff_base_seconds,
            max_delay_seconds=settings.transport_backoff_max_seconds,
        )
    except PublishAborted:
        raise
    except TransportError as exc:
        rejected = exc.status_code in CONTRACT_MISMATCH
        _log(
            logging.ERROR,
            "publish.rejected" if rejected else "publish.failed",
            course_id=course_id,
            status_code=exc.status_code,
            error=str(exc),
        )
        return PublishOutcome(
            course_id=course_id,
            course_name=course_name,
            status="rejected" if rejected else "failed",
            http_status=exc.status_code,
            error=str(exc),
            body=exc.body,
        )
    except httpx.HTTPError as exc:
        _log(logging.ERROR, "publish.failed", course_id=course_id, error=str(exc))
        return PublishOutcome(
            course_id=course_id, course_name=course_name, status="failed", error=str(exc)
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    _log(logging.INFO, "publish.ok", course_id=course_id, status_code=response.status_code)
    return PublishOutcome(
        course_id=course_id,
        course_name=course_name,
        status="published",
        http_status=response.status_code,
        remote_id=extract_remote_id(body),
    )


def collect_publishable(artifacts_dir: Path) -> list[tuple[str, str, dict[str, Any]]]:
    found: list[tuple[str, str, dict[str, Any]]] = []
    for run_path in sorted(Path(artifacts_dir).glob("*/run.json")):
        try:
            run = read_json(run_path)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(run, dict) or run.get("status") != "validated":
            continue
        course_path = run_path.parent / "course.json"
        if not course_path.exists():
            continue
        try:
            document = read_json(course_path)
        except (json.JSONDecodeError, OSError):
            continue
        found.append((str(run.get("course_id", "")), str(run.get("course_name", "")), document))
    return found


def publish_all(
    settings: Settings,
    *,
    course_id: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> dict[str, Any]:
    ledger = Ledger.load(Path(settings.artifacts_dir) / "_published.json")
    candidates = collect_publishable(Path(settings.artifacts_dir))
    if course_id:
        candidates = [c for c in candidates if c[0] == course_id]

    queued: list[tuple[str, str, dict[str, Any], str]] = []
    unchanged = 0
    for cid, name, document in candidates:
        digest = checksum(document)
        if not force and ledger.unchanged_since_publish(cid, digest):
            unchanged += 1
            continue
        queued.append((cid, name, document, digest))

    summary: dict[str, Any] = {
        "endpoint": settings.laravel_endpoint or None,
        "method": settings.laravel_method,
        "publishable": len(candidates),
        "already_published": unchanged,
        "queued": len(queued),
    }

    if dry_run:
        summary["status"] = "dry_run"
        summary["courses"] = [{"course_id": c, "course_name": n} for c, n, _, _ in queued]
        return summary

    if not queued:
        summary.update(published=0, rejected=0, failed=0, aborted=None, results=[])
        return summary

    settings.require_publish_target()
    factory = client_factory or (lambda: httpx.Client(timeout=settings.request_timeout_seconds))
    client = factory()
    results: list[PublishOutcome] = []
    aborted: str | None = None
    try:
        for cid, name, document, digest in queued:
            try:
                outcome = publish_document(
                    document, settings=settings, client=client, course_id=cid, course_name=name
                )
            except PublishAborted as exc:
                aborted = str(exc)
                _log(logging.ERROR, "publish.aborted", error=aborted)
                break
            results.append(outcome)
            if outcome.succeeded:
                ledger.mark(outcome, digest)
    finally:
        client.close()
        ledger.save()

    summary.update(
        published=len([r for r in results if r.status == "published"]),
        rejected=len([r for r in results if r.status == "rejected"]),
        failed=len([r for r in results if r.status == "failed"]),
        aborted=aborted,
        results=[r.to_dict() for r in results],
    )
    return summary
