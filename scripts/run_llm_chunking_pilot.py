"""Chunk the 25-course pilot's documents with the LLM chunker.

Run: PYTHONPATH=. python scripts/run_llm_chunking_pilot.py [--limit N] [--provider deepseek]

Idempotent: a document whose output already exists is skipped, so a partial run
can be resumed without re-spending on work already done.
"""

import argparse
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from src.extract.llm_chunker import chunk_document, write_chunks

OUT_DIR = Path("data/chunks_llm")
PILOT_FILE = Path("data/pilot25_documents.json")
REPORT = Path("data/llm_chunking_pilot_report.json")


def targets(db_path: str = "data/manifest.db"):
    conn = sqlite3.connect(db_path)
    try:
        rows = {
            d: (s, p)
            for d, s, p in conn.execute(
                "select document_id, source_id, local_path from documents"
            )
        }
    finally:
        conn.close()
    wanted = json.load(open(PILOT_FILE, encoding="utf-8"))
    out = []
    for document_id in wanted:
        source_id, path = rows.get(document_id, (None, None))
        if path and Path(path).exists():
            out.append((document_id, source_id, Path(path)))
    return out


def run_one(document_id, source_id, path, provider):
    started = time.time()
    out_path = OUT_DIR / f"{document_id}.json"
    if out_path.exists():
        return {"document_id": document_id, "source_id": source_id, "outcome": "skipped"}
    try:
        chunks = chunk_document(path, document_id, provider=provider)
        write_chunks(chunks, out_path)
        segments = sorted({str(c.segment_id) for c in chunks})
        return {
            "document_id": document_id,
            "source_id": source_id,
            "outcome": "chunked",
            "chunks": len(chunks),
            "segments": segments,
            "unclassified": sum(1 for c in chunks if c.segment_id == "unclassified"),
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "document_id": document_id,
            "source_id": source_id,
            "outcome": "failed",
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "seconds": round(time.time() - started, 1),
        }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work = targets()
    if args.limit:
        work = work[: args.limit]
    print(f"documents to process: {len(work)} (provider={args.provider}, workers={args.workers})", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_one, d, s, p, args.provider): d for d, s, p in work
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done = len(results)
            if result["outcome"] == "chunked":
                print(
                    f"[{done}/{len(work)}] {result['source_id']:<14} {result['chunks']:>4} chunks "
                    f"({result['unclassified']} unclassified) {result['seconds']}s",
                    flush=True,
                )
            elif result["outcome"] == "failed":
                print(f"[{done}/{len(work)}] {result['source_id']:<14} FAILED {result['error'][:90]}", flush=True)

    REPORT.write_text(json.dumps(results, indent=1), encoding="utf-8")
    ok = [r for r in results if r["outcome"] == "chunked"]
    bad = [r for r in results if r["outcome"] == "failed"]
    skipped = [r for r in results if r["outcome"] == "skipped"]
    print()
    print(f"chunked {len(ok)} | failed {len(bad)} | skipped {len(skipped)}")
    if ok:
        total = sum(r["chunks"] for r in ok)
        unc = sum(r["unclassified"] for r in ok)
        print(f"total chunks {total} | unclassified {unc} ({100 * unc / total:.1f}%)")
    print(f"report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
