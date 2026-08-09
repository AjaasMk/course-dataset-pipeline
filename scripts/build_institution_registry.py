import argparse
import json
import time
from pathlib import Path

import requests

from src.institutions import store
from src.institutions.models import InstitutionAlias
from src.institutions.nirf_institutions import SOURCE_ID, extract_institutions
from src.retrieve.probe import BROWSER_HEADERS

RANKING_URL = "https://www.nirfindia.org/Rankings/{year}/{category}Ranking.html"
DEFAULT_YEAR = "2025"
DEFAULT_CATEGORIES = [
    "Overall",
    "University",
    "College",
    "Engineering",
    "Management",
    "Pharmacy",
    "Medical",
    "Dental",
    "Law",
    "Architecture",
    "Agriculture",
    "Research",
    "Innovation",
]
REQUEST_TIMEOUT = 45
DELAY_SECONDS = 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", default=DEFAULT_YEAR)
    parser.add_argument("--categories", nargs="*", default=DEFAULT_CATEGORIES)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("data/institution_registry_report.json"))
    args = parser.parse_args()

    per_category: dict[str, int] = {}
    failures: dict[str, str] = {}
    rows = 0

    for n, category in enumerate(args.categories):
        url = RANKING_URL.format(year=args.year, category=category)
        try:
            response = requests.get(url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            failures[category] = type(exc).__name__
            print(f"  {category:14} FAILED {type(exc).__name__}")
            continue

        institutions = extract_institutions(response.text, args.year, category)
        for institution in institutions:
            store.upsert_institution(institution, db_path=args.db)
            store.add_alias(
                InstitutionAlias(
                    institution_id=institution.institution_id,
                    observed_name=institution.canonical_name,
                    source_id=SOURCE_ID,
                ),
                db_path=args.db,
            )

        rows += len(institutions)
        per_category[category] = len(institutions)
        print(f"  {category:14} {len(institutions):4} ranked")

        if n < len(args.categories) - 1:
            time.sleep(DELAY_SECONDS)

    total = store.count_institutions(db_path=args.db)
    payload = {
        "year": args.year,
        "ranking_rows": rows,
        "distinct_institutions": total,
        "per_category": per_category,
        "failed_categories": failures,
        "status": "pass" if total > 0 and not failures else "partial",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{rows} ranking rows -> {total} distinct institutions")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
