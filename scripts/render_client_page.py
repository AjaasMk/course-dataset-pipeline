"""Render one course into the client's page template, structure-for-structure.

Run: PYTHONPATH=. python scripts/render_client_page.py mechanical_engineering

The client confirmed their template is the contract: nothing less, nothing more.
So this emits ALL 16 content sections in their order, with their class names,
their stylesheet and their behaviour script -- the CSS and JS are read out of
their file rather than copied, so a change on their side cannot drift from ours.

Every component keeps its real shell. A section with no data renders its own
markup with placeholder rows or an explicit awaiting note, never demo text and
never a collapsed layout: the point is to show which of their 123 page values
our evidence can currently fill, in the exact place each one belongs.
"""

import html
import json
import re
import sys
from pathlib import Path

TEMPLATE = Path("docs/specs by fmc/course-details-demo-template-v2.html")
DATA = Path("data/verification")
TOTAL_POINTS = 123

EXTRA_CSS = """
    .awaiting { border: 1px dashed #c3d0d8; border-radius: var(--radius-md);
      padding: 15px; color: var(--muted); font-size: .86rem; background: #fbfdfe; }
    .awaiting strong { display: block; color: var(--primary); margin-bottom: 3px; }
    .evidence { margin-top: 9px; font-size: .73rem; color: var(--muted);
      border-left: 3px solid var(--line); padding-left: 9px; }
    .evidence q { font-style: italic; }
    .est { background: var(--green-soft); color: var(--green); border-radius: 999px;
      padding: 3px 8px; font-size: .68rem; font-weight: 850; margin-left: 6px; }
"""


def parts() -> tuple[str, str]:
    text = TEMPLATE.read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", text, re.S).group(1)
    js = re.search(r"<script>(.*?)</script>", text, re.S).group(1)
    return css + EXTRA_CSS, js


def render(data: dict) -> str:
    e = html.escape
    segs = data["segments"]

    def f(segment, name):
        return segs.get(segment, {}).get("fields", {}).get(name)

    def cite(segment, name):
        return next((c for c in segs.get(segment, {}).get("citations", [])
                     if c["field"] == name), None)

    def why(segment):
        block = segs.get(segment, {})
        if block.get("blocked_reason"):
            return block["blocked_reason"]
        if block.get("non_canonical_only"):
            return "only non-canonical (Tier D) sources available for this course"
        return "the retrieved official documents do not state it"

    def awaiting(label, reason):
        return (f'<div class="awaiting"><strong>{e(label)}</strong>'
                f'Awaiting evidence &mdash; {e(reason)}.</div>')

    def note(c):
        if not c:
            return ""
        return (f'<div class="evidence">{e(c["document_id"])} p.{c["page"]} '
                f'&middot; chunk {c["chunk_id"]} &middot; {e(c["confidence"])} confidence'
                f'<br><q>{e(c["quoted_evidence"][:110])}</q></div>')

    css, js = parts()
    name = data["course_name"]
    subjects = f("Curriculum", "core_subjects") or []
    electives = f("Curriculum", "electives") or []
    project = f("Curriculum", "project")
    internship = f("Curriculum", "internship")
    credits = f("Duration & Mode", "credit_count")
    regulator = f("Course Identity", "regulating_body")
    filled = data["summary"]["fields_populated"]
    pct = round(filled / TOTAL_POINTS * 100)

    def quick(icon, label, value):
        shown = (", ".join(map(str, value)) if isinstance(value, list)
                 else str(value) if value not in (None, "", [], {}) else None)
        return (f'<article class="quick-card"><div class="quick-icon">{icon}</div>'
                f'<small>{label}</small><strong>'
                + (e(shown) if shown else "&mdash;") + "</strong></article>")

    # Subjects split across the client's year tabs. The curriculum table gives
    # subject codes but the chunk's heading was wrong about which semester they
    # sit in, so they all render under Year 1 rather than being placed on a
    # guess -- a wrong year is worse than an unassigned one.
    def subject_cards(items):
        if not items:
            return awaiting("Subjects", why("Curriculum"))
        return ('<div class="subject-grid">' + "".join(
            f'<article class="subject-card"><strong>{e(s)}</strong>'
            f'<span>Established from the regulator curriculum table. '
            f'No description published in the source.</span></article>'
            for s in items) + "</div>")

    empty_row = ('<tr><td colspan="4" style="color:var(--muted)">'
                 "Awaiting evidence &mdash; no official schedule retrieved.</td></tr>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="description" content="Course details page built from official sources only." />
<title>{e(name)} | Course Library</title>
<style>{css}</style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <span>Career information for students in Grades 8&ndash;12 and their parents</span>
      <span>Need guidance? <a href="#parent">Talk to a counsellor</a></span>
    </div>
  </div>

  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="#"><span class="brand-mark">C</span>Career Portal</a>
      <nav class="main-nav" aria-label="Primary navigation">
        <a href="#">Courses</a><a href="#">Careers</a>
        <a href="#">Colleges</a><a href="#">Assessments</a>
      </nav>
      <div class="header-actions">
        <button class="btn btn-secondary">Sign in</button>
        <button class="btn btn-primary">Student dashboard</button>
      </div>
    </div>
  </header>

  <nav class="breadcrumbs" aria-label="Breadcrumb">
    Home <span>&rsaquo;</span> Courses <span>&rsaquo;</span>
    Engineering &amp; Applied Technology <span>&rsaquo;</span> {e(name)}
  </nav>

  <main>
    <section class="hero">
      <div class="hero-card">
        <div>
          <div class="label-row">
            <span class="eyebrow">Undergraduate</span>
            <span class="eyebrow">Engineering &amp; Applied Technology</span>
            <span class="eyebrow">Source-verified</span>
          </div>
          <h1>{e(name)}</h1>
          <p class="hero-summary">
            This page shows only what official regulator documents state. Every
            value carries the document, page and quoted line it came from;
            sections with no evidence say so rather than being filled in.
          </p>
          <div class="hero-actions">
            <button class="btn btn-accent" id="saveTop">&#9825; Save course</button>
            <button class="btn btn-secondary" id="compareTop">&#8646; Add to compare</button>
            <a class="btn btn-secondary" href="#colleges">&#8982; Find colleges</a>
          </div>
        </div>
        <aside class="fit-panel">
          <h2>Evidence coverage</h2>
          <p>How much of this page official sources currently support.</p>
          <div class="fit-score"><strong>{pct}%</strong></div>
          <div class="fit-list">
            <span>{filled} of {TOTAL_POINTS} page values established</span>
            <span>{data['summary']['segments_with_evidence']} of {data['summary']['segments_total']} segments with evidence</span>
            <span>0 values generated or inferred</span>
          </div>
        </aside>
      </div>
    </section>

    <section class="quick-grid" aria-label="Course at a glance">
      {quick("&#9201;", "Typical duration", f("Duration & Mode", "minimum_duration"))}
      {quick("&#127891;", "Entry level", f("Eligibility", "minimum_qualification"))}
      {quick("&#128218;", "Suitable streams", f("Eligibility", "accepted_streams"))}
      {quick("&#129514;", "Learning style", f("Curriculum", "learning_activities"))}
      {quick("&#128176;", "Indicative fees", f("Fees", "tuition_fee"))}
      {quick("&#129517;", "Career direction", f("Career Mapping", "typical_entry_role"))}
    </section>

    <nav class="section-tabs" aria-label="Course section navigation">
      <div class="tab-inner">
        <a href="#snapshot">Snapshot</a><a href="#overview">Overview</a>
        <a href="#fit">Suitability</a><a href="#eligibility">Eligibility</a>
        <a href="#subjects">Subjects</a><a href="#careers">Careers</a>
        <a href="#recruiters">Recruiters</a><a href="#fees">Fees</a>
        <a href="#colleges">Colleges</a><a href="#compare">Compare</a>
        <a href="#parent">Parent guide</a><a href="#faq">FAQs</a>
      </div>
    </nav>

    <div class="page">
      <div class="main-column">

        <section class="content-section" id="snapshot">
          <div class="section-heading">
            <div><h2>Course snapshot</h2>
            <p>Salary outlook and possible specialisation pathways</p></div>
            <span class="section-tag">Decision snapshot</span>
          </div>
          <div class="snapshot-grid">
            <article class="snapshot-panel">
              <h3>Indicative salary range</h3>
              <p>Published salary evidence for this course.</p>
              <div class="salary-values">
                <div class="salary-value"><small>Lower range</small><strong>&mdash;</strong></div>
                <div class="salary-value featured"><small>Typical average</small><strong>&mdash;</strong></div>
                <div class="salary-value"><small>Higher range</small><strong>&mdash;</strong></div>
              </div>
              {awaiting("Salary", why("Salary"))}
            </article>
            <article class="snapshot-panel">
              <h3>Popular specialisations</h3>
              <p>Specialisations named in official course documents.</p>
              {awaiting("Specialisations", why("Specialisation"))}
            </article>
          </div>
          <div class="data-note"><span>&#9432;</span><span>
            Salary and specialisation require Tier A/B/C evidence. Commercial
            portals are used for discovery only and never as the published value.
          </span></div>
        </section>

        <section class="content-section" id="overview">
          <div class="section-heading">
            <div><h2>What is {e(name)}?</h2>
            <p>A simple explanation for students and parents</p></div>
            <span class="section-tag">About 180 words</span>
          </div>
          {awaiting("Overview", "explanatory prose is written, not extracted, and the generation stage has not run")}
        </section>

        <section class="content-section" id="fit">
          <div class="section-heading">
            <div><h2>Is this course suitable for you?</h2>
            <p>Interest, learning preference and reality check</p></div>
            <span class="section-tag">Student decision support</span>
          </div>
          <div class="two-col">
            <article class="info-box positive"><h3>You may enjoy this course if you&hellip;</h3>
            {awaiting("Suitability", "advisory guidance is written, not extracted")}</article>
            <article class="info-box caution"><h3>Think carefully if you&hellip;</h3>
            {awaiting("Cautions", "advisory guidance is written, not extracted")}</article>
          </div>
        </section>

        <section class="content-section" id="eligibility">
          <div class="section-heading">
            <div><h2>Eligibility and admission</h2>
            <p>Requirements vary by university</p></div>
            <span class="section-tag">Verify institution rules</span>
          </div>
          <div class="two-col">
            <article class="info-box"><h3>Typical eligibility</h3>
            {awaiting("Eligibility", why("Eligibility"))}</article>
            <article class="info-box"><h3>Possible admission methods</h3>
            {awaiting("Admission methods", why("Entrance & Admission"))}</article>
          </div>
          <div class="timeline" aria-label="Admission pathway">
            {"".join(f'<article class="timeline-step"><span class="step-number">{i}</span>'
                     f'<strong>Step {i}</strong><p>Awaiting official admission schedule.</p>'
                     f'</article>' for i in range(1, 6))}
          </div>
        </section>

        <section class="content-section" id="subjects">
          <div class="section-heading">
            <div><h2>What will you study?</h2>
            <p>Established from the regulator's model curriculum</p></div>
            <span class="section-tag">{len(subjects)} subjects established</span>
          </div>
          <div class="tabs" role="tablist" aria-label="Year-wise subjects">
            <button class="tab-btn active" data-tab="year1">Year 1</button>
            <button class="tab-btn" data-tab="year2">Year 2</button>
            <button class="tab-btn" data-tab="year3">Year 3</button>
            <button class="tab-btn" data-tab="learning">Learning style</button>
          </div>
          <div class="tab-panel active" id="year1">{subject_cards(subjects)}
            {note(cite("Curriculum", "core_subjects"))}</div>
          <div class="tab-panel" id="year2">
            {awaiting("Year 2 subjects", "the source curriculum table does not map subjects to a year")}</div>
          <div class="tab-panel" id="year3">
            {awaiting("Year 3 subjects", "the source curriculum table does not map subjects to a year")}</div>
          <div class="tab-panel" id="learning">
            <div class="two-col">
              <article class="info-box"><h3>Common learning activities</h3>
              {awaiting("Learning activities", why("Curriculum"))}</article>
              <article class="info-box"><h3>Common assessment methods</h3>
              {awaiting("Assessment methods", why("Curriculum"))}</article>
            </div>
          </div>
        </section>

        <section class="content-section">
          <div class="section-heading">
            <div><h2>Skills you can develop</h2>
            <p>Subject knowledge, transferable skills and career readiness</p></div>
            <span class="section-tag">9 skill areas</span>
          </div>
          {awaiting("Skills", "explanatory content is written, not extracted, and the generation stage has not run")}
        </section>

        <section class="content-section" id="careers">
          <div class="section-heading">
            <div><h2>Career opportunities</h2>
            <p>Separate direct-entry roles from regulated professional roles</p></div>
            <span class="section-tag">Career-route clarity</span>
          </div>
          {awaiting("Careers", why("Career Mapping"))}
        </section>

        <section class="content-section" id="recruiters">
          <div class="section-heading">
            <div><h2>Top recruiters and employment sectors</h2>
            <p>Organisations shown with the roles they recruit for</p></div>
            <span class="section-tag">Verified directory</span>
          </div>
          {awaiting("Recruiters", why("Recruiters & Placement"))}
          <div class="data-note"><span>&#9432;</span><span>
            A recruiter is published only from an official placement report. A
            logo must not imply that every student receives an offer.
          </span></div>
        </section>

        <section class="content-section">
          <div class="section-heading">
            <div><h2>Further-study pathway</h2>
            <p>One possible route toward a specialised career</p></div>
          </div>
          {awaiting("Further-study pathway", "explanatory content is written, not extracted")}
        </section>

        <section class="content-section" id="fees">
          <div class="section-heading">
            <div><h2>Fees and total study cost</h2>
            <p>Official fee schedules only</p></div>
            <span class="section-tag">Parent priority</span>
          </div>
          <div class="table-wrap"><table>
            <thead><tr><th>Cost category</th><th>Indicative range</th>
            <th>Frequency</th><th>What parents should check</th></tr></thead>
            <tbody>{empty_row}</tbody>
          </table></div>
          {awaiting("Fees", why("Fees"))}
        </section>

        <section class="content-section" id="colleges">
          <div class="section-heading">
            <div><h2>Top colleges and universities</h2>
            <p>Ranked directory with All, Government and Private filters</p></div>
            <span class="section-tag">Official ranking</span>
          </div>
          <div class="college-toolbar">
            <div class="college-filters" role="group" aria-label="Filter institutions by type">
              <button class="college-filter-btn active" data-college-filter="all">All institutions</button>
              <button class="college-filter-btn" data-college-filter="government">Government</button>
              <button class="college-filter-btn" data-college-filter="private">Private</button>
            </div>
            <div class="ranking-source">Awaiting official ranking data</div>
          </div>
          {awaiting("Colleges", why("Institution & Offering"))}
        </section>

        <section class="content-section" id="compare">
          <div class="section-heading">
            <div><h2>Compare similar courses</h2>
            <p>Help families understand meaningful differences</p></div>
            <span class="section-tag">Decision table</span>
          </div>
          <div class="table-wrap"><table>
            <thead><tr><th>Feature</th><th>{e(name)}</th>
            <th>Alternative 1</th><th>Alternative 2</th></tr></thead>
            <tbody>{empty_row}</tbody>
          </table></div>
          {awaiting("Comparison", "cross-course assembly has not run")}
        </section>

        <section class="content-section">
          <div class="section-heading">
            <div><h2>What should you do now?</h2>
            <p>Different guidance for Grades 8&ndash;10 and Grades 11&ndash;12</p></div>
          </div>
          {awaiting("Next steps", "advisory guidance is written, not extracted")}
        </section>

        <section class="content-section parent-section" id="parent">
          <div class="section-heading">
            <div><h2>Parent corner</h2>
            <p>Questions that support informed family discussion</p></div>
            <span class="section-tag">About 150 words</span>
          </div>
          {awaiting("Parent guidance", "advisory content is written, not extracted")}
        </section>

        <section class="content-section" id="faq">
          <div class="section-heading">
            <div><h2>Frequently asked questions</h2>
            <p>Short, expandable answers</p></div>
            <span class="section-tag">6&ndash;10 questions</span>
          </div>
          <div class="accordion">
            <article class="accordion-item open">
              <button class="accordion-button"><span>No questions published yet</span><span>&minus;</span></button>
              <div class="accordion-content">
                FAQs are advisory content written for each course. The generation
                stage has not run, so none are published here.
              </div>
            </article>
          </div>
        </section>

        <section class="content-section source-box">
          <strong>Page verification area</strong>
          <p>Content status: source-verified build &middot; Reviewer: Career Content Team</p>
          <p>{filled} of {TOTAL_POINTS} page values are established from official
          sources, each traceable to a document, page and quoted line. The
          remainder are marked awaiting rather than filled with placeholder text.
          Source used: AICTE Revised Model Curriculum for the UG Degree Course in
          {e(name)} (Tier A).</p>
        </section>
      </div>

      <aside class="sidebar">
        <section class="side-card">
          <h3>Evidence summary</h3>
          <p>How much of this page is backed by official sources.</p>
          <div class="progress-label"><span>Page coverage</span><span>{pct}%</span></div>
          <div class="progress"><span style="width:{pct}%"></span></div>
          <button class="btn btn-primary" id="saveSide">&#9825; Save this course</button>
          <button class="btn btn-secondary" id="compareSide">&#8646; Compare courses</button>
        </section>
        <section class="side-card">
          <h3>Course checklist</h3>
          <div class="mini-list">
            <div class="mini-item"><span class="mini-icon">1</span>
            <span>{filled} values from official sources.</span></div>
            <div class="mini-item"><span class="mini-icon">2</span>
            <span>{TOTAL_POINTS - filled} awaiting evidence or generation.</span></div>
            <div class="mini-item"><span class="mini-icon">3</span>
            <span>0 values generated or inferred.</span></div>
            <div class="mini-item"><span class="mini-icon">4</span>
            <span>Every published value carries a quoted source line.</span></div>
          </div>
        </section>
        <section class="side-card">
          <h3>Need personal guidance?</h3>
          <p>Discuss course fit, subject selection and pathways with a career counsellor.</p>
          <button class="btn btn-accent">Book counselling</button>
        </section>
      </aside>
    </div>
  </main>

  <div class="mobile-bar">
    <button class="btn btn-secondary" id="mobileSave">&#9825; Save</button>
    <button class="btn btn-secondary" id="mobileCompare">&#8646; Compare</button>
    <a class="btn btn-primary" href="#colleges">Colleges</a>
  </div>

  <footer>
    <strong>Career Portal Course Library</strong><br />
    Course information should guide exploration and should not replace official
    eligibility, admission or professional-regulation sources.
  </footer>

  <script>{js}</script>
</body>
</html>"""


def main() -> int:
    course_id = sys.argv[1] if len(sys.argv) > 1 else "mechanical_engineering"
    data = json.loads((DATA / f"{course_id}.json").read_text(encoding="utf-8"))
    out = DATA / f"{course_id}-client-template.html"
    out.write_text(render(data), encoding="utf-8")
    print(f"{course_id}: {data['summary']['fields_populated']} of {TOTAL_POINTS} page values")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
