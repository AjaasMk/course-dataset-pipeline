from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Settings
from .courselist import CourseEntry
from .generate import CourseResult, generate_course
from .perplexity import PerplexityClient
from .store import ArtifactStore

logger = logging.getLogger("coursegen.pilot")


def _log(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, default=str, sort_keys=True))


def resolve_names(entries: list[CourseEntry], names: list[str]) -> tuple[list[CourseEntry], list[str]]:
    by_name = {e.course_name.casefold(): e for e in entries}
    found: list[CourseEntry] = []
    missing: list[str] = []
    for name in names:
        entry = by_name.get(name.strip().casefold())
        if entry is None:
            missing.append(name)
        elif entry not in found:
            found.append(entry)
    return found, missing


def stratified_sample(
    entries: list[CourseEntry], count: int, seed: list[CourseEntry] | None = None
) -> list[CourseEntry]:
    picked: list[CourseEntry] = list(seed or [])[:count]
    chosen = {e.course_id for e in picked}

    by_discipline: dict[str, list[CourseEntry]] = {}
    for entry in entries:
        if entry.course_id in chosen:
            continue
        by_discipline.setdefault(entry.discipline, []).append(entry)

    round_index = 0
    while len(picked) < count:
        added = False
        for discipline in sorted(by_discipline):
            bucket = by_discipline[discipline]
            if round_index < len(bucket) and len(picked) < count:
                picked.append(bucket[round_index])
                added = True
        if not added:
            break
        round_index += 1
    return picked


@dataclass
class PilotReport:
    results: list[CourseResult] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        validated = [r for r in self.results if r.publishable]
        flagged = [r for r in self.results if not r.publishable]
        attempted = len(self.results) + len(self.errors)

        usage: dict[str, float] = {}
        flag_codes: Counter[str] = Counter()
        unsourced: Counter[str] = Counter()
        attempts_over_one: Counter[str] = Counter()
        chunk_flags: Counter[str] = Counter()

        for result in self.results:
            for outcome in result.chunk_outcomes:
                for key, value in outcome.usage.items():
                    usage[key] = usage.get(key, 0) + value
                if outcome.accepted and not outcome.citations:
                    unsourced[outcome.chunk_key] += 1
                if outcome.attempts > 1:
                    attempts_over_one[outcome.chunk_key] += 1
                if not outcome.accepted:
                    chunk_flags[outcome.chunk_key] += 1
                for report in outcome.reports:
                    if report.get("status") == "fail":
                        for finding in report.get("findings", []):
                            if finding.get("severity") == "error":
                                flag_codes[str(finding.get("code"))] += 1
            if result.validation:
                for finding in result.validation.get("findings", []):
                    if finding.get("severity") == "error":
                        flag_codes[str(finding.get("code"))] += 1

        requests = int(usage.get("requests", 0))
        per_course = requests / len(self.results) if self.results else 0.0
        total_cost = usage.get("cost.total_cost", 0.0)

        return {
            "courses_attempted": attempted,
            "validated": len(validated),
            "flagged": len(flagged),
            "errored": len(self.errors),
            "flag_rate": round(len(flagged) / attempted, 3) if attempted else 0.0,
            "requests": {
                "total": requests,
                "per_course": round(per_course, 2),
                "baseline_per_course": 6,
                "retry_overhead": round(max(0.0, per_course - 6), 2),
            },
            "cost": {
                "total_usd": round(total_cost, 4),
                "per_course_usd": round(total_cost / len(self.results), 4) if self.results else 0.0,
                "projected_166_courses_usd": round(
                    total_cost / len(self.results) * 166, 2
                ) if self.results else 0.0,
                "breakdown_usd": {
                    k.replace("cost.", ""): round(v, 4)
                    for k, v in sorted(usage.items())
                    if k.startswith("cost.") and k != "cost.total_cost"
                },
            },
            "tokens": {
                k: int(v) for k, v in sorted(usage.items())
                if k != "requests" and not k.startswith("cost.") and "currency" not in k
            },
            "retried_chunks": dict(attempts_over_one.most_common()),
            "flagged_chunks": dict(chunk_flags.most_common()),
            "unsourced_chunks": dict(unsourced.most_common()),
            "top_validation_failures": dict(flag_codes.most_common(15)),
            "per_course": [
                {
                    "course_id": r.course_id,
                    "course_name": r.course_name,
                    "status": r.status,
                    "flagged_chunks": [o.chunk_key for o in r.chunk_outcomes if not o.accepted],
                    "unsourced_chunks": [
                        o.chunk_key for o in r.chunk_outcomes if o.accepted and not o.citations
                    ],
                    "requests": sum(o.usage.get("requests", 0) for o in r.chunk_outcomes),
                }
                for r in self.results
            ],
            "errors": self.errors,
        }


def run_pilot(
    entries: list[CourseEntry],
    *,
    settings: Settings,
    client_factory: Callable[[], Any] | None = None,
    on_course: Callable[[CourseEntry, CourseResult | None], None] | None = None,
) -> PilotReport:
    report = PilotReport()
    factory = client_factory or (lambda: PerplexityClient(settings))
    client = factory()
    try:
        for index, entry in enumerate(entries, start=1):
            _log(
                logging.INFO,
                "pilot.course",
                index=index,
                total=len(entries),
                course=entry.course_name,
                discipline=entry.discipline,
            )
            store = ArtifactStore(settings.artifacts_dir, entry.course_id)
            try:
                result = generate_course(
                    course_id=entry.course_id,
                    course_name=entry.course_name,
                    client=client,
                    settings=settings,
                    store=store,
                    discipline=entry.discipline,
                )
            except Exception as exc:
                _log(
                    logging.ERROR,
                    "pilot.course_failed",
                    course=entry.course_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                report.errors.append(
                    {
                        "course_id": entry.course_id,
                        "course_name": entry.course_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                if on_course is not None:
                    on_course(entry, None)
                continue
            report.results.append(result)
            if on_course is not None:
                on_course(entry, result)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return report
