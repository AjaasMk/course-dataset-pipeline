"""Render the PHP prototype's pages as static HTML.

PHP is not installed on this host, and the client's Laravel app is not ours to
run, so the same data is rendered statically here to make the design reviewable
now. web/*.php stays the deliverable; this is a preview of it.

Run: PYTHONPATH=. python scripts/build_web_preview.py
"""

import html
import json
import shutil
import sys
from pathlib import Path

INDEX_FILE = Path("data/web/courses.json")
GENERATED_DIR = Path("data/generated")
OUT_DIR = Path("data/web/preview")
STYLE = Path("web/style.css")


def load_generated(course_key: str, segment: str):
    slug = segment.replace(" ", "_").replace("&", "and")
    path = GENERATED_DIR / f"{course_key}__{slug}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def segment_state(course: dict, segment: str) -> dict:
    record = load_generated(course["course_key"], segment)
    if record:
        return {
            "provenance": "generated",
            "fields": record.get("fields") or {},
            "generator_model": record.get("generator_model"),
            "generated_at": record.get("generated_at"),
            "sources_attempted": record.get("sources_attempted") or [],
            "review_required": record.get("review_required", True),
            "publishable": record.get("publishable", False),
            "sources": [],
        }
    sources = course.get("segments", {}).get(segment) or []
    return {
        "provenance": "sourced" if sources else "no_source_found",
        "fields": {},
        "sources": sources,
        "sources_attempted": [],
        "generator_model": None,
        "generated_at": None,
        "review_required": True,
        "publishable": False,
    }


def humanise(key: str) -> str:
    return key.replace("_", " ").capitalize()


def render_value(value) -> str:
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{html.escape(str(v))}</li>" for v in value) + "</ul>"
    return f"<p>{html.escape(str(value))}</p>"


def chrome(title: str, admin: bool, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title><link rel="stylesheet" href="style.css"></head><body>
<div class="topbar"><div class="topbar-inner">
<span>Career information for students in Grades 8-12 and their parents</span>
<span>{'Admin view' if admin else 'Student view'}</span></div></div>
{body}
<footer><strong>Career Portal Course Library</strong><br>
Course information should guide exploration and should not replace official
eligibility, admission or professional-regulation sources.</footer>
</body></html>"""


def header(admin: bool, index_only: bool, course_key: str = "") -> str:
    if index_only:
        student, adm = "index.html", "index-admin.html"
    else:
        student, adm = f"{course_key}.html", f"{course_key}-admin.html"
    return f"""<header class="site-header"><div class="header-inner">
<a class="brand" href="index.html"><span class="brand-mark">C</span> Career Portal</a>
<div><a class="btn {'' if admin else 'active'}" href="{student}">Student view</a>
<a class="btn {'active' if admin else ''}" href="{adm}">Admin view</a></div>
</div></header>"""


def build_index(index: dict, admin: bool) -> str:
    courses, segments = index["courses"], index["segment_order"]
    totals = {"sourced": 0, "generated": 0, "no_source_found": 0}
    cards = []
    for course in courses:
        per = {"sourced": 0, "generated": 0, "no_source_found": 0}
        for segment in segments:
            per[segment_state(course, segment)["provenance"]] += 1
            totals[segment_state(course, segment)["provenance"]] += 1
        total = max(sum(per.values()), 1)
        link = f"{course['course_key']}{'-admin' if admin else ''}.html"
        legend = (
            f"<span>{per['sourced']} sourced</span><span>{per['generated']} generated</span>"
            + (f"<span>{per['no_source_found']} empty</span>" if per["no_source_found"] else "")
            if admin
            else f"<span>{total - per['no_source_found']} of {total} sections available</span>"
        )
        cards.append(f"""<a class="course-card" href="{link}">
<h3>{html.escape(course['name'])}</h3>
<p class="field">{html.escape(course['field'])}</p>
<div class="bar">
<span class="sourced" style="width:{per['sourced']/total*100}%"></span>
<span class="generated" style="width:{per['generated']/total*100}%"></span>
<span class="empty" style="width:{per['no_source_found']/total*100}%"></span></div>
<div class="legend">{legend}</div></a>""")

    cells = len(courses) * max(len(segments), 1)
    coverage = ""
    if admin:
        coverage = f"""<div class="content-section"><h2>Coverage</h2>
<p class="sub">{cells} cells across {len(courses)} courses x {len(segments)} segments</p>
<div class="bar">
<span class="sourced" style="width:{totals['sourced']/cells*100}%"></span>
<span class="generated" style="width:{totals['generated']/cells*100}%"></span>
<span class="empty" style="width:{totals['no_source_found']/cells*100}%"></span></div>
<div class="legend">
<span><i class="dot" style="background:var(--green)"></i>Sourced {totals['sourced']}</span>
<span><i class="dot" style="background:var(--accent)"></i>Generated {totals['generated']}</span>
<span><i class="dot" style="background:#dfe7ec"></i>No source found {totals['no_source_found']}</span>
</div></div>"""

    body = f"""{header(admin, True)}
<section class="hero"><div class="hero-card">
<span class="eyebrow">Pilot</span><span class="eyebrow">{len(courses)} courses</span>
<span class="eyebrow">{len(segments)} segments each</span>
<h1>Course Library</h1>
<p>Each course carries the same fourteen segments. A segment is either backed by an
official source document, generated where no source could be found, or recorded as
having nothing behind it - never silently omitted.</p>
</div></section>
<div class="page">{coverage}
<div class="toolbar"><strong style="color:var(--primary)">Courses</strong>
<span style="color:var(--muted);font-size:.84rem">Reading from data/generated/</span></div>
<div class="card-grid">{''.join(cards)}</div></div>"""
    return chrome("Course Library", admin, body)


def build_course(course: dict, segments: list, admin: bool) -> str:
    blocks = []
    for segment in segments:
        state = segment_state(course, segment)
        fields = {k: v for k, v in (state["fields"] or {}).items() if v not in (None, "", [], {})}

        prov = ""
        if admin:
            klass = {"generated": "generated", "sourced": "sourced"}.get(state["provenance"], "none")
            src = f" from {html.escape(', '.join(state['sources']))}" if state["sources"] else ""
            prov = (f'<p class="sub"><span class="pill {klass}">'
                    f'{html.escape(state["provenance"].replace("_", " "))}</span>{src}</p>')

        if fields:
            content = "".join(
                f'<div class="field-block"><h4>{html.escape(humanise(k))}</h4>{render_value(v)}</div>'
                for k, v in fields.items()
            )
        elif admin:
            content = ('<div class="empty-note">Source documents retrieved, but extraction has '
                       'not been run for this segment yet, so no field values exist.</div>'
                       if state["provenance"] == "sourced"
                       else '<div class="empty-note">No source document found and nothing '
                            'generated for this segment.</div>')
        else:
            content = '<div class="empty-note">Information for this section is being prepared.</div>'

        strip = ""
        if admin and state["provenance"] == "generated":
            attempted = (f"<br>Sources checked and found nothing: "
                         f"{html.escape(', '.join(state['sources_attempted']))}."
                         if state["sources_attempted"] else "")
            strip = f"""<div class="admin-strip">
Generated by <code>{html.escape(str(state['generator_model']))}</code> on
{html.escape(str(state['generated_at'])[:10])}. No citation exists for generated content.{attempted}
<br>Review required: {'yes' if state['review_required'] else 'no'} &middot;
Publishable: {'yes' if state['publishable'] else 'no'}</div>"""

        blocks.append(f'<section class="content-section"><h2>{html.escape(segment)}</h2>'
                      f"{prov}{content}{strip}</section>")

    body = f"""{header(admin, False, course['course_key'])}
<section class="hero"><div class="hero-card">
<span class="eyebrow">{html.escape(course['level'])}</span>
<span class="eyebrow">{html.escape(course['field'])}</span>
<h1>{html.escape(course['name'])}</h1>
<p>This page brings together what is known about the course across fourteen standard
sections: what you study, how you get in, what it costs and where it leads.</p>
</div></section>
<div class="page">{''.join(blocks)}
<section class="content-section"><h2>Page verification area</h2>
<p class="sub">Content status: Pilot &middot; Reviewer: Career Content Team</p></section>
</div>"""
    return chrome(course["name"], admin, body)


def main() -> int:
    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(STYLE, OUT_DIR / "style.css")

    (OUT_DIR / "index.html").write_text(build_index(index, False), encoding="utf-8")
    (OUT_DIR / "index-admin.html").write_text(build_index(index, True), encoding="utf-8")

    for course in index["courses"]:
        key = course["course_key"]
        (OUT_DIR / f"{key}.html").write_text(
            build_course(course, index["segment_order"], False), encoding="utf-8")
        (OUT_DIR / f"{key}-admin.html").write_text(
            build_course(course, index["segment_order"], True), encoding="utf-8")

    print(f"wrote {len(list(OUT_DIR.glob('*.html')))} pages to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
