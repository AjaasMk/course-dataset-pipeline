"""Real diagnostic sampling of below-threshold retrieval failures.

Not part of the production pipeline -- built to answer "why does most of
Stage 1 land below_threshold" with real per-candidate evidence, not
assumptions (see CLAUDE.md's below_threshold root-cause section). Samples
courses across ALL 30 taxonomy fields (not just the 13 with a Regulator Map
entry, since 18 of 30 fall back to general_university_degrees), plans
intents fresh with the current planner, and calls each adapter's resolve()
live to capture the actual best candidate + score per intent -- info the
production pipeline doesn't persist for rejected candidates. Re-run after
any planner/adapter change (same random seed -> same 90-course sample) to
get a real before/after comparison, not a guess.

Run: PYTHONPATH=. python scripts/diagnose_below_threshold.py
"""
import json
import random
from collections import Counter, defaultdict

from src.courses.taxonomy import load_taxonomy
from src.retrieve.planner import plan_course
from src.retrieve.registry import load_registry
from src.retrieve.aicte import AICTEAdapter
from src.retrieve.careers360 import Careers360Adapter
from src.retrieve.collegedunia import CollegeDuniaAdapter
from src.retrieve.ncs import NCSAdapter
from src.retrieve.nirf import NIRFAdapter
from src.retrieve.notice_board import NoticeBoardAdapter
from src.retrieve.nqr import NQRAdapter
from src.retrieve.nsp import NSPAdapter
from src.retrieve.nta import NTAAdapter
from src.retrieve.models import SourceTier
from src.retrieve.ugc import UGCAdapter

random.seed(42)


def build_adapters():
    adapters = [
        AICTEAdapter(), UGCAdapter(), NIRFAdapter(), NTAAdapter(), NCSAdapter(),
        NQRAdapter(), NSPAdapter(), Careers360Adapter(), CollegeDuniaAdapter(),
        NoticeBoardAdapter("CUET", [SourceTier.A], "https://cuet.nta.nic.in/"),
        NoticeBoardAdapter("JOSAA", [SourceTier.A], "https://josaa.nic.in/"),
        NoticeBoardAdapter("CSAB", [SourceTier.A], "https://csab.nic.in/"),
        NoticeBoardAdapter("NMC", [SourceTier.A], "https://www.nmc.org.in/"),
        NoticeBoardAdapter("DCI", [SourceTier.A], "https://dciindia.gov.in/"),
        NoticeBoardAdapter("INC", [SourceTier.A], "https://www.indiannursingcouncil.org/"),
        NoticeBoardAdapter("PCI", [SourceTier.A], "https://www.pci.nic.in/"),
        NoticeBoardAdapter("COA", [SourceTier.A], "https://www.coa.gov.in/"),
        NoticeBoardAdapter("RCI", [SourceTier.A], "https://rehabcouncil.nic.in/"),
        NoticeBoardAdapter("UGC_DEB", [SourceTier.A], "https://deb.ugc.ac.in/"),
        NoticeBoardAdapter("CEE_KERALA", [SourceTier.A], "https://cee.kerala.gov.in/"),
    ]
    return {a.source_id: a for a in adapters}


def main():
    registry = load_registry()
    taxonomy = load_taxonomy()

    by_field = defaultdict(list)
    for c in taxonomy:
        for f in c.fields:
            by_field[f].append(c)

    sample = []
    for field, courses in by_field.items():
        sample.extend(random.sample(courses, min(3, len(courses))))
    print(f"sampled {len(sample)} courses across {len(by_field)} taxonomy fields")

    adapters = build_adapters()
    thresholds = {sid: registry.threshold_for(sid) for sid in registry.sources}

    results = []
    for course in sample:
        intents = plan_course(course, registry)
        for intent in intents:
            adapter = adapters.get(intent.source_id)
            if adapter is None or not adapter.supports(intent):
                results.append({
                    "course": course.standard_course_name,
                    "field": course.fields[0] if course.fields else None,
                    "segment": intent.segment.value, "source_id": intent.source_id,
                    "status": "no_adapter", "best_score": None, "best_title": None,
                    "query_terms": intent.query_terms,
                })
                continue
            try:
                discovered = adapter.resolve(intent)
            except Exception as exc:
                results.append({
                    "course": course.standard_course_name,
                    "field": course.fields[0] if course.fields else None,
                    "segment": intent.segment.value, "source_id": intent.source_id,
                    "status": f"error:{type(exc).__name__}", "best_score": None,
                    "best_title": None, "query_terms": intent.query_terms,
                })
                continue
            threshold = thresholds.get(intent.source_id, 0.80)
            best = max(discovered, key=lambda d: d.match_confidence, default=None)
            status = (
                "nothing_discovered" if best is None
                else ("resolved" if best.match_confidence >= threshold else "below_threshold")
            )
            results.append({
                "course": course.standard_course_name,
                "field": course.fields[0] if course.fields else None,
                "segment": intent.segment.value, "source_id": intent.source_id, "status": status,
                "best_score": None if best is None else round(best.match_confidence, 3),
                "best_title": None if best is None else best.document_title,
                "query_terms": intent.query_terms,
            })

    with open("data/diagnostic_below_threshold.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    status_counts = Counter(r["status"] for r in results)
    print("\ntotal intents sampled:", len(results))
    for status, n in status_counts.most_common():
        print(f"  {n:5}  {status}")

    print("\nbelow_threshold by (segment, source_id):")
    bt_by_seg_source = Counter(
        (r["segment"], r["source_id"]) for r in results if r["status"] == "below_threshold"
    )
    for (seg, src), n in bt_by_seg_source.most_common(25):
        print(f"  {n:4}  {seg:26} {src}")

    print("\nbelow_threshold score distribution:")
    scores = [r["best_score"] for r in results if r["status"] == "below_threshold"]
    bands = Counter()
    for s in scores:
        if s >= 0.65:
            bands["near_miss (0.65-0.79)"] += 1
        elif s >= 0.40:
            bands["moderate (0.40-0.64)"] += 1
        else:
            bands["low (<0.40)"] += 1
    for band, n in bands.most_common():
        print(f"  {n:5}  {band}")

    print("\nfull results written to data/diagnostic_below_threshold.json")


if __name__ == "__main__":
    main()
