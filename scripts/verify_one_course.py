"""Build one course's JSON and HTML from evidence alone. No API calls.

Run: PYTHONPATH=. python scripts/verify_one_course.py mechanical_engineering

Every value here was quoted from a retrieved chunk by hand during the manual
RAG verification and is carried with its document, page, chunk and segment, so
the page can be checked line by line against the source. Nothing is generated:
a field with no evidence renders as "not established", which is what the page
honestly looks like before the generation stage runs.
"""

import html
import json
import sys
from pathlib import Path

from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
)
from src.facts.models import RANKING_FIELD_IDS
from src.facts.segment_facts import SEGMENT_FACTS

OUT = Path("data/verification")
DOC = "DOC-7e1e842bc9f96211"

# field -> (value, page, chunk_id, segment_id, quoted evidence, confidence)
EVIDENCE = {
    "regulating_body": (
        "All India Council for Technical Education", 10, 5, "Curriculum",
        "All India Council for Technical Education67PREFACE", "medium"),
    "credit_count": (
        160, 10, 5, "Curriculum",
        "readjustment of courses within the overall 160 credits", "high"),
    "core_subjects": (
        # Names only. The PCC ME 2xx codes in the source are AICTE's model
        # numbering; every university renumbers, so the code is not a property
        # of the course and publishing it reads as institution-specific.
        ["Heat Transfer & Thermal Machines",
         "Fluid Mechanics & Hydraulic Machines",
         "Mechanics of Deformable Solids",
         "Kinematics & Dynamics of Machines"], 31, 11, "Curriculum",
        "PCC ME 201 Heat Transfer & Thermal Machines 3 1 0 4 4", "high"),
    "electives": (
        ["Open Elective Courses (3 courses from any department)"], 23, 8, "Curriculum",
        "OPEN ELECTIVE COURSES (3 courses from any department)", "high"),
    "project": (
        "Engineering Project-2 (Design & Analysis); Engineering Project-3 "
        "(Prototype & Testing)", 23, 8, "Curriculum",
        "PROJ- ME 401 Engineering Project-2 (Design & Analysis)", "high"),
    "internship": (
        "Summer Internship is evaluated as part of the scheme", 24, 10, "Curriculum",
        "For Summer Internship / Projects / Seminar etc.Evaluation is b", "low"),
}

# Derived from the live field maps, never hand-listed. Typed out by hand once,
# this diverged from the real schema by 53 fields -- omitting 12 Institution &
# Offering fields, splitting the shared Course model arbitrarily across two page
# blocks, and dropping fields from four more segments. The maps are the schema;
# anything that restates them will drift from them.
SEGMENTS = {
    "Course Identity": list(COURSE_FIELD_IDS),
    "Duration & Mode": list(COURSE_FIELD_IDS),
    "Eligibility": list(ELIGIBILITY_FIELD_IDS),
    "Curriculum": list(CURRICULUM_FIELD_IDS),
    "Specialisation": list(SPECIALISATION_FIELD_IDS),
    "Ranking & Accreditation": list(RANKING_FIELD_IDS),
    **{segment: list(field_ids) for segment, (_, field_ids) in SEGMENT_FACTS.items()},
}

BLOCKED = {"Ranking & Accreditation": "no retrieval query defined for this segment"}
TIER_D_ONLY = {"Fees", "Institution & Offering", "Recruiters & Placement", "Salary",
               "Specialisation", "Career Mapping"}


def build(course_id: str, course_name: str) -> dict:
    segments = {}
    for segment, fields in SEGMENTS.items():
        values, citations = {}, []
        for name in fields:
            if name in EVIDENCE:
                value, page, chunk, seg, quote, conf = EVIDENCE[name]
                values[name] = value
                citations.append({
                    "field": name, "document_id": DOC, "page": page,
                    "chunk_id": chunk, "segment_id": seg,
                    "quoted_evidence": quote, "confidence": conf,
                })
            else:
                values[name] = None
        segments[segment] = {
            "provenance": "sourced" if citations else "no_evidence",
            "blocked_reason": BLOCKED.get(segment),
            "non_canonical_only": segment in TIER_D_ONLY,
            "fields": values,
            "citations": citations,
        }
    return {
        "course_id": course_id,
        "course_name": course_name,
        "generated_by": "manual RAG verification -- no API calls, no generation",
        "segments": segments,
        "summary": {
            "fields_total": sum(len(f) for f in SEGMENTS.values()),
            "fields_populated": len(EVIDENCE),
            "segments_with_evidence": sum(
                1 for s in segments.values() if s["citations"]),
            "segments_total": len(SEGMENTS),
        },
    }


def render(data: dict) -> str:
    e = html.escape
    rows = []
    for segment, block in data["segments"].items():
        populated = {k: v for k, v in block["fields"].items() if v not in (None, "", [], {})}
        cites = {c["field"]: c for c in block["citations"]}
        if populated:
            body = "".join(
                f'<div class="field"><h4>{e(k.replace("_", " ").title())}</h4>'
                + ("<ul>" + "".join(f"<li>{e(str(i))}</li>" for i in v) + "</ul>"
                   if isinstance(v, list) else f"<p>{e(str(v))}</p>")
                + (f'<p class="cite">Source: {e(cites[k]["document_id"])} '
                   f'p.{cites[k]["page"]} chunk {cites[k]["chunk_id"]} '
                   f'&middot; confidence {e(cites[k]["confidence"])}<br>'
                   f'<q>{e(cites[k]["quoted_evidence"][:120])}</q></p>' if k in cites else "")
                + "</div>"
                for k, v in populated.items())
            tag = f'<span class="pill ok">{len(populated)} of {len(block["fields"])} established</span>'
        else:
            why = (block["blocked_reason"] or
                   ("only non-canonical (Tier D) evidence available"
                    if block["non_canonical_only"] else
                    "retrieved documents contain no evidence for these fields"))
            body = f'<p class="empty">Not established &mdash; {e(why)}.</p>'
            tag = '<span class="pill none">0 established</span>'
        rows.append(f'<section><div class="head"><h2>{e(segment)}</h2>{tag}</div>{body}</section>')

    s = data["summary"]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(data['course_name'])} &mdash; verification output</title>
<style>
:root{{--ink:#17202a;--muted:#5c6975;--line:#dce4ea;--primary:#123f5a;
--ok:#27725a;--ok-bg:#eaf6f1;--none:#8a949c;--none-bg:#f0f3f5;--canvas:#f5f8fa}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--canvas);color:var(--ink);line-height:1.6;
font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:900px;margin:0 auto;padding:32px 20px 80px}}
header.page{{background:linear-gradient(135deg,#10394f,#165d79);color:#fff;
border-radius:20px;padding:30px}}
header.page h1{{margin:0 0 8px;font-size:2rem;letter-spacing:-.03em}}
header.page p{{margin:0;color:#dcebf1;font-size:.95rem}}
.stats{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 0}}
.stat{{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);
border-radius:10px;padding:8px 12px;font-size:.82rem;font-weight:700}}
section{{background:#fff;border:1px solid var(--line);border-radius:14px;
padding:20px;margin-top:14px}}
.head{{display:flex;justify-content:space-between;align-items:center;gap:12px;
border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:14px}}
h2{{margin:0;font-size:1.15rem;color:var(--primary)}}
.pill{{font-size:.72rem;font-weight:800;border-radius:999px;padding:4px 10px;white-space:nowrap}}
.pill.ok{{background:var(--ok-bg);color:var(--ok)}}
.pill.none{{background:var(--none-bg);color:var(--none)}}
.field{{margin-bottom:16px}}
.field h4{{margin:0 0 4px;font-size:.9rem;color:var(--primary)}}
.field p,.field ul{{margin:0 0 4px}} .field ul{{padding-left:20px}}
.cite{{font-size:.75rem;color:var(--muted);border-left:3px solid var(--line);
padding-left:10px;margin-top:6px}}
.cite q{{font-style:italic}}
.empty{{margin:0;color:var(--muted);font-size:.9rem}}
footer{{margin-top:24px;color:var(--muted);font-size:.8rem}}
</style></head><body><div class="wrap">
<header class="page">
<h1>{e(data['course_name'])}</h1>
<p>Generated strictly from retrieved evidence. No content was invented; every value carries its source, page and chunk.</p>
<div class="stats">
<span class="stat">{s['fields_populated']} of {s['fields_total']} fields established</span>
<span class="stat">{s['segments_with_evidence']} of {s['segments_total']} segments with evidence</span>
<span class="stat">0 generated</span>
</div></header>
{''.join(rows)}
<footer>Verification build &mdash; {e(data['generated_by'])}.</footer>
</div></body></html>"""


def main() -> int:
    course_id = sys.argv[1] if len(sys.argv) > 1 else "mechanical_engineering"
    from src.courses.taxonomy import load_taxonomy

    course = {c.course_id: c for c in load_taxonomy()}[course_id]
    data = build(course_id, course.standard_course_name)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{course_id}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / f"{course_id}.html").write_text(render(data), encoding="utf-8")

    s = data["summary"]
    print(f"{course_id}: {s['fields_populated']}/{s['fields_total']} fields, "
          f"{s['segments_with_evidence']}/{s['segments_total']} segments")
    print(f"  -> {OUT / (course_id + '.json')}")
    print(f"  -> {OUT / (course_id + '.html')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
