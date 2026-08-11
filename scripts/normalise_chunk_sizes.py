"""Bring the stored chunk files into the retrieval size envelope.

Run: PYTHONPATH=. python scripts/normalise_chunk_sizes.py [--apply] [--limit N]

Offline and free: every chunk already carries char offsets and the source
documents are on disk, so this re-slices rather than re-chunking. Without
--apply it reports the before/after distribution and writes nothing.
"""

import argparse
import json
import sqlite3
import statistics as st
import sys
from pathlib import Path

from src.extract.chunk_sizing import (
    HARD_MAX_TOKENS,
    MIN_TOKENS,
    normalise,
    source_text_for,
    tokens_for,
)
from src.extract.llm_chunker import LLMChunk, write_chunks

CHUNKS_DIR = Path("data/chunks_llm")
REPORT = Path("data/chunk_sizing_report.json")


def source_paths(db_path: str = "data/manifest.db") -> dict[str, Path]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select document_id, local_path from documents where local_path is not null"
        ).fetchall()
    finally:
        conn.close()
    return {document_id: Path(path) for document_id, path in rows}


def summarise(sizes: list[int]) -> dict:
    if not sizes:
        return {}
    ordered = sorted(sizes)
    return {
        "chunks": len(sizes),
        "mean_tokens": round(st.mean(sizes)),
        "median_tokens": round(st.median(sizes)),
        "p10": ordered[int(len(ordered) * 0.10)],
        "p90": ordered[int(len(ordered) * 0.90)],
        "under_min": sum(1 for s in sizes if s < MIN_TOKENS),
        "over_hard_max": sum(1 for s in sizes if s > HARD_MAX_TOKENS),
        "in_band": sum(1 for s in sizes if MIN_TOKENS <= s <= HARD_MAX_TOKENS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    paths = source_paths()
    files = sorted(CHUNKS_DIR.glob("*.json"))
    if args.limit:
        files = files[: args.limit]

    before: list[int] = []
    after: list[int] = []
    failures = []
    verbatim_checked = verbatim_ok = 0

    for path in files:
        document_id = path.stem
        source = paths.get(document_id)
        if source is None or not source.exists():
            failures.append({"document_id": document_id, "error": "source file missing"})
            continue
        try:
            text = source_text_for(source)
            chunks = [LLMChunk(**raw) for raw in json.loads(path.read_text(encoding="utf-8"))]
        except Exception as exc:
            failures.append({"document_id": document_id, "error": f"{type(exc).__name__}: {exc}"})
            continue

        before.extend(tokens_for(c.text) for c in chunks)
        sized = normalise(chunks, text)
        after.extend(tokens_for(c.text) for c in sized)

        for chunk in sized:
            verbatim_checked += 1
            if chunk.text == text[chunk.char_start : chunk.char_end]:
                verbatim_ok += 1

        if args.apply:
            write_chunks(sized, path)

    report = {
        "documents": len(files),
        "failures": failures,
        "before": summarise(before),
        "after": summarise(after),
        "verbatim_checked": verbatim_checked,
        "verbatim_ok": verbatim_ok,
        "applied": args.apply,
        "pass": not failures and verbatim_checked == verbatim_ok,
    }
    REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    b, a = report["before"], report["after"]
    print(f"documents {len(files)} | failures {len(failures)}")
    print(f"{'':<16}{'before':>10}{'after':>10}")
    for key in ("chunks", "mean_tokens", "median_tokens", "p10", "p90",
                "under_min", "over_hard_max", "in_band"):
        print(f"{key:<16}{b.get(key, 0):>10,}{a.get(key, 0):>10,}")
    if b.get("chunks"):
        print(f"\nin-band share  {b['in_band']/b['chunks']*100:5.1f}% -> "
              f"{a['in_band']/a['chunks']*100:5.1f}%")
    print(f"verbatim slices {verbatim_ok}/{verbatim_checked}")
    print(f"{'APPLIED' if args.apply else 'DRY RUN (use --apply to write)'} -> {REPORT}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
