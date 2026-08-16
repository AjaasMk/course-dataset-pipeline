from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

from .chunks import CHUNKS, CHUNKS_BY_KEY
from .courselist import CourseListError, categories, iter_entries, load_course_list
from .domains import DomainRegistry, normalize_discipline
from .config import ConfigError, Settings, load_settings
from .generate import generate_course, injected_fields, slugify
from .perplexity import PerplexityClient
from .pilot import resolve_names, run_pilot, stratified_sample
from .review import load_review_queue
from .schema_tools import chunk_schema, load_root_schema, relax_for_provider
from .store import ArtifactStore, read_json, write_json
from .validate import RuleContext, validate_document


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _course_id_for(name: str, explicit: str | None) -> str:
    return explicit or f"crs_{slugify(name).replace('-', '_')}"


def cmd_generate(args: argparse.Namespace, settings: Settings) -> int:
    registry = DomainRegistry.load(settings.domains_path)
    discipline = normalize_discipline(args.discipline)
    if discipline and discipline not in registry.disciplines():
        if not settings.allow_unknown_discipline:
            raise ConfigError(
                f"discipline {discipline!r} is not declared in {settings.domains_path}; "
                f"known disciplines: {registry.disciplines()}. "
                "Set ALLOW_UNKNOWN_DISCIPLINE=true to fall back to the default domains instead."
            )
        logging.getLogger("coursegen.cli").warning(
            json.dumps(
                {
                    "event": "discipline.unknown",
                    "discipline": discipline,
                    "action": "falling back to default domains",
                }
            )
        )
    course_id = _course_id_for(args.course, args.course_id)
    store = ArtifactStore(settings.artifacts_dir, course_id)
    only = tuple(args.chunk) if args.chunk else None
    if only:
        unknown = [key for key in only if key not in CHUNKS_BY_KEY]
        if unknown:
            raise ConfigError(f"unknown chunk(s) {unknown}; known chunks: {sorted(CHUNKS_BY_KEY)}")

    with PerplexityClient(settings) as client:
        result = generate_course(
            course_id=course_id,
            course_name=args.course,
            client=client,
            settings=settings,
            store=store,
            only_chunks=only,
            discipline=discipline,
        )

    if not result.publishable:
        _write_review(settings, result.to_dict(), course_id)
    _emit(result.to_dict())
    return 0 if result.publishable else 2


def cmd_validate(args: argparse.Namespace, settings: Settings) -> int:
    document = read_json(Path(args.path))
    root_schema = load_root_schema(settings.schema_path)
    registry = DomainRegistry.load(settings.domains_path)
    context = RuleContext(
        currency=settings.currency, allowed_domains=registry.allowlist(settings.search_domains)
    )
    report = validate_document(
        document,
        root_schema,
        context,
        scope="document",
        course_id=str(document.get("course_id", "")),
    )
    payload = report.to_dict()
    if args.out:
        write_json(Path(args.out), payload)
    _emit(payload)
    return 0 if report.passed else 1


def cmd_merge(args: argparse.Namespace, settings: Settings) -> int:
    course_id = _course_id_for(args.course, args.course_id)
    store = ArtifactStore(settings.artifacts_dir, course_id)
    document: dict[str, Any] = dict(injected_fields(course_id, args.course, settings))
    missing: list[str] = []
    for chunk in CHUNKS:
        data = store.load_chunk(chunk.key)
        if data is None:
            missing.append(chunk.key)
            continue
        document.update(data)
    store.save_course(document)
    _emit({"course_id": course_id, "path": str(store.course_path), "missing_chunks": missing})
    return 0 if not missing else 2


def cmd_schema(args: argparse.Namespace, settings: Settings) -> int:
    root_schema = load_root_schema(settings.schema_path)
    if args.chunk:
        chunk = CHUNKS_BY_KEY[args.chunk]
        schema = chunk_schema(root_schema, chunk)
        _emit(relax_for_provider(schema) if args.provider else schema)
        return 0
    _emit(
        [
            {
                "key": chunk.key,
                "title": chunk.title,
                "properties": list(chunk.properties),
                "derived": list(chunk.derived_paths),
            }
            for chunk in CHUNKS
        ]
    )
    return 0


def cmd_domains(args: argparse.Namespace, settings: Settings) -> int:
    registry = DomainRegistry.load(settings.domains_path)
    discipline = normalize_discipline(args.discipline)
    resolved = [registry.resolve(discipline, chunk, settings.search_domains) for chunk in CHUNKS]
    truncated = [r.chunk_key for r in resolved if r.dropped]
    empty = [r.chunk_key for r in resolved if not r.domains]
    _emit(
        {
            "status": "warn" if truncated or empty else "ok",
            "source_file": str(settings.domains_path),
            "discipline": discipline or None,
            "known_disciplines": registry.disciplines(),
            "fallback": list(settings.search_domains),
            "allowlist_used_for_source_validation": list(registry.allowlist(settings.search_domains)),
            "chunks_over_cap": truncated,
            "chunks_with_no_domains": empty,
            "per_chunk": {r.chunk_key: r.to_dict() for r in resolved},
        }
    )
    return 0


def cmd_courses(args: argparse.Namespace, settings: Settings) -> int:
    entries = load_course_list(args.path)
    registry = DomainRegistry.load(settings.domains_path)
    declared = set(registry.disciplines())

    if args.list:
        selected = iter_entries(entries, discipline=args.discipline, limit=args.limit)
        _emit([entry.to_dict() for entry in selected])
        return 0

    per_category: dict[str, int] = {}
    for entry in entries:
        for category in entry.categories:
            per_category[category] = per_category.get(category, 0) + 1

    present = {entry.discipline for entry in entries}
    _emit(
        {
            "source_file": str(args.path),
            "courses": len(entries),
            "categories": len(categories(entries)),
            "courses_per_category": per_category,
            "multi_category_courses": [
                {"course_name": e.course_name, "categories": list(e.categories), "primary": e.category}
                for e in entries
                if len(e.categories) > 1
            ],
            "disciplines_without_domain_entry": sorted(present - declared),
            "calls_at_six_per_course": len(entries) * len(CHUNKS),
        }
    )
    return 0


def cmd_pilot(args: argparse.Namespace, settings: Settings) -> int:
    entries = load_course_list(args.path)
    if args.discipline:
        entries = list(iter_entries(entries, discipline=args.discipline))
    seed: list = []
    if args.include:
        seed, missing = resolve_names(entries, args.include)
        if missing:
            raise ConfigError(
                f"--include named courses that are not in the list: {missing}. "
                "Names must match the workbook exactly."
            )
    selected = stratified_sample(entries, args.count, seed=seed)
    if not selected:
        raise ConfigError("no courses selected; check --discipline")

    registry = DomainRegistry.load(settings.domains_path)
    declared = set(registry.disciplines())
    missing = sorted({e.discipline for e in selected} - declared)
    if missing and not settings.allow_unknown_discipline:
        raise ConfigError(f"selected courses use undeclared disciplines: {missing}")

    plan = {
        "courses": [
            {"course_name": e.course_name, "discipline": e.discipline, "course_id": e.course_id}
            for e in selected
        ],
        "requests_if_no_retries": len(selected) * len(CHUNKS),
        "model": settings.perplexity_model,
        "region": settings.region,
    }
    if args.dry_run:
        _emit({"status": "dry_run", **plan})
        return 0

    settings.require_api_key()
    logging.getLogger("coursegen.cli").warning(json.dumps({"event": "pilot.start", **plan}))

    report = run_pilot(selected, settings=settings)
    payload = report.to_dict()
    for result in report.results:
        if not result.publishable:
            _write_review(settings, result.to_dict(), result.course_id)
    out = Path(args.out) if args.out else Path(settings.artifacts_dir) / "pilot-report.json"
    write_json(out, payload)
    payload["report_path"] = str(out)
    _emit(payload)
    return 0 if payload["flagged"] == 0 and payload["errored"] == 0 else 2


def cmd_smoke(args: argparse.Namespace, settings: Settings) -> int:
    settings.require_api_key()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["course_name", "typical_duration_years", "regulator"],
        "properties": {
            "course_name": {"type": "string"},
            "typical_duration_years": {"type": "number"},
            "regulator": {"type": "string"},
        },
    }
    registry = DomainRegistry.load(settings.domains_path)
    domains = registry.resolve(args.discipline, CHUNKS_BY_KEY["academics"], settings.search_domains)

    with PerplexityClient(settings) as client:
        try:
            response = client.complete_json(
                operation="smoke:academics",
                system_prompt="Return one JSON object matching the schema. No prose.",
                user_prompt=f"Course: {args.course}. Give its name, typical duration in years, "
                f"and the national regulator for it in {settings.region}.",
                json_schema=schema,
                search_domains=domains.domains,
            )
        except Exception as exc:
            _emit(
                {
                    "status": "fail",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "raw": getattr(exc, "raw", "")[:600],
                    "endpoint": f"{settings.perplexity_base_url.rstrip('/')}/v1/agent",
                    "preset": settings.perplexity_preset,
                    "model": settings.perplexity_model or None,
                }
            )
            return 1

    _emit(
        {
            "status": "ok",
            "endpoint": f"{settings.perplexity_base_url.rstrip('/')}/v1/agent",
            "preset": settings.perplexity_preset,
            "model": settings.perplexity_model or None,
            "search_domains_sent": list(domains.domains),
            "data": response.data,
            "citations": response.citations,
            "search_results": len(response.search_results),
            "usage": response.usage,
        }
    )
    return 0


def cmd_retry(args: argparse.Namespace, settings: Settings) -> int:
    queue = load_review_queue(settings.review_dir, settings.artifacts_dir)
    if args.course_id:
        queue = [item for item in queue if item.course_id == args.course_id]
    if not queue:
        _emit({"status": "empty", "message": "nothing in the review queue", "review_dir": str(settings.review_dir)})
        return 0

    registry = DomainRegistry.load(settings.domains_path)
    plan = [
        {
            "course_id": i.course_id,
            "course_name": i.course_name,
            "chunks_to_rerun": i.flagged_chunks,
            "previous_attempts": i.attempts,
            "requests_if_no_retries": len(i.flagged_chunks),
        }
        for i in queue
    ]
    if args.dry_run:
        _emit({"status": "dry_run", "queued": len(queue), "plan": plan,
               "requests_if_no_retries": sum(len(i.flagged_chunks) for i in queue)})
        return 0

    root_schema = load_root_schema(settings.schema_path)
    rule_context = RuleContext(
        currency=settings.currency, allowed_domains=registry.allowlist(settings.search_domains)
    )

    results: list[dict[str, Any]] = []
    needs_api: list = []
    for item in queue:
        store = ArtifactStore(settings.artifacts_dir, item.course_id)
        document = store.load_course()
        if document is None:
            needs_api.append(item)
            continue
        report = validate_document(
            document, root_schema, rule_context, scope="document", course_id=item.course_id
        )
        if report.passed:
            store.save_validation(report.to_dict())
            store.save_run(
                {"course_id": item.course_id, "course_name": item.course_name,
                 "status": "validated", "flagged_chunks": [], "revalidated": True}
            )
            Path(settings.review_dir).joinpath(f"{item.course_id}.json").unlink(missing_ok=True)
            results.append(
                {
                    "course_id": item.course_id,
                    "course_name": item.course_name,
                    "was": item.flagged_chunks,
                    "now": "validated",
                    "how": "revalidated",
                    "requests": 0,
                }
            )
        else:
            needs_api.append(item)

    if args.revalidate_only:
        _emit(
            {
                "queued": len(queue),
                "cleared_free": len(results),
                "would_need_api": [i.course_id for i in needs_api],
                "requests": 0,
                "results": results,
            }
        )
        return 0

    if needs_api:
        settings.require_api_key()
        with PerplexityClient(settings) as client:
            for item in needs_api:
                if not item.flagged_chunks:
                    continue
                store = ArtifactStore(settings.artifacts_dir, item.course_id)
                result = generate_course(
                    course_id=item.course_id,
                    course_name=item.course_name,
                    client=client,
                    settings=settings,
                    store=store,
                    only_chunks=tuple(item.flagged_chunks),
                    discipline=item.discipline,
                )
                if result.publishable:
                    Path(settings.review_dir).joinpath(f"{item.course_id}.json").unlink(missing_ok=True)
                else:
                    _write_review(settings, result.to_dict(), item.course_id)
                results.append(
                    {
                        "course_id": item.course_id,
                        "course_name": item.course_name,
                        "was": item.flagged_chunks,
                        "now": result.status,
                        "how": "regenerated",
                        "still_flagged": [o.chunk_key for o in result.chunk_outcomes if not o.accepted],
                        "requests": sum(o.usage.get("requests", 0) for o in result.chunk_outcomes),
                    }
                )

    cleared = [r for r in results if r["now"] == "validated"]
    free = [r for r in cleared if r["how"] == "revalidated"]
    _emit(
        {
            "queued": len(queue),
            "cleared": len(cleared),
            "cleared_without_spending": len(free),
            "still_flagged": len(results) - len(cleared),
            "requests": sum(r["requests"] for r in results),
            "results": results,
        }
    )
    return 0 if len(cleared) == len(results) else 2


def _write_review(settings: Settings, payload: dict[str, Any], course_id: str) -> Path:
    return write_json(Path(settings.review_dir) / f"{course_id}.json", payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coursegen")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="run the chunked generation pipeline for one course")
    gen.add_argument("course")
    gen.add_argument("--course-id")
    gen.add_argument("--chunk", action="append", help="regenerate only these chunks; repeatable")
    gen.add_argument("--discipline", help="discipline key declared in config/domains.json")
    gen.set_defaults(handler=cmd_generate)

    val = sub.add_parser("validate", help="validate a saved course document")
    val.add_argument("path")
    val.add_argument("--out")
    val.set_defaults(handler=cmd_validate)

    mrg = sub.add_parser("merge", help="rebuild course.json from saved chunk artifacts")
    mrg.add_argument("course")
    mrg.add_argument("--course-id")
    mrg.set_defaults(handler=cmd_merge)

    sch = sub.add_parser("schema", help="print chunk definitions or one chunk's schema")
    sch.add_argument("--chunk", choices=sorted(CHUNKS_BY_KEY))
    sch.add_argument("--provider", action="store_true", help="apply the provider relaxation pass")
    sch.set_defaults(handler=cmd_schema)

    crs = sub.add_parser("courses", help="inspect the course list workbook")
    crs.add_argument("path")
    crs.add_argument("--list", action="store_true", help="emit course rows instead of a summary")
    crs.add_argument("--discipline")
    crs.add_argument("--limit", type=int)
    crs.set_defaults(handler=cmd_courses)

    smk = sub.add_parser("smoke", help="one cheap real call to verify API wiring")
    smk.add_argument("--course", default="B.Tech Computer Science & Engineering")
    smk.add_argument("--discipline", default="engineering-technology")
    smk.set_defaults(handler=cmd_smoke)

    plt = sub.add_parser("pilot", help="run a small stratified batch and report on it")
    plt.add_argument("path")
    plt.add_argument("--count", type=int, default=10)
    plt.add_argument("--discipline")
    plt.add_argument(
        "--include", action="append", help="course name to guarantee in the sample; repeatable"
    )
    plt.add_argument("--out")
    plt.add_argument("--dry-run", action="store_true", help="show the plan without spending anything")
    plt.set_defaults(handler=cmd_pilot)

    rty = sub.add_parser("retry", help="re-run only the flagged chunks of courses in the review queue")
    rty.add_argument("--course-id", help="retry a single course instead of the whole queue")
    rty.add_argument("--dry-run", action="store_true", help="show the plan without spending anything")
    rty.add_argument(
        "--revalidate-only",
        action="store_true",
        help="only re-check saved documents against current rules; never call the API",
    )
    rty.set_defaults(handler=cmd_retry)

    dom = sub.add_parser("domains", help="show the search domains each chunk will use")
    dom.add_argument("--discipline", help="resolve as this discipline")
    dom.set_defaults(handler=cmd_domains)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        settings = load_settings()
        return int(args.handler(args, settings))
    except ConfigError as exc:
        _emit({"status": "error", "error": "config", "message": str(exc)})
        return 3
    except CourseListError as exc:
        _emit({"status": "error", "error": "course_list", "message": str(exc)})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
