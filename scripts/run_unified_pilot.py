"""Build client-schema course pages, one LLM call each.

Run: PYTHONPATH=. python scripts/run_unified_pilot.py [--limit N] [--dry-run]

One call per course produces the client's page tree directly, filled from
retrieved evidence where it exists and generated where it does not. Every
claimed citation is verified against the documents actually supplied before it
counts as sourced.

Idempotent: a course whose page already exists is skipped, so a partial or
interrupted run resumes without re-spending on work already done.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from src.courses.taxonomy import load_taxonomy
from src.extract.chunk_io import canonical_only, course_document_ids
from src.extract.unified_extraction import extract_course_page
from scripts.run_extraction_pilot import PILOT, load_chunks_for
from scripts.validate_client_schema import status_for, validate

OUT_DIR = Path("data/pages")
REPORT = Path("data/unified_pilot_report.json")


def run_one(course) -> dict:
    started = time.time()
    out_path = OUT_DIR / f"{course.course_id}.json"
    if out_path.exists():
        return {"course_id": course.course_id, "outcome": "skipped"}

    try:
        chunks, dropped = canonical_only(
            load_chunks_for(course_document_ids(course.course_id)))
        result = extract_course_page(chunks, course)

        # The client's own validation rules, run on our output rather than
        # assumed to pass. A page that scores below 90 is reported, not shipped.
        score, errors, _ = validate(result["page"]["course"])
        result["validation"] = {"score": score,
                                "status": status_for(score, errors),
                                "errors": errors[:10]}

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False),
                            encoding="utf-8")
        audit = result["audit"]
        return {"course_id": course.course_id, "outcome": "built",
                "chunks": len(chunks), "non_canonical_dropped": dropped,
                "fields": audit["fields_populated"],
                "sourced": audit["fields_sourced"],
                "generated": audit["fields_generated"],
                "citations_claimed": audit["claimed"],
                "citations_rejected": audit["rejected"],
                "score": score, "status": result["validation"]["status"],
                "seconds": round(time.time() - started, 1)}
    except Exception as exc:
        return {"course_id": course.course_id, "outcome": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:200],
                "seconds": round(time.time() - started, 1)}


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    courses = {c.course_id: c for c in load_taxonomy()}
    work = [courses[cid] for cid in PILOT if cid in courses]
    if args.limit:
        work = work[: args.limit]

    print(f"courses: {len(work)} | one LLM call each")
    if args.dry_run:
        for course in work:
            done = (OUT_DIR / f"{course.course_id}.json").exists()
            print(f"  {course.course_id:<46}{'skip (exists)' if done else 'would build'}")
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, c) for c in work]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result["outcome"] == "built":
                detail = (f"{result['fields']:>3} fields  "
                          f"{result['sourced']:>3} sourced  "
                          f"{result['generated']:>3} generated  "
                          f"score {result['score']:>3}  {result['status']}")
            else:
                detail = result.get("error", result["outcome"])[:70]
            print(f"[{len(results)}/{len(work)}] {result['outcome'][:7]:<8}"
                  f"{result['course_id'][:34]:<36}{detail}", flush=True)

    built = [r for r in results if r["outcome"] == "built"]
    report = {
        "courses": len(results),
        "built": len(built),
        "failed": sum(1 for r in results if r["outcome"] == "failed"),
        "ready": sum(1 for r in built if r["status"] == "READY"),
        "fields_total": sum(r["fields"] for r in built),
        "fields_sourced": sum(r["sourced"] for r in built),
        "fields_generated": sum(r["generated"] for r in built),
        "citations_claimed": sum(r["citations_claimed"] for r in built),
        "citations_rejected": sum(r["citations_rejected"] for r in built),
        "results": results,
    }
    REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print()
    if built:
        sourced_pct = report["fields_sourced"] / max(report["fields_total"], 1) * 100
        rejected_pct = (report["citations_rejected"]
                        / max(report["citations_claimed"], 1) * 100)
        print(f"built {report['built']}/{report['courses']} | "
              f"READY {report['ready']} | failed {report['failed']}")
        print(f"fields: {report['fields_total']} total, "
              f"{report['fields_sourced']} sourced ({sourced_pct:.1f}%), "
              f"{report['fields_generated']} generated")
        print(f"citations: {report['citations_claimed']} claimed, "
              f"{report['citations_rejected']} rejected ({rejected_pct:.1f}%)")
    print(f"report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
