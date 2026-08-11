"""Offline evaluation of the retrieval layer. No API calls, no credit spent.

Run: PYTHONPATH=. python scripts/eval_chunk_retrieval.py [--json] [--segment Curriculum]

Ground truth is real, not synthetic: the citations in data/extracted_facts/ were
produced by Sonnet when it could see every chunk, so a chunk containing a
citation's quoted evidence is a chunk the extraction demonstrably needed. A
retrieval stage that drops one would have cost a real field.

Matching is whitespace-normalised. The model's quoted_evidence collapses runs of
whitespace that the PDF's text layer contains, so a byte-exact search finds only
84% of citations even in chunks that genuinely hold them. Normalising is about
identifying the right chunk, and does not weaken the separate byte-identical
guarantee that citation VALIDATION relies on.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from src.extract import facts_extraction as fe
from src.extract.bm25 import BM25
from src.extract.segment_queries import query_for
from src.retrieve.models import Segment
from scripts.run_extraction_pilot import PILOT, course_documents, load_chunks_for

FACTS_DIR = Path("data/extracted_facts")
REPORT = Path("data/retrieval_eval_report.json")
CUTS = [5, 10, 20, 30, 50]
FUSION_TOP_K = 30
STAGES = ["bm25", "vector", "fusion", "rerank"]
RECALL_FLOOR = 0.60

SEGMENTS = {
    "Curriculum": ("Curriculum", [Segment.CURRICULUM]),
    "Eligibility": ("Eligibility", [Segment.ELIGIBILITY]),
    "Course": ("Course Identity", [Segment.COURSE_IDENTITY, Segment.DURATION_MODE]),
    "Specialisation": ("Specialisation", [Segment.SPECIALISATION]),
}

_WS = re.compile(r"\s+")


def flat(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip().lower()


def gold_for(chunks, citations) -> tuple[dict[int, set[str]], list[dict]]:
    """Chunk index -> the field_ids whose evidence it holds, plus unlocatable ones."""
    flattened = [flat(c.text) for c in chunks]
    gold: dict[int, set[str]] = defaultdict(set)
    missing = []
    for citation in citations:
        quote = flat(citation.get("quoted_evidence"))
        if not quote:
            continue
        probe = quote[:80]
        hit = next((i for i, body in enumerate(flattened) if probe in body), None)
        if hit is None:
            missing.append({"field_id": citation.get("field_id"), "quote": quote[:60]})
            continue
        gold[hit].add(citation.get("field_id") or "?")
    return gold, missing


def evaluate(kind: str, docs) -> list[dict]:
    segment_name, segment_enums = SEGMENTS[kind]
    query = query_for(segment_name)
    results = []

    for course_id in PILOT:
        path = FACTS_DIR / f"{course_id}__{kind}.json"
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        citations = record.get("citations") or []

        document_ids: set = set()
        for enum in segment_enums:
            document_ids |= docs[course_id].get(enum.value, set())
        chunks = fe._chunks_for_segments(load_chunks_for(document_ids), segment_enums)

        if not chunks:
            results.append({"course_id": course_id, "outcome": "no_chunks",
                            "citations": len(citations)})
            continue
        if not citations:
            results.append({"course_id": course_id, "outcome": "no_citations",
                            "chunks": len(chunks)})
            continue

        gold, missing = gold_for(chunks, citations)
        if not gold:
            results.append({"course_id": course_id, "outcome": "gold_unlocatable",
                            "chunks": len(chunks), "citations": len(citations)})
            continue

        texts = [c.text for c in chunks]
        fields = {f for ids in gold.values() for f in ids}
        stages = _rank_stages(query, texts)

        row = {
            "course_id": course_id,
            "outcome": "evaluated",
            "chunks": len(chunks),
            "gold_chunks": len(gold),
            "fields_with_evidence": len(fields),
            "citations_unlocatable": len(missing),
        }
        for stage, ranked in stages.items():
            for cut in CUTS:
                top = set(ranked[:cut])
                row[f"{stage}/recall@{cut}"] = round(len(set(gold) & top) / len(gold), 3)
                covered = {f for i in (set(gold) & top) for f in gold[i]}
                row[f"{stage}/field_coverage@{cut}"] = round(len(covered) / len(fields), 3)
            row[f"{stage}/all_gold_in_top5"] = row[f"{stage}/recall@5"] == 1.0
        results.append(row)
    return results


def _rank_stages(query: str, texts: list[str]) -> dict[str, list[int]]:
    """Each stage's ordering, so the harness reports a delta per stage.

    The reranker only ever sees the fused top-30, which is what makes it
    affordable; its ranking is reported padded with the rest of the fusion order
    so recall at wider cuts stays comparable across stages rather than being
    truncated by the pipeline's own funnel.
    """
    import hashlib

    from src.extract.embeddings import cosine_rank, embed
    from src.extract.reranker import reciprocal_rank_fusion, rerank

    # Hashed from the text rather than read off the chunk: the extraction-side
    # Chunk model carries no content_hash, and the cache key means "this exact
    # text" either way, so deriving it keeps the cache usable from both models.
    hashes = [hashlib.sha256(t.encode("utf-8")).hexdigest()[:16] for t in texts]
    bm25 = [i for i, _ in BM25(texts).rank(query)]
    vector = [i for i, _ in cosine_rank(query, embed(texts, hashes))]
    fused = reciprocal_rank_fusion([bm25, vector])

    head = fused[:FUSION_TOP_K]
    reranked = [head[i] for i, _ in rerank(query, [texts[i] for i in head])]
    return {
        "bm25": bm25,
        "vector": vector,
        "fusion": fused,
        "rerank": reranked + [i for i in fused if i not in set(head)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--segment", default=None, choices=sorted(SEGMENTS))
    args = parser.parse_args()

    docs = course_documents()
    kinds = [args.segment] if args.segment else sorted(SEGMENTS)
    per_segment = {kind: evaluate(kind, docs) for kind in kinds}

    summary = {}
    for kind, rows in per_segment.items():
        scored = [r for r in rows if r["outcome"] == "evaluated"]
        entry = {
            "courses": len(rows),
            "evaluated": len(scored),
            "no_chunks": sum(1 for r in rows if r["outcome"] == "no_chunks"),
            "no_citations": sum(1 for r in rows if r["outcome"] == "no_citations"),
            "gold_unlocatable": sum(1 for r in rows if r["outcome"] == "gold_unlocatable"),
            "citations_unlocatable": sum(r.get("citations_unlocatable", 0) for r in scored),
        }
        for stage in STAGES:
            for cut in CUTS:
                if scored:
                    entry[f"{stage}/recall@{cut}"] = round(
                        sum(r[f"{stage}/recall@{cut}"] for r in scored) / len(scored), 3)
                    entry[f"{stage}/field_coverage@{cut}"] = round(
                        sum(r[f"{stage}/field_coverage@{cut}"] for r in scored) / len(scored), 3)
            entry[f"{stage}/all_gold_in_top5"] = sum(
                1 for r in scored if r.get(f"{stage}/all_gold_in_top5"))
        summary[kind] = entry

    curriculum = summary.get("Curriculum", {})
    report = {
        "stages": STAGES,
        "note": "compression stage not yet built",
        "recall_floor": RECALL_FLOOR,
        "summary": summary,
        "per_course": per_segment,
        "pass": curriculum.get("rerank/recall@5", 0) >= RECALL_FLOOR,
    }
    REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    if args.json:
        print(json.dumps(report["summary"], indent=1))
        return 0 if report["pass"] else 1

    print("compression stage not yet built\n")
    for kind, entry in summary.items():
        gold = sum(r.get("gold_chunks", 0) for r in per_segment[kind]
                   if r["outcome"] == "evaluated")
        print(f"{kind}  --  {entry['evaluated']} courses, {gold} gold chunks")
        header = f"  {'stage':<10}"
        for cut in CUTS:
            header += f"{'R@' + str(cut):>8}"
        header += f"{'FC@5':>8}{'FC@10':>8}{'all@5':>7}"
        print(header)
        for stage in STAGES:
            line = f"  {stage:<10}"
            for cut in CUTS:
                line += f"{entry.get(f'{stage}/recall@{cut}', 0):>8.3f}"
            line += (f"{entry.get(f'{stage}/field_coverage@5', 0):>8.3f}"
                     f"{entry.get(f'{stage}/field_coverage@10', 0):>8.3f}"
                     f"{entry.get(f'{stage}/all_gold_in_top5', 0):>7}")
            print(line)
        print()

    print("\nretrieval failures / no-source cases")
    for kind, entry in summary.items():
        print(f"  {kind:<16}no_chunks {entry['no_chunks']:>3} | no_citations "
              f"{entry['no_citations']:>3} | gold_unlocatable {entry['gold_unlocatable']:>3}"
              f" | citations unlocatable {entry['citations_unlocatable']:>3}")

    print(f"\nrecall@5 floor {RECALL_FLOOR} -> {'PASS' if report['pass'] else 'FAIL'}")
    print(f"report -> {REPORT}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
