"""Emit the extraction schema, checked against the client's Data Fields sheet.

Run: PYTHONPATH=. python scripts/dump_extraction_schema.py [--json]

Written from the live Pydantic models and field-ID maps, not maintained by
hand, so it cannot drift from what is actually sent to the model. Every field
is reconciled against the workbook and any disagreement is reported rather than
smoothed over:

  matched      our field name and F-number agree with the client's sheet
  unmapped     the client defines it; we have no field for it
  extra        we have a field the client's sheet does not define
  id_mismatch  same name, different F-number

Writes docs/specs/extraction-schema.json.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

from src.extract import facts_extraction as fe
from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
    Course,
    Curriculum,
    EligibilityRule,
    Specialisation,
)
from src.facts.models import Ranking
from src.facts.segment_facts import SEGMENT_FACTS

WORKBOOK = Path("docs/specs by fmc/indian_course_library_ai_sources_rag.xlsx")
OUT = Path("docs/specs/extraction-schema.json")

RANKING_FIELD_IDS = {
    "ranking_body": "F072",
    "ranking_year": "F073",
    "ranking_category": "F074",
    "rank": "F075",
    "rank_band": "F076",
    "ranking_score": "F077",
    "naac_status": "F078",
    "nba_programme_status": "F079",
}

# Keys the pipeline sets itself -- identity, versioning, bookkeeping. They are
# never extracted, so they carry no citation and are excluded from the gate.
NON_EXTRACTED = {
    "record_id", "course_id", "recorded_at", "superseded_at",
    "curriculum_year", "eligibility_year", "institution_key",
}

# Which extractor is wired today. A model without one can hold values but has
# nothing writing into it yet.
EXTRACTORS = {
    "Course Identity": "extract_course",
    "Duration & Mode": "extract_course",
    "Eligibility": "extract_eligibility",
    "Curriculum": "extract_curriculum",
    "Specialisation": "extract_specialisation",
}

MODELS = {
    "Course Identity": (Course, COURSE_FIELD_IDS),
    "Duration & Mode": (Course, COURSE_FIELD_IDS),
    "Eligibility": (EligibilityRule, ELIGIBILITY_FIELD_IDS),
    "Curriculum": (Curriculum, CURRICULUM_FIELD_IDS),
    "Specialisation": (Specialisation, SPECIALISATION_FIELD_IDS),
    "Ranking & Accreditation": (Ranking, RANKING_FIELD_IDS),
    **SEGMENT_FACTS,
}


def workbook_fields() -> dict[str, list[dict]]:
    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    rows = list(wb["Data Fields"].iter_rows(values_only=True))
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows[1:]:
        cells = [str(c).strip() if c is not None else "" for c in row[:5]]
        field_id, segment, name, description, data_type = cells
        if field_id.startswith("F"):
            out[segment].append(
                {"field_id": field_id, "name": name, "type": data_type,
                 "description": description}
            )
    return out


def type_of(model, name: str) -> str:
    info = model.model_fields.get(name)
    if info is None:
        return "-"
    text = str(info.annotation)
    for long, short in (("typing.Optional[str]", "str?"), ("typing.Optional[int]", "int?"),
                        ("typing.Optional[bool]", "bool?"), ("typing.Optional[float]", "float?"),
                        ("list[str]", "list[str]"), ("<class 'str'>", "str"),
                        ("<class 'int'>", "int")):
        text = text.replace(long, short)
    return text.replace("typing.", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    client = workbook_fields()
    segments = {}
    issues = []

    for segment, (model, field_ids) in MODELS.items():
        defined = {f["field_id"]: f for f in client.get(segment, [])}
        by_name = {f["name"]: f for f in client.get(segment, [])}

        fields = []
        for name, field_id in field_ids.items():
            entry = {
                "field_id": field_id,
                "name": name,
                "type": type_of(model, name),
                "cited": True,
                "status": "matched",
            }
            if name in by_name and by_name[name]["field_id"] != field_id:
                entry["status"] = "id_mismatch"
                entry["client_field_id"] = by_name[name]["field_id"]
                issues.append({"segment": segment, **entry})
            elif field_id not in defined:
                entry["status"] = "extra"
                issues.append({"segment": segment, **entry})
            else:
                entry["description"] = defined[field_id]["description"]
            fields.append(entry)

        for name in model.model_fields:
            if name in field_ids or name in NON_EXTRACTED:
                continue
            fields.append({"field_id": None, "name": name, "type": type_of(model, name),
                           "cited": False, "status": "ungated"})

        mapped = set(field_ids.values())
        for field_id, entry in defined.items():
            if field_id not in mapped:
                fields.append({**entry, "cited": False, "status": "unmapped"})
                issues.append({"segment": segment, **entry, "status": "unmapped"})

        segments[segment] = {
            "model": model.__name__,
            "extractor": EXTRACTORS.get(segment),
            "client_fields": len(defined),
            "mapped_fields": len(field_ids),
            "fields": sorted(fields, key=lambda f: f["field_id"] or "zzz"),
        }

    report = {
        "source_of_truth": str(WORKBOOK),
        "note": "generated from the live models by scripts/dump_extraction_schema.py",
        "segments": segments,
        "issues": issues,
        "totals": {
            "segments_with_a_model": len(segments),
            "client_fields_covered": sum(s["mapped_fields"] for s in segments.values()),
            "client_fields_defined": sum(len(v) for v in client.values()),
            "segments_with_an_extractor": sum(1 for s in segments.values() if s["extractor"]),
        },
        "pass": not issues,
    }
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0 if report["pass"] else 1

    for segment, entry in segments.items():
        wired = entry["extractor"] or "-- no extractor wired --"
        print(f"{segment}  [{entry['model']}]  {wired}")
        for field in entry["fields"]:
            mark = {"matched": " ", "unmapped": "!", "extra": "+",
                    "id_mismatch": "?", "ungated": "."}[field["status"]]
            print(f"  {mark} {field['field_id'] or '····':<6}{field['name']:<32}"
                  f"{field.get('type', '-'):<14}{'cited' if field['cited'] else ''}")
        print()

    totals = report["totals"]
    print(f"legend:  (blank) matched   ! client field we do not model   "
          f"+ ours only   ? id mismatch   . not citation-gated")
    print(f"\nsegments with a fact model      {totals['segments_with_a_model']}")
    print(f"segments with an extractor      {totals['segments_with_an_extractor']}")
    print(f"client fields covered           {totals['client_fields_covered']} "
          f"of {totals['client_fields_defined']}")
    print(f"issues                          {len(issues)}")
    print(f"\n{'PASS' if report['pass'] else 'FAIL'} -> {OUT}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
