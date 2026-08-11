"""Check the page block map against the client's template and our segment taxonomy.

Run: PYTHONPATH=. python scripts/check_page_coverage.py [--json]

Three failure modes, all reported rather than assumed absent:
  1. a block rendered by the client's template with no entry in the map
  2. a mapped block naming a segment that is not in the taxonomy
  3. a taxonomy segment no block consumes (work with no destination)
"""

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from src.retrieve.models import EXPLANATORY_SEGMENTS, RETRIEVAL_SEGMENTS

TEMPLATE = Path("docs/specs by fmc/course-details-demo-template-v2.html")
MAP = Path("docs/specs/page-block-map.json")

# Blocks outside .main-column, which the heading sweep below cannot see.
NON_SECTION_BLOCKS = {"breadcrumbs", "hero", "hero.fit_panel", "quick_strip", "sidebar"}


def template_headings() -> list[str]:
    soup = BeautifulSoup(TEMPLATE.read_text(encoding="utf-8"), "html.parser")
    headings = []
    for section in soup.select(".main-column > section"):
        h2 = section.find("h2")
        strong = section.find("strong")
        headings.append((h2 or strong).get_text(strip=True))
    return headings


def normalise(heading: str) -> str:
    return heading.lower().replace("bsc psychology", "{course}").rstrip("?").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    block_map = json.loads(MAP.read_text(encoding="utf-8"))
    blocks = block_map["blocks"]
    taxonomy = {s.value for s in RETRIEVAL_SEGMENTS | EXPLANATORY_SEGMENTS}

    mapped_headings = {
        normalise(heading)
        for block in blocks
        for heading in (block.get("template_section"), block["heading"])
        if heading and block["block"] not in NON_SECTION_BLOCKS
    }
    unmapped_blocks = [h for h in template_headings() if normalise(h) not in mapped_headings]

    consumed: dict[str, list[str]] = {}
    unknown_segments = []
    for block in blocks:
        for segment in block["segments"]:
            if segment not in taxonomy:
                unknown_segments.append({"block": block["block"], "segment": segment})
            consumed.setdefault(segment, []).append(block["block"])

    unconsumed = sorted(taxonomy - set(consumed))

    by_producer: dict[str, int] = {}
    for block in blocks:
        by_producer[block["producer"]] = by_producer.get(block["producer"], 0) + 1

    report = {
        "template": str(TEMPLATE),
        "blocks_mapped": len(blocks),
        "template_sections": len(template_headings()),
        "blocks_by_producer": by_producer,
        "segments_in_taxonomy": len(taxonomy),
        "segments_consumed": len(consumed),
        "unmapped_template_blocks": unmapped_blocks,
        "unknown_segments": unknown_segments,
        "unconsumed_segments": unconsumed,
        "declared_unconsumed": sorted(block_map["unconsumed_segments"]),
        "pass": (
            not unmapped_blocks
            and not unknown_segments
            and unconsumed == sorted(block_map["unconsumed_segments"])
        ),
    }

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"blocks mapped        {report['blocks_mapped']} "
              f"({report['template_sections']} sections in the template)")
        for producer, count in sorted(by_producer.items()):
            print(f"  {producer:<12} {count}")
        print(f"segments consumed    {report['segments_consumed']} of {report['segments_in_taxonomy']}")
        for name in unconsumed:
            print(f"  unconsumed: {name}")
        for heading in unmapped_blocks:
            print(f"  UNMAPPED BLOCK: {heading}")
        for entry in unknown_segments:
            print(f"  UNKNOWN SEGMENT: {entry['segment']} in {entry['block']}")
        print(f"\n{'PASS' if report['pass'] else 'FAIL'}")

    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
