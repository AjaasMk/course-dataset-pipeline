"""Extract cited fields from the pilot's chunks, for the segments that have a fact model.

Run: PYTHONPATH=. python scripts/run_extraction_pilot.py [--limit N] [--dry-run]

Covers the five segments with a real fact model in src/facts/. The other nine
have documents and chunks but no extraction model, field-id map or table, so
their cells cannot hold anything yet -- reported rather than silently skipped.

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
from src.extract.facts_extraction import (
    extract_course,
    extract_curriculum,
    extract_eligibility,
    extract_specialisation,
)
from src.extract.models import Chunk
from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
)
from src.facts.engine import check_citations
from src.retrieve.models import Segment

CHUNKS_DIR = Path("data/chunks_llm")
OUT_DIR = Path("data/extracted_facts")
REPORT = Path("data/extraction_pilot_report.json")
YEAR = "2025-26"
VALID_SEGMENT_IDS = {s.value for s in Segment} | {"unclassified"}

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

# extractor, the segments it covers, and the field-id map its citations use.
EXTRACTORS = {
    "Course": (extract_course, ["Course Identity", "Duration & Mode"], COURSE_FIELD_IDS),
    "Eligibility": (extract_eligibility, ["Eligibility"], ELIGIBILITY_FIELD_IDS),
    "Curriculum": (extract_curriculum, ["Curriculum"], CURRICULUM_FIELD_IDS),
    "Specialisation": (extract_specialisation, ["Specialisation"], SPECIALISATION_FIELD_IDS),
}


def course_documents(db_path: str = "data/manifest.db"):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select i.course_id, i.segment, d.document_id from retrieval_intents i "
            "join intent_resolutions r on i.intent_id = r.intent_id "
            "join documents d on d.document_id = r.document_id "
            "where d.local_path is not null"
        ).fetchall()
    finally:
        conn.close()
    out = defaultdict(lambda: defaultdict(set))
    for course_id, segment, document_id in rows:
        out[course_id][segment].add(document_id)
    return out


def load_chunks_for(document_ids) -> list[Chunk]:
    """Chunks in the shape facts_extraction expects.

    The LLM chunker's records carry more than the Chunk model does, so only the
    fields that model declares are passed through; the rest (offsets, scope,
    subsegment) stay in the chunk files for other consumers.
    """
    chunks: list[Chunk] = []
    index = 0
    for document_id in sorted(document_ids):
        path = CHUNKS_DIR / f"{document_id}.json"
        if not path.exists():
            continue
        for raw in json.loads(path.read_text(encoding="utf-8")):
            segment_id = raw.get("segment_id") or "unclassified"
            # Chunk files written before a segment was retired still carry its
            # label. Demote rather than crash -- the same treatment the chunker
            # gives a segment it does not recognise -- so retiring a segment
            # does not require rewriting every chunk file on disk.
            if segment_id not in VALID_SEGMENT_IDS:
                segment_id = "unclassified"
            chunks.append(
                Chunk(
                    chunk_id=index,
                    text=raw.get("text", ""),
                    source_document=document_id,
                    source_url=raw.get("document_id", document_id),
                    page_number=raw.get("page_number"),
                    heading_title=(raw.get("heading_path") or [None])[0],
                    token_count=max(1, len(raw.get("text", "").split())),
                    segment_id=segment_id,
                    segment_match_confidence=raw.get("segment_confidence", 0.0),
                )
            )
            index += 1
    return chunks


def run_one(course, kind):
    extractor, segments, field_ids = EXTRACTORS[kind]
    out_path = OUT_DIR / f"{course.course_id}__{kind}.json"
    if out_path.exists():
        return {"course_id": course.course_id, "kind": kind, "outcome": "skipped"}

    started = time.time()
    documents = set()
    for segment in segments:
        documents |= COURSE_DOCS[course.course_id].get(segment, set())
    if not documents:
        return {"course_id": course.course_id, "kind": kind, "outcome": "no_documents"}

    try:
        chunks = load_chunks_for(documents)
        if not chunks:
            return {"course_id": course.course_id, "kind": kind, "outcome": "no_chunks"}

        if kind == "Curriculum":
            record, refs = extractor(chunks, course, YEAR)
        elif kind == "Eligibility":
            record, refs = extractor(chunks, course, YEAR)
        elif kind == "Specialisation":
            pairs = extractor(chunks, course)
            record, refs = (pairs[0] if pairs else (None, []))
        else:
            record, refs = extractor(chunks, course)

        if record is None:
            return {"course_id": course.course_id, "kind": kind, "outcome": "nothing_extracted",
                    "seconds": round(time.time() - started, 1)}

        # The citation gate runs here too, not only inside record_*(): this
        # pilot writes JSON rather than to the facts store, and skipping the
        # check would let an uncited field look extracted.
        check_citations(record, field_ids, refs)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "course_id": course.course_id,
                    "kind": kind,
                    "segments": segments,
                    "fields": record.model_dump(exclude={"record_id", "recorded_at", "superseded_at"}),
                    "citations": [r.model_dump() for r in refs],
                },
                indent=1, ensure_ascii=False, default=str,
            ),
            encoding="utf-8",
        )
        populated = sum(
            1 for k in field_ids if getattr(record, k, None) not in (None, "", [], {})
        )
        return {
            "course_id": course.course_id, "kind": kind, "outcome": "extracted",
            "populated_fields": populated, "citations": len(refs),
            "chunks_used": len(chunks), "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "course_id": course.course_id, "kind": kind, "outcome": "failed",
            "error": f"{type(exc).__name__}: {exc}"[:220],
            "seconds": round(time.time() - started, 1),
        }


COURSE_DOCS = {}


def main() -> int:
    global COURSE_DOCS
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    COURSE_DOCS = course_documents()
    courses = {c.course_id: c for c in load_taxonomy()}

    work = []
    for course_id in PILOT:
        for kind, (_, segments, _) in EXTRACTORS.items():
            if any(segments_have := [s for s in segments if COURSE_DOCS[course_id].get(s)]):
                work.append((courses[course_id], kind))
    if args.limit:
        work = work[: args.limit]

    print(f"extraction units to run: {len(work)}")
    if args.dry_run:
        for course, kind in work:
            print(f"  {course.course_id:<46} {kind}")
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, c, k) for c, k in work]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            detail = (
                f"{result.get('populated_fields', 0)} fields, {result.get('citations', 0)} citations"
                if result["outcome"] == "extracted"
                else result.get("error", result["outcome"])[:80]
            )
            print(f"[{len(results)}/{len(work)}] {result['outcome'][:9]:<10} "
                  f"{result['course_id'][:34]:<36} {result['kind']:<14} {detail}", flush=True)

    REPORT.write_text(json.dumps(results, indent=1), encoding="utf-8")
    ok = [r for r in results if r["outcome"] == "extracted"]
    print()
    print(f"extracted {len(ok)} | failed {sum(1 for r in results if r['outcome'] == 'failed')} "
          f"| nothing found {sum(1 for r in results if r['outcome'] == 'nothing_extracted')}")
    if ok:
        print(f"fields populated: {sum(r['populated_fields'] for r in ok)} | "
              f"citations: {sum(r['citations'] for r in ok)}")
    print(f"report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
