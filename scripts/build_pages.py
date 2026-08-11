"""Assemble one complete page per course: every block filled, no gaps.

Run: PYTHONPATH=. python scripts/build_pages.py [--limit N] [--dry-run]

Order of preference per block, never varied:
  1. extracted facts, cited            -> provenance "sourced"
  2. generated because retrieval found nothing   -> "generated", no_source_found
  3. generated because nothing publishes it      -> "generated", no_atomic_source_exists
  4. derived from facts already held             -> "derived"

A block is never left empty and never silently filled -- every one carries its
provenance, so the admin view can tell the three apart even though a student
sees the same rendered section either way.

Idempotent: a course whose page already exists is skipped.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from src.courses.taxonomy import load_taxonomy
from src.extract.block_schemas import DERIVED_BLOCKS
from src.extract.fallback_generation import generate_block, generate_segment
from src.extract.segment_schemas import schema_for
from src.facts.generated import GenerationReason
from src.retrieve.models import EXPLANATORY_SEGMENTS

BLOCK_MAP = Path("docs/specs/page-block-map.json")
FACTS_DIR = Path("data/extracted_facts")
OUT_DIR = Path("data/pages")
REPORT = Path("data/page_build_report.json")

# Which extractor's output holds a segment's fields. Segments absent here have
# no fact model yet, so retrieval cannot fill them and they fall to generation.
SEGMENT_TO_EXTRACTOR = {
    "Course Identity": "Course",
    "Duration & Mode": "Course",
    "Eligibility": "Eligibility",
    "Curriculum": "Curriculum",
    "Specialisation": "Specialisation",
}

PILOT = json.loads(Path("data/pilot25_courses.json").read_text(encoding="utf-8")) if Path(
    "data/pilot25_courses.json"
).exists() else None


def course_name(course) -> str:
    return course.standard_course_name


def course_field(course) -> str:
    # The taxonomy carries `fields` as a list because four specialisations are
    # cross-listed under two sheets. The page shows one, so the first is the
    # primary association.
    return course.fields[0] if course.fields else ""


def load_blocks() -> list[dict]:
    return json.loads(BLOCK_MAP.read_text(encoding="utf-8"))["blocks"]


def extracted_fields(course_id: str, segment: str) -> dict:
    kind = SEGMENT_TO_EXTRACTOR.get(segment)
    if kind is None:
        return {}
    path = FACTS_DIR / f"{course_id}__{kind}.json"
    if not path.exists():
        return {}
    record = json.loads(path.read_text(encoding="utf-8"))
    skip = {"course_id", "curriculum_year", "eligibility_year", "record_id"}
    fields = {
        k: v
        for k, v in (record.get("fields") or {}).items()
        if k not in skip and v not in (None, "", [], {})
    }
    if not fields:
        return {}
    return {"fields": fields, "citations": record.get("citations") or []}


def segment_content(course, segment: str) -> dict:
    found = extracted_fields(course.course_id, segment)
    if found:
        return {
            "provenance": "sourced",
            "fields": found["fields"],
            "citations": found["citations"],
        }

    reason = (
        GenerationReason.NO_ATOMIC_SOURCE_EXISTS
        if segment in {s.value for s in EXPLANATORY_SEGMENTS}
        else GenerationReason.NO_SOURCE_FOUND
    )
    record = generate_segment(
        course_id=course.course_id,
        course_name=course_name(course),
        segment=segment,
        schema=schema_for(segment),
        field_of_study=course_field(course),
        reason=reason,
    )
    return {
        "provenance": "generated",
        "reason": record.reason.value,
        "generator_model": record.generator_model,
        "generated_at": record.generated_at,
        "fields": record.fields,
        "citations": [],
    }


def sibling_courses(course, limit: int = 4) -> dict:
    """Real alternatives from the taxonomy, for the comparison block.

    Supplied rather than left to the model: asked to name "similar courses" it
    will produce plausible ones that do not exist in this library, and the page
    would then link to nothing.
    """
    siblings = [
        course_name(c) for c in load_taxonomy()
        if course_field(c) == course_field(course) and c.course_id != course.course_id
    ]
    return {"this_course": course_name(course), "candidate_alternatives": siblings[:limit]}


def derived_content(course, block: str, page: dict) -> dict:
    if block == "breadcrumbs":
        value = {"path": ["Home", "Courses", course_field(course), course_name(course)]}
    elif block == "page_verification":
        cited = sum(
            len(b.get("citations") or []) for b in page.values() if isinstance(b, dict)
        )
        value = {
            "content_status": "Pilot",
            "reviewer": "Career Content Team",
            "citation_count": cited,
        }
    else:
        value = {}
    return {"provenance": "derived", "fields": value, "citations": []}


def build_one(course, blocks) -> dict:
    started = time.time()
    out_path = OUT_DIR / f"{course.course_id}.json"
    if out_path.exists():
        return {"course_id": course.course_id, "outcome": "skipped"}

    page: dict = {}
    counts = {"sourced": 0, "generated": 0, "derived": 0, "ui": 0}
    try:
        for block in blocks:
            name, producer = block["block"], block["producer"]
            if producer == "ui":
                counts["ui"] += 1
                continue
            if producer == "advisory":
                record = generate_block(
                    course_id=course.course_id,
                    course_name=course_name(course),
                    block=name,
                    field_of_study=course_field(course),
                    context=sibling_courses(course) if name == "compare" else None,
                )
                page[name] = {
                    "provenance": "generated",
                    "reason": record.reason.value,
                    "generator_model": record.generator_model,
                    "generated_at": record.generated_at,
                    "fields": record.fields,
                    "citations": [],
                }
                counts["generated"] += 1
                continue
            if producer == "derived" or name in DERIVED_BLOCKS:
                page[name] = derived_content(course, name, page)
                counts["derived"] += 1
                continue

            merged: dict = {"fields": {}, "citations": []}
            provenances = set()
            for segment in block["segments"]:
                part = segment_content(course, segment)
                provenances.add(part["provenance"])
                merged["fields"][segment] = part["fields"]
                merged["citations"].extend(part["citations"])
            provenance = (
                "sourced"
                if provenances == {"sourced"}
                else "generated"
                if provenances == {"generated"}
                else "partially_generated"
            )
            page[name] = {"provenance": provenance, **merged}
            counts["sourced" if provenance == "sourced" else "generated"] += 1

        empty = [n for n, b in page.items() if not b["fields"]]
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {"course_id": course.course_id, "course_name": course_name(course),
                 "field": course_field(course), "blocks": page},
                indent=1, ensure_ascii=False, default=str,
            ),
            encoding="utf-8",
        )
        return {
            "course_id": course.course_id, "outcome": "built",
            "blocks": len(page), **counts, "empty_blocks": empty,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "course_id": course.course_id, "outcome": "failed",
            "error": f"{type(exc).__name__}: {exc}"[:220],
            "seconds": round(time.time() - started, 1),
        }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    blocks = load_blocks()
    from scripts.run_extraction_pilot import PILOT as PILOT_IDS

    courses = {c.course_id: c for c in load_taxonomy()}
    work = [courses[cid] for cid in PILOT_IDS if cid in courses]
    if args.limit:
        work = work[: args.limit]

    fillable = [b for b in blocks if b["producer"] != "ui"]
    print(f"courses: {len(work)} | blocks per page: {len(fillable)} "
          f"(+{len(blocks) - len(fillable)} ui)")
    if args.dry_run:
        for block in blocks:
            print(f"  {block['producer']:<12} {block['block']}")
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(build_one, c, blocks) for c in work]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            detail = (
                f"{result.get('sourced', 0)} sourced, {result.get('generated', 0)} generated, "
                f"{result.get('derived', 0)} derived"
                if result["outcome"] == "built"
                else result.get("error", result["outcome"])[:70]
            )
            print(f"[{len(results)}/{len(work)}] {result['outcome'][:7]:<8} "
                  f"{result['course_id'][:36]:<38} {detail}", flush=True)

    built = [r for r in results if r["outcome"] == "built"]
    gaps = {r["course_id"]: r["empty_blocks"] for r in built if r["empty_blocks"]}
    report = {
        "courses": len(results),
        "built": len(built),
        "failed": sum(1 for r in results if r["outcome"] == "failed"),
        "blocks_per_page": len(fillable),
        "sourced": sum(r.get("sourced", 0) for r in built),
        "generated": sum(r.get("generated", 0) for r in built),
        "derived": sum(r.get("derived", 0) for r in built),
        "courses_with_gaps": gaps,
        "pass": bool(built) and not gaps and not any(
            r["outcome"] == "failed" for r in results
        ),
        "results": results,
    }
    REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print()
    print(f"built {report['built']}/{report['courses']} | sourced {report['sourced']} "
          f"| generated {report['generated']} | derived {report['derived']}")
    print(f"gaps: {len(gaps)} course(s) with an empty block")
    print(f"{'PASS' if report['pass'] else 'FAIL'} -> {REPORT}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
