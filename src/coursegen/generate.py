from __future__ import annotations

import json
import logging
import re
from datetime import date
from dataclasses import dataclass, field
from typing import Any

from .chunks import CHUNKS, CHUNKS_BY_KEY, Chunk, chunk_owning
from .config import Settings
from .domains import DomainRegistry, normalize_discipline
from .perplexity import ChunkResponse, PerplexityClient, ProviderOutputError
from .prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt
from .retry import TransportError
from .schema_tools import chunk_schema, load_root_schema, relax_for_provider
from .store import ArtifactStore
from .validate import RuleContext, ValidationReport, validate_document

logger = logging.getLogger("coursegen.generate")

CITATION_MARKER_RE = re.compile(r"\s*\[\d+(?:\s*[,;]\s*\d+)*\]")

CONTEXT_KEYS: tuple[str, ...] = ("course_level", "category", "subcategory", "quick_facts")
MAX_DOCUMENT_REPAIR_ROUNDS = 2


def _log(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, default=str, sort_keys=True))


@dataclass
class ChunkOutcome:
    chunk_key: str
    status: str
    attempts: int
    data: dict[str, Any] | None = None
    reports: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    search_result_count: int = 0
    search_domains: list[str] = field(default_factory=list)
    usage: dict[str, float] = field(default_factory=dict)
    transport_error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk": self.chunk_key,
            "status": self.status,
            "attempts": self.attempts,
            "citations": self.citations,
            "grounding": {
                "search_domains": self.search_domains,
                "citations": len(self.citations),
                "search_results": self.search_result_count,
                "unsourced": self.status == "accepted" and not self.citations,
            },
            "usage": self.usage,
            "transport_error": self.transport_error,
            "reports": self.reports,
        }


@dataclass
class CourseResult:
    course_id: str
    course_name: str
    status: str
    document: dict[str, Any]
    chunk_outcomes: list[ChunkOutcome]
    validation: dict[str, Any] | None = None

    @property
    def publishable(self) -> bool:
        return self.status == "validated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "course_name": self.course_name,
            "status": self.status,
            "flagged_chunks": [o.chunk_key for o in self.chunk_outcomes if not o.accepted],
            "unsourced_chunks": [
                o.chunk_key for o in self.chunk_outcomes if o.accepted and not o.citations
            ],
            "chunks": [o.to_dict() for o in self.chunk_outcomes],
            "validation": self.validation,
        }


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)


def injected_fields(course_id: str, course_name: str, settings: Settings) -> dict[str, Any]:
    return {
        "course_id": course_id,
        "slug": slugify(course_name),
        "course_name": course_name,
        "currency": settings.currency,
        "region": settings.region,
    }


def strip_citation_markers(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: strip_citation_markers(value) for key, value in node.items()}
    if isinstance(node, list):
        return [strip_citation_markers(item) for item in node]
    if isinstance(node, str):
        cleaned = CITATION_MARKER_RE.sub('', node)
        cleaned = re.sub(r'[ \t]+([.,;:!?])', lambda m: m.group(1), cleaned)
        cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
        return cleaned.strip()
    return node


def apply_derived_fields(
    document: dict[str, Any], settings: Settings | None = None
) -> dict[str, Any]:
    verification = document.get("verification")
    if isinstance(verification, dict):
        verification["last_reviewed"] = date.today().isoformat()
        sources = verification.get("sources")
        if isinstance(sources, list):
            seen: set[str] = set()
            deduped = []
            for source in sources:
                url = source.get("url") if isinstance(source, dict) else None
                if isinstance(url, str) and url not in seen:
                    seen.add(url)
                    deduped.append(source)
            verification["sources"] = deduped

    salary = document.get("snapshot", {}).get("salary") if isinstance(document.get("snapshot"), dict) else None
    if isinstance(salary, dict):
        low, typical, high = salary.get("lower_annual"), salary.get("typical_annual"), salary.get("higher_annual")
        if all(isinstance(v, int) for v in (low, typical, high)) and high > low:
            salary["marker_percent"] = max(0, min(100, round((typical - low) / (high - low) * 100)))
        elif not isinstance(salary.get("marker_percent"), int):
            salary["marker_percent"] = 50
    return document


def flatten_usage(usage: dict[str, Any], prefix: str = "") -> dict[str, float]:
    flat: dict[str, float] = {}
    for key, value in (usage or {}).items():
        if key == "requests":
            continue
        name = f"{prefix}{key}"
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            flat[name] = flat.get(name, 0) + value
        elif isinstance(value, dict):
            for sub, amount in flatten_usage(value, f"{name}.").items():
                flat[sub] = flat.get(sub, 0) + amount
    return flat


def merge_usage(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    merged = dict(left)
    for key, value in right.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def strip_derived_fields(chunk: Chunk, data: dict[str, Any]) -> dict[str, Any]:
    stripped = json.loads(json.dumps(data))
    for dotted in chunk.derived_paths:
        parts = dotted.split(".")
        node = stripped
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return stripped


def build_context(accepted: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {"course_name": base["course_name"], "region": base["region"]}
    for key in CONTEXT_KEYS:
        if key in accepted:
            context[key] = accepted[key]
    return context


def generate_chunk(
    chunk: Chunk,
    *,
    client: PerplexityClient,
    settings: Settings,
    root_schema: dict[str, Any],
    base_fields: dict[str, Any],
    context: dict[str, Any],
    store: ArtifactStore | None = None,
    seed_errors: list[str] | None = None,
    seed_data: dict[str, Any] | None = None,
    registry: DomainRegistry | None = None,
    discipline: str | None = None,
) -> ChunkOutcome:
    strict_schema = chunk_schema(root_schema, chunk)
    provider_schema = relax_for_provider(strict_schema)
    registry = registry if registry is not None else DomainRegistry.load(settings.domains_path)
    resolved = registry.resolve(discipline, chunk, settings.search_domains)
    search_domains = resolved.domains
    rule_context = RuleContext(
        currency=settings.currency,
        allowed_domains=registry.allowlist(settings.search_domains),
        search_filtered=bool(search_domains),
    )

    if not search_domains:
        _log(
            logging.WARNING,
            "chunk.unfiltered_search",
            course_id=base_fields["course_id"],
            chunk=chunk.key,
            discipline=resolved.discipline or None,
        )

    if resolved.dropped:
        _log(
            logging.WARNING,
            "chunk.domains_truncated",
            course_id=base_fields["course_id"],
            chunk=chunk.key,
            discipline=resolved.discipline or None,
            kept=list(resolved.domains),
            dropped=list(resolved.dropped),
        )

    previous_data: dict[str, Any] | None = seed_data
    previous_errors: list[str] = list(seed_errors or [])
    reports: list[dict[str, Any]] = []
    citations: list[str] = []
    search_result_count = 0
    usage_total: dict[str, float] = {}

    for attempt in range(1, settings.generation_max_attempts + 1):
        if previous_data is not None and previous_errors:
            user_prompt = build_repair_prompt(
                chunk,
                course_name=base_fields["course_name"],
                region=settings.region,
                currency=settings.currency,
                schema=provider_schema,
                previous_output=previous_data,
                error_lines=previous_errors,
                context=context,
                include_schema=settings.include_schema_in_prompt,
            )
        else:
            user_prompt = build_user_prompt(
                chunk,
                course_name=base_fields["course_name"],
                region=settings.region,
                currency=settings.currency,
                schema=provider_schema,
                context=context,
                include_schema=settings.include_schema_in_prompt,
            )

        _log(
            logging.INFO,
            "chunk.attempt",
            course_id=base_fields["course_id"],
            chunk=chunk.key,
            attempt=attempt,
            max_attempts=settings.generation_max_attempts,
            repair=bool(previous_data and previous_errors),
        )

        try:
            response: ChunkResponse = client.complete_json(
                operation=f"{base_fields['course_id']}:{chunk.key}",
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                json_schema=provider_schema,
                search_domains=search_domains,
            )
        except TransportError as exc:
            _log(
                logging.ERROR,
                "chunk.transport_failed",
                course_id=base_fields["course_id"],
                chunk=chunk.key,
                attempt=attempt,
                status_code=exc.status_code,
                error=str(exc),
            )
            return ChunkOutcome(
                chunk_key=chunk.key,
                status="flagged",
                attempts=attempt,
                reports=reports,
                citations=citations,
                search_domains=list(search_domains),
                usage=usage_total,
                transport_error=str(exc),
            )
        except ProviderOutputError as exc:
            usage_total["requests"] = usage_total.get("requests", 0) + 1
            previous_data = previous_data or {}
            previous_errors = [f"- <root>: {exc}"]
            citations = []
            search_result_count = 0
            reports.append(
                {
                    "attempt": attempt,
                    "status": "fail",
                    "scope": f"chunk:{chunk.key}",
                    "counts": {"errors": 1, "warnings": 0},
                    "findings": [
                        {
                            "code": "provider_output",
                            "path": "",
                            "message": str(exc),
                            "severity": "error",
                            "source": "rule",
                        }
                    ],
                }
            )
            continue

        candidate = strip_citation_markers(dict(response.data))
        citations = response.citations
        search_result_count = len(response.search_results)
        usage_total["requests"] = usage_total.get("requests", 0) + 1
        for key, value in flatten_usage(response.usage).items():
            usage_total[key] = usage_total.get(key, 0) + value
        if store is not None:
            store.save_attempt(
                chunk.key,
                attempt,
                {"data": candidate, "citations": response.citations, "usage": response.usage},
            )

        merged_for_rules = {**base_fields, **context, **candidate}
        report: ValidationReport = validate_document(
            candidate,
            strict_schema,
            rule_context,
            scope=f"chunk:{chunk.key}",
            course_id=base_fields["course_id"],
        )
        rules_only = validate_document(
            merged_for_rules,
            {"type": "object"},
            rule_context,
            scope=f"chunk:{chunk.key}:rules",
            course_id=base_fields["course_id"],
        )
        report.extend([f for f in rules_only.findings if f.source == "rule" and f not in report.findings])

        payload = report.to_dict() | {"attempt": attempt}
        reports.append(payload)

        if report.passed:
            _log(
                logging.INFO,
                "chunk.accepted",
                course_id=base_fields["course_id"],
                chunk=chunk.key,
                attempt=attempt,
                warnings=len(report.warnings),
            )
            if not citations:
                _log(
                    logging.WARNING,
                    "chunk.unsourced",
                    course_id=base_fields["course_id"],
                    chunk=chunk.key,
                    detail="provider returned no citations; this chunk may be written from model "
                    "memory rather than the searched sources",
                )
            accepted = apply_derived_fields(candidate, settings)
            if store is not None:
                store.save_chunk(chunk.key, accepted)
            return ChunkOutcome(
                chunk_key=chunk.key,
                status="accepted",
                attempts=attempt,
                data=accepted,
                reports=reports,
                citations=citations,
                search_result_count=search_result_count,
                search_domains=list(search_domains),
                usage=usage_total,
            )

        _log(
            logging.WARNING,
            "chunk.rejected",
            course_id=base_fields["course_id"],
            chunk=chunk.key,
            attempt=attempt,
            errors=len(report.errors),
            codes=sorted({f.code for f in report.errors}),
        )
        previous_data = candidate
        previous_errors = report.feedback_lines()

    _log(
        logging.ERROR,
        "chunk.flagged",
        course_id=base_fields["course_id"],
        chunk=chunk.key,
        attempts=settings.generation_max_attempts,
    )
    return ChunkOutcome(
        chunk_key=chunk.key,
        status="flagged",
        attempts=settings.generation_max_attempts,
        data=previous_data,
        reports=reports,
        citations=citations,
        search_result_count=search_result_count,
        search_domains=list(search_domains),
        usage=usage_total,
    )


def generate_course(
    *,
    course_id: str,
    course_name: str,
    client: PerplexityClient,
    settings: Settings,
    store: ArtifactStore | None = None,
    only_chunks: tuple[str, ...] | None = None,
    discipline: str | None = None,
) -> CourseResult:
    root_schema = load_root_schema(settings.schema_path)
    registry = DomainRegistry.load(settings.domains_path)
    discipline = normalize_discipline(discipline)
    base_fields = injected_fields(course_id, course_name, settings)
    selected = tuple(CHUNKS_BY_KEY[key] for key in only_chunks) if only_chunks else CHUNKS

    document: dict[str, Any] = dict(base_fields)
    outcomes: list[ChunkOutcome] = []

    if only_chunks and store is not None:
        for chunk in CHUNKS:
            if chunk.key in only_chunks:
                continue
            existing = store.load_chunk(chunk.key)
            if existing:
                document.update(existing)

    for chunk in selected:
        outcome = generate_chunk(
            chunk,
            client=client,
            settings=settings,
            root_schema=root_schema,
            base_fields=base_fields,
            context=build_context(document, base_fields),
            store=store,
            registry=registry,
            discipline=discipline,
        )
        outcomes.append(outcome)
        if outcome.data:
            document.update(outcome.data)

    document = apply_derived_fields(document, settings)

    if any(not o.accepted for o in outcomes):
        result = CourseResult(
            course_id=course_id,
            course_name=course_name,
            status="flagged",
            document=document,
            chunk_outcomes=outcomes,
        )
        _persist(result, store)
        return result

    result = _validate_and_repair(
        document=document,
        outcomes=outcomes,
        course_id=course_id,
        course_name=course_name,
        client=client,
        settings=settings,
        root_schema=root_schema,
        base_fields=base_fields,
        store=store,
        registry=registry,
        discipline=discipline,
    )
    _persist(result, store)
    return result


def _validate_and_repair(
    *,
    document: dict[str, Any],
    outcomes: list[ChunkOutcome],
    course_id: str,
    course_name: str,
    client: PerplexityClient,
    settings: Settings,
    root_schema: dict[str, Any],
    base_fields: dict[str, Any],
    store: ArtifactStore | None,
    registry: DomainRegistry,
    discipline: str | None,
) -> CourseResult:
    guidance_domains = registry.resolve(discipline, CHUNKS_BY_KEY["guidance"], settings.search_domains)
    rule_context = RuleContext(
        currency=settings.currency,
        allowed_domains=registry.allowlist(settings.search_domains),
        search_filtered=bool(guidance_domains.domains),
    )
    outcome_by_key = {o.chunk_key: o for o in outcomes}

    for round_index in range(MAX_DOCUMENT_REPAIR_ROUNDS + 1):
        report = validate_document(
            document, root_schema, rule_context, scope="document", course_id=course_id
        )
        if report.passed:
            return CourseResult(
                course_id=course_id,
                course_name=course_name,
                status="validated",
                document=document,
                chunk_outcomes=outcomes,
                validation=report.to_dict(),
            )

        failing = _chunks_for_paths(report.error_paths())
        _log(
            logging.WARNING,
            "document.rejected",
            course_id=course_id,
            round=round_index + 1,
            errors=len(report.errors),
            failing_chunks=sorted(c.key for c in failing),
        )

        if round_index == MAX_DOCUMENT_REPAIR_ROUNDS or not failing:
            return CourseResult(
                course_id=course_id,
                course_name=course_name,
                status="flagged",
                document=document,
                chunk_outcomes=outcomes,
                validation=report.to_dict(),
            )

        for chunk in failing:
            scoped_errors = [
                f"- {f.path or '<root>'}: {f.message}"
                for f in report.errors
                if _owning_key(f.path) in chunk.properties
            ]
            outcome = generate_chunk(
                chunk,
                client=client,
                settings=settings,
                root_schema=root_schema,
                base_fields=base_fields,
                context=build_context(document, base_fields),
                store=store,
                seed_errors=scoped_errors,
                seed_data=strip_derived_fields(
                    chunk, {key: document[key] for key in chunk.properties if key in document}
                ),
                registry=registry,
                discipline=discipline,
            )
            previous = outcome_by_key.get(chunk.key)
            if previous is not None:
                outcome.attempts += previous.attempts
                outcome.reports = previous.reports + outcome.reports
                outcome.usage = merge_usage(previous.usage, outcome.usage)
            outcome_by_key[chunk.key] = outcome
            outcomes = [outcome_by_key[o.chunk_key] for o in outcomes]
            if outcome.data:
                document.update(outcome.data)
            if not outcome.accepted:
                return CourseResult(
                    course_id=course_id,
                    course_name=course_name,
                    status="flagged",
                    document=document,
                    chunk_outcomes=outcomes,
                    validation=report.to_dict(),
                )
        document = apply_derived_fields(document, settings)

    return CourseResult(
        course_id=course_id,
        course_name=course_name,
        status="flagged",
        document=document,
        chunk_outcomes=outcomes,
    )


def _owning_key(path: str) -> str:
    for separator in (".", "["):
        index = path.find(separator)
        if index > 0:
            path = path[:index]
    return path


def _chunks_for_paths(paths: set[str]) -> list[Chunk]:
    keys = {
        chunk.key
        for path in paths
        if (chunk := chunk_owning(_owning_key(path))) is not None
    }
    return [chunk for chunk in CHUNKS if chunk.key in keys]


def _persist(result: CourseResult, store: ArtifactStore | None) -> None:
    if store is None:
        return
    store.save_course(result.document)
    store.save_run(result.to_dict())
    if result.validation is not None:
        store.save_validation(result.validation)


__all__ = [
    "ChunkOutcome",
    "CourseResult",
    "apply_derived_fields",
    "generate_chunk",
    "generate_course",
    "flatten_usage",
    "injected_fields",
    "merge_usage",
    "strip_citation_markers",
    "slugify",
]
