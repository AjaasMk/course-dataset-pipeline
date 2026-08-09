import argparse
import json
from pathlib import Path

from src.courses.taxonomy import load_taxonomy
from src.retrieve.aicte import AICTEAdapter
from src.retrieve.careers360 import Careers360Adapter
from src.retrieve.ncs import NCSAdapter
from src.retrieve.nirf import NIRFAdapter
from src.retrieve.notice_board import NoticeBoardAdapter
from src.retrieve.nqr import NQRAdapter
from src.retrieve.nsp import NSPAdapter
from src.retrieve.nta import NTAAdapter
from src.retrieve.planner import plan_course
from src.retrieve.models import SourceTier
from src.retrieve.registry import load_registry
from src.retrieve.render import RenderedFetcher
from src.retrieve.resolver import resolve_intents
from src.retrieve.ugc import UGCAdapter


def build_adapters() -> dict:
    render = RenderedFetcher().fetch
    adapters = [
        AICTEAdapter(),
        UGCAdapter(),
        NIRFAdapter(),
        NTAAdapter(),
        NCSAdapter(),
        NQRAdapter(),
        NSPAdapter(),
        Careers360Adapter(),
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
        NoticeBoardAdapter("NAAC", [SourceTier.A], "https://www.naac.gov.in/", fetch_html=render),
        NoticeBoardAdapter(
            "APPRENTICESHIP_INDIA", [SourceTier.A],
            "https://www.apprenticeshipindia.gov.in/", fetch_html=render,
        ),
        NoticeBoardAdapter("MOSPI_PLFS", [SourceTier.A], "https://www.mospi.gov.in/", fetch_html=render),
    ]
    return {adapter.source_id: adapter for adapter in adapters}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--courses", nargs="*", help="course names; default is a small sample")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("data/stage1_report.json"))
    args = parser.parse_args()

    registry = load_registry()
    taxonomy = load_taxonomy()

    if args.courses:
        wanted = [c for c in taxonomy if c.standard_course_name in args.courses]
    else:
        wanted = taxonomy[: args.limit]

    adapters = build_adapters()
    thresholds = {source_id: registry.threshold_for(source_id) for source_id in registry.sources}
    tiers = {source_id: s.tiers for source_id, s in registry.sources.items()}

    intents = []
    for course in wanted:
        intents.extend(plan_course(course, registry))

    print(f"{len(wanted)} courses -> {len(intents)} intents")
    report = resolve_intents(intents, adapters, thresholds=thresholds, tiers=tiers, db_path=args.db)

    print(
        f"\nresolved {report.resolved} "
        f"({report.resolved_authoritative} authoritative, {report.resolved_secondary} secondary) "
        f"| unresolved {report.unresolved} | errored {report.errored} "
        f"| documents {report.documents}"
    )
    print("\nsegment x source_tier:")
    for (segment, tier), counts in sorted(report.by_segment_tier.items()):
        rendered = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"  {segment:26} Tier {tier:2} {rendered}")

    if report.reasons:
        print("\nreasons:")
        for reason, count in sorted(report.reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5}  {reason}")

    payload = {
        "courses": [c.standard_course_name for c in wanted],
        "status": report.status,
        "totals": report.model_dump(exclude={"by_segment_tier"}),
        "by_segment_tier": [
            {"segment": s, "source_tier": t, **counts}
            for (s, t), counts in sorted(report.by_segment_tier.items())
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nreport -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
