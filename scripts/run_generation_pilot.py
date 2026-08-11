"""Generate content for every pilot-25 (course, segment) cell with no source.

Run: PYTHONPATH=. python scripts/run_generation_pilot.py [--limit N] [--dry-run]

Idempotent: a cell whose output already exists is skipped.
"""

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from src.courses.taxonomy import load_taxonomy
from src.extract.fallback_generation import generate_segment
from src.extract.segment_schemas import is_provisional, schema_for
from src.facts.generated import validate_generated
from src.retrieve.models import RETRIEVAL_SEGMENTS, Segment

OUT_DIR = Path("data/generated")
REPORT = Path("data/generation_pilot_report.json")

PILOT = [
    "mechanical_engineering", "computer_science_engineering", "artificial_intelligence_ai",
    "electrical_engineering", "civil_engineering", "chemical_engineering", "biotechnology",
    "robotics_engineering", "architecture_core", "animation_core_general",
    "game_design_core_mechanics", "film_production_core_general", "communication_core_general",
    "data_science", "machine_learning", "industrial_engineering", "agricultural_engineering",
    "agricultural_economics", "education_general_core", "pharmacy_core",
    "allopathic_medicine_surgery_core", "marketing",
    "supply_chain_management_logistics_business_track",
    "web_development_internet_technologies", "polymer_engineering",
]


def sourced_segments(db_path: str = "data/manifest.db"):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select i.course_id, i.segment, i.source_id from retrieval_intents i "
            "join intent_resolutions r on i.intent_id = r.intent_id "
            "join documents d on d.document_id = r.document_id "
            "where d.local_path is not null"
        ).fetchall()
    finally:
        conn.close()
    have = defaultdict(set)
    for course_id, segment, _ in rows:
        have[course_id].add(segment)
    return have


def attempted_sources(course_id: str, segment: str, db_path: str = "data/manifest.db"):
    conn = sqlite3.connect(db_path)
    try:
        return [
            s for (s,) in conn.execute(
                "select distinct source_id from retrieval_intents "
                "where course_id = ? and segment = ?",
                (course_id, segment),
            )
        ]
    finally:
        conn.close()


def run_one(course, segment):
    out_path = OUT_DIR / f"{course.course_id}__{segment.replace(' ', '_').replace('&', 'and')}.json"
    if out_path.exists():
        return {"course_id": course.course_id, "segment": segment, "outcome": "skipped"}
    started = time.time()
    try:
        record = generate_segment(
            course_id=course.course_id,
            course_name=course.standard_course_name,
            segment=segment,
            schema=schema_for(segment),
            field_of_study=course.fields[0] if course.fields else "",
            sources_attempted=attempted_sources(course.course_id, segment),
        )
        # Publication is allowed for generated content by the policy set in
        # src/facts/generated.py; validate_generated() is what enforces it, so
        # it runs after the flag is set rather than being trusted.
        record.publishable = True
        validate_generated(record)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(record.model_dump_json(indent=1), encoding="utf-8")
        return {
            "course_id": course.course_id,
            "segment": segment,
            "outcome": "generated",
            "fields": len([v for v in record.fields.values() if v]),
            "provisional_schema": is_provisional(segment),
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "course_id": course.course_id,
            "segment": segment,
            "outcome": "failed",
            "error": f"{type(exc).__name__}: {exc}"[:250],
        }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    courses = {c.course_id: c for c in load_taxonomy()}
    have = sourced_segments()
    order = [s.value for s in Segment if s in RETRIEVAL_SEGMENTS]

    gaps = [
        (courses[cid], seg)
        for cid in PILOT
        for seg in order
        if seg not in have[cid]
    ]
    if args.limit:
        gaps = gaps[: args.limit]

    print(f"cells to generate: {len(gaps)}")
    if args.dry_run:
        for course, segment in gaps:
            print(f"  {course.course_id:<44} {segment}")
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, c, s) for c, s in gaps]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            mark = "ok " if result["outcome"] == "generated" else result["outcome"][:3]
            extra = f"{result.get('fields', 0)} fields" if result["outcome"] == "generated" else result.get("error", "")[:70]
            print(f"[{len(results)}/{len(gaps)}] {mark} {result['course_id'][:34]:<36} {result['segment']:<24} {extra}", flush=True)

    REPORT.write_text(json.dumps(results, indent=1), encoding="utf-8")
    ok = [r for r in results if r["outcome"] == "generated"]
    bad = [r for r in results if r["outcome"] == "failed"]
    print()
    print(f"generated {len(ok)} | failed {len(bad)} | skipped {len(results) - len(ok) - len(bad)}")
    print(f"on a provisional schema: {sum(1 for r in ok if r.get('provisional_schema'))}")
    print(f"report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
