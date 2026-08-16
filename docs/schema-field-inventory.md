# Course schema — field inventory

Source: `docs/course-details-demo-template-v2.html`
Schema: `schema/course.schema.json` (JSON Schema draft 2020-12)
Reference instance: `schema/examples/bsc-psychology.json` — the demo page's content, used as
the fixture proving the schema fits what the template renders. It deviates from the demo copy
in exactly the five places the demo contradicts itself (see below); everything else is verbatim.

```bash
python -c "import json,sys;from jsonschema import Draft202012Validator as V;s=json.load(open('schema/course.schema.json',encoding='utf-8'));i=json.load(open('schema/examples/bsc-psychology.json',encoding='utf-8'));V.check_schema(s);e=list(V(s).iter_errors(i));print('PASS' if not e else [(list(x.path),x.message) for x in e]);sys.exit(bool(e))"
```

Every row maps a rendered element in the demo to a schema path. Counts are locked
to the demo's rendered counts, not to the copy in the section tags.

## 1. Identity / page-level

| Demo element | Schema path | Type |
|---|---|---|
| `<title>` | `seo.page_title` | string |
| `<meta name="description">` | `seo.meta_description` | string |
| Breadcrumb level 3 + hero chip 2 | `category` | string |
| Breadcrumb leaf | `subcategory` | string |
| Hero `<h1>` | `course_name` | string |
| Hero chip 1 (`Undergraduate`) | `course_level` | enum(5) |
| Hero chip 3 (`Student-friendly guide`) | `hero.badge` | string |
| — (pipeline-supplied) | `course_id`, `slug` | string |
| — (scope for all figures) | `currency` enum(5), `region` | string |

## 2. Hero

| Demo element | Schema path | Type |
|---|---|---|
| `.hero-summary` | `hero.summary` | string (150–420) |
| `.fit-score` `76%` | `hero.fit.score_percent` | int 0–100 |
| `.fit-panel > p` | `hero.fit.note` | string |
| `.fit-list span` ×3 | `hero.fit.indicators` | string[3] |

## 3. Quick facts — `.quick-grid`, 6 fixed cards

Modelled as a **named object**, not an array: the six labels are fixed template
copy, so an object makes a dropped card a schema violation rather than a silent
short array.

| Card label | Schema path | Type |
|---|---|---|
| Typical duration | `quick_facts.typical_duration.{min_years,max_years}` | number |
| Entry level | `quick_facts.entry_level` | string |
| Suitable streams | `quick_facts.suitable_streams` | string[1–5] |
| Learning style | `quick_facts.learning_style` | string |
| Indicative fees | `quick_facts.indicative_annual_fees.{min,max}` | integer |
| Career direction | `quick_facts.career_direction` | string |

Icons (`⏱ 🎓 📚 🧪 💰 🧭`) are presentation — excluded, keep them in the Blade template.

## 4. Course snapshot — `#snapshot`

| Demo element | Schema path | Type |
|---|---|---|
| Lower range `₹2.5 LPA` | `snapshot.salary.lower_annual` | integer (250000) |
| Typical average `₹4.2 LPA` | `snapshot.salary.typical_annual` | integer |
| Higher range `₹8 LPA+` | `snapshot.salary.higher_annual` + `higher_is_open_ended` | integer + bool |
| `.salary-marker` `left: 38%` | `snapshot.salary.marker_percent` | int 0–100 |
| `.data-note` inside salary panel | `snapshot.salary.note` | string |
| `.specialisation-item` ×8 | `snapshot.specialisations` | string[8] |
| Section-level `.data-note` | `snapshot.data_note` | string |

The `01`–`08` prefixes on specialisations are rendered by the template from array index.

## 5. Overview — `#overview`

| Demo element | Schema path | Type |
|---|---|---|
| `<h2>What is BSc Psychology?</h2>` | `overview.heading` | string |
| 3 `<p>` blocks | `overview.paragraphs` | string[3] |

`About 180 words` is a generation constraint (validated in step 3), not a stored field.

## 6. Suitability — `#fit`

| Demo element | Schema path | Type |
|---|---|---|
| `.info-box.positive h3` | `suitability.good_fit.heading` | string |
| `.check-list li` ×4 | `suitability.good_fit.points` | string[4] |
| `.info-box.caution h3` | `suitability.caution.heading` | string |
| caution `li` ×4 | `suitability.caution.points` | string[4] |
| `.tags span` ×7 | `suitability.tags` | string[7] |

## 7. Eligibility — `#eligibility`

| Demo element | Schema path | Type |
|---|---|---|
| Typical eligibility `li` ×4 | `eligibility.typical_requirements` | string[4] |
| Admission methods `li` ×4 | `eligibility.admission_methods` | string[4] |
| `.timeline-step` ×5 | `eligibility.admission_timeline[]` | object[5] |
| ↳ `.step-number` / `strong` / `p` | `.step` / `.title` / `.description` | int / string / string |

## 8. Curriculum — `#subjects`

| Demo element | Schema path | Type |
|---|---|---|
| Year tabs, 4 `.subject-card` each | `curriculum.years[3–5].subjects[4]` | object[][4] |
| ↳ `strong` / `span` | `.name` / `.description` | string |
| Tab "Learning style" box 1 | `curriculum.learning_activities` | string |
| Tab "Learning style" box 2 | `curriculum.assessment_methods` | string |

**This is the one list whose length is driven by the course, not by the demo.** The demo
renders 3 year tabs because BSc Psychology is a 3-year degree; a B.Tech needs 4 and a B.Arch
needs 5. `curriculum.years` accepts **3–5 entries**, and the rule
`curriculum_length_matches_duration` requires the count to sit inside the course's own
`quick_facts.typical_duration` — so a course stated as 4 years with 3 year tabs is rejected,
and a course stated as 3–4 years may render either 3 or 4.

The template needs **no change** to render a 4th or 5th tab: `.tabs` is `flex-wrap`, the
subject grid is 2-column, and the tab script iterates `.tab-btn`/`.tab-panel` generically.
The "Learning style" tab stays last.

Ceiling is 5, not 4, so B.Arch, integrated LLB and 5-year integrated master's programmes stay
representable. A 6-year programme fails schema validation rather than silently truncating —
raise `maxItems` if the taxonomy contains any.

## 9. Skills

`.skill-card` ×6 → `skills[6]` of `{name, description}`. See discrepancy 1 below.

## 10. Careers — `#careers`

`.career-card` ×6 → `careers[6]`:

| Demo element | Schema path | Type |
|---|---|---|
| `h3` | `.title` | string |
| `p` | `.description` | string |
| `.route-badge` | `.route_badge` | enum(5) — the exact 5 badges used in the demo |
| `.route` | `.typical_route` | string |

`route_badge` is an enum because it drives a coloured pill; free text would produce
unbounded variants and break the "direct-entry vs regulated role" distinction the
section exists for.

## 11. Recruiters — `#recruiters`

`.recruiter-card` ×6 → `recruiters[6]`:
`logo_initials` (2 uppercase letters), `name`, `sector`, `description`, `roles[2]`.

`logo_initials` is stored, not derived — the demo uses `HR` for "People Consulting
Group B" and `NG` for "Community Foundation E", so initials aren't a function of the name.

## 12. Further-study pathway

`.pathway-item` ×5 → `further_study_pathway[5]` (string[]). The `→` arrows are template chrome.

## 13. Fees — `#fees`

Table of 4 rows → `fees.rows[4]`: `category`, `min`, `max`, `is_variable`,
`frequency` enum(4), `parent_check`. Plus `fees.footnote`.

`min`/`max` are nullable so the demo's `Varies` row is representable: when
`is_variable` is true both must be null (enforced in step 3's validator — JSON Schema
alone can express this with `if/then`, but the cross-field rule belongs with the other
business rules).

## 14. Colleges — `#colleges`

| Demo element | Schema path | Type |
|---|---|---|
| `Demo composite ranking` | `colleges.ranking_source` | string |
| `Updated August 2026` | `colleges.ranking_updated` | `YYYY-MM` |
| `.college-card` ×6 | `colleges.items[6]` | object[6] |
| ↳ `.college-rank` | `.rank` | int 1–6 |
| ↳ `h3` | `.name` | string |
| ↳ `p` (`New Delhi · BSc (Hons) Psychology · 4 years`) | `.city`, `.course_name`, `.duration_years` | string, string, number |
| ↳ `.institution-type` + `data-college-type` | `.institution_type` | enum government/private |
| ↳ `Demo score: 92.4` | `.score` | number 0–100 |
| ↳ meta chip 3 | `.admission_route` | string |
| ↳ meta chip 4 | `.highlight` | string |
| ↳ `.college-actions strong` | `.annual_fee` | integer |
| `.data-note` | `colleges.data_note` | string |

`institution_type` must stay a two-value enum — the client-side filter buttons
match on `data-college-type` exactly.

## 15. Compare — `#compare`

The demo table is 4 feature rows × 3 course columns. Modelled **column-wise** as
`comparison[3]`, each with the 4 fixed features as named properties
(`main_focus`, `statistics_level`, `laboratory_exposure`, `common_next_steps`).
Row-wise arrays would let the model emit rows in a different order or invent a
fifth feature; named properties can't drift.

`comparison[0].course_name` must equal `course_name` (cross-field rule, step 3).

## 16. Action roadmap

`.roadmap-card` ×3 → `action_roadmap[3]`: `stage` enum(`Grades 8-10`, `Grade 11`,
`Grade 12`), `title`, `description`.

## 17. Parent corner — `#parent`

`parent_corner.intro` (~150 words) + `.parent-question` ×6 → `questions[6]`.
The `1`–`6` numbering is CSS `counter()`.

## 18. FAQs — `#faq`

`.accordion-item` ×5 → `faqs[]` of `{question, answer}`.
Range set to **5–10** — the one count left loose rather than pinned. See discrepancy 2 below.

## 19. Verification — `.source-box`

| Demo element | Schema path | Type |
|---|---|---|
| `Last reviewed: August 2026` | `verification.last_reviewed` | `YYYY-MM-DD` |
| `Content status: Demo only` | `verification.content_status` | enum draft/reviewed/published |
| `Reviewer: Career Content Team` | `verification.reviewer` | string |
| "list official sources here" | `verification.sources[3–15]` | object[] |

`sources` is the one field I added that has no rendered equivalent in the demo. The
demo's own copy asks for it, and with Perplexity grounding you get citations for free
— dropping them means no audit trail for any number on the page. Each entry is
`{title, url (https only), publisher}`.

---

## Deliberately excluded

Excluded because it is **site chrome, identical on every course page** — hardcode in
the Blade template, don't make the model regenerate it 500 times:

- Topbar, header, primary nav, footer, mobile action bar
- Section navigation tabs (derivable from which sections are present)
- All `<h2>` section headings and their subtitles **except** `overview.heading`
  (which embeds the course name), plus all `.section-tag` pills
- Sidebar: progress bar (per-user state), "Course checklist" 4 items,
  "Need personal guidance?" card
- Save / Compare / Share button labels and their JS state

That's ~40 strings kept out of the generation payload. If the client wants any of
them per-course, they're additive and cheap to put back — tell me which.

Excluded because it is **presentation derived from data**:

- Quick-card icons, specialisation `01`–`08` numbers, parent-question counter,
  pathway arrows, salary scale gradient, accordion `+`/`−`

---

## Five places the demo contradicts itself

Found by validating the demo's own content against the schema built from it. In each case
the schema follows the number on the right, because that is what the template asks for in
production; the fixture was written to match.

| # | Where | Rendered | Section tag / implied | Schema follows |
|---|---|---|---|---|
| 1 | Skills | 6 cards | tag says "9 skill areas" | **6** (what renders) |
| 2 | FAQs | 5 items | tag says "6–10 questions" | **5–10**, the one loose range |
| 3 | Overview | 109 words | tag says "About 180 words" | **180** (140–260 accepted) |
| 4 | Parent corner intro | 48 words | tag says "About 150 words" | **150** (110–220 accepted) |
| 5 | Salary marker | CSS `left: 38%` | values imply 31% | **computed**, never authored |

3 and 4 matter most: the demo's rendered copy is roughly half the length its own tags call
for. Generating at the rendered length would ship visibly thin pages. If the client wants
the shorter copy, the two word-count rules are one-line changes.

5 is why `marker_percent` became a derived field rather than a generated one — see
[pipeline.md](docs/pipeline.md).

## Two calls I made that are worth your veto

**1. Money and duration are numbers, not display strings.**
The demo renders `₹20,000–₹3,00,000/year*`, `₹2.5 LPA`, `₹1.85 lakh/year*`, `3–4 years`
— three different formats for the same kind of quantity. Storing those strings makes
step 3's "reasonable value ranges" check impossible and makes the page unusable outside
India. Schema stores integers in base currency units (₹250000, not "2.5 LPA") plus a
single root `currency`; the Blade template formats. Cost: the Laravel side needs a
lakh/LPA formatter. Worth it.

**2. Enums where the value drives styling.**
`course_level`, `route_badge`, `institution_type`, `fees.rows[].frequency`,
`action_roadmap[].stage`, `content_status`. Free text in any of these produces a
card with no matching CSS class.

---

## Size, and why it matters for step 2

**99 distinct leaf field definitions** across 19 sections. Because most of them sit
inside fixed-length arrays, one fully populated course is **336 discrete values** — see
`schema/examples/bsc-psychology.json`, which is the demo page's own content expressed
in this schema and validates clean. Deepest nesting is
`curriculum.years[3].subjects[4].description` at 3 array/object levels.

That is too large for a single Perplexity Sonar structured-output call to fill
reliably. Expect truncation, dropped array items, and degraded grounding in the tail
sections. The schema is already partitioned along clean seams for a chunked approach
— identity+hero+quick_facts / snapshot+overview+suitability / eligibility+curriculum+skills /
careers+recruiters+pathway / fees+colleges+comparison / roadmap+parent+faqs+verification —
six calls, each independently re-runnable and independently validatable against a
`$ref`'d sub-schema. I'll bring options when we get to step 2.
