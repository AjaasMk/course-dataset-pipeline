import argparse
import json
from pathlib import Path

from src.facts import store as facts_store
from src.facts.models import Ranking, SourceRef, VerificationStatus
from src.institutions.nirf_institutions import extract_institutions
from src.retrieve import store as doc_store
from src.retrieve.models import DiscoveredDocument, MatchType
from src.retrieve.nirf import NIRFAdapter

DEFAULT_CATEGORIES = [
    "Overall", "University", "College", "Engineering", "Management",
    "Pharmacy", "Medical", "Dental", "Law", "Architecture", "Agriculture",
    "Research", "Innovation",
]


def _quote_row(institution_row: dict) -> str:
    parts = [institution_row["nirf_id"], institution_row["canonical_name"]]
    if institution_row.get("city"):
        parts += [institution_row["city"], institution_row["state"]]
    if institution_row.get("nirf_score") is not None:
        parts.append(str(institution_row["nirf_score"]))
    parts.append(str(institution_row["nirf_rank"]))
    return " | ".join(str(p) for p in parts if p is not None)


def migrate(
    categories: list[str],
    year: str = "2025",
    doc_db: Path = None,
    facts_db: Path = None,
) -> dict:
    adapter = NIRFAdapter()
    per_category: dict[str, int] = {}
    document_ids: dict[str, str] = {}

    found_year, category_urls = adapter.build_index()

    for category in categories:
        url = category_urls.get(category)
        if url is None:
            per_category[category] = 0
            continue

        # Reuse a document already recorded for this exact URL rather than
        # re-downloading; otherwise fetch it for real through the adapter so
        # every ranking has a genuine, hashed document to cite.
        existing = doc_store.get_document_by_url(url, db_path=doc_db)
        if existing is not None:
            record = existing
        else:
            document = DiscoveredDocument(
                document_url=url,
                document_title=f"NIRF {found_year} {category} Ranking",
                match_confidence=1.0,
                match_type=MatchType.EXACT,
                academic_year=found_year,
            )
            record = adapter.download(document)
            doc_store.insert_document(record, db_path=doc_db)

        document_ids[category] = record.document_id

        html = Path(record.local_path).read_text(encoding="utf-8")
        rows = extract_institutions(html, found_year, category)

        for row in rows:
            ranking = Ranking(
                institution_id=row.institution_id,
                ranking_body="NIRF",
                ranking_year=row.ranking_year,
                ranking_category=row.ranking_category,
                rank=row.nirf_rank,
                ranking_score=row.nirf_score,
            )
            ref = SourceRef(
                field_id="F075",
                document_id=record.document_id,
                quoted_evidence=_quote_row(row.model_dump()),
                verification_status=VerificationStatus.AI_CHECKED,
            )
            facts_store.record_ranking(ranking, refs=[ref], db_path=facts_db)

        per_category[category] = len(rows)

    return {"year": year, "per_category": per_category, "document_ids": document_ids}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", nargs="*", default=DEFAULT_CATEGORIES)
    parser.add_argument("--out", type=Path, default=Path("data/facts_migration_report.json"))
    args = parser.parse_args()

    report = migrate(args.categories)
    for category, n in report["per_category"].items():
        print(f"  {category:14} {n:4} rankings recorded")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
