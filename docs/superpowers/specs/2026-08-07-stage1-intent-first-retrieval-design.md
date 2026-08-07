# Stage 1 Redesign — Intent-First, Segment-Based Retrieval

Date: 2026-08-07
Status: Proposed

## Context

Stage 1 today retrieves **one best-guess document per course**: walk the tier's
`retrieval_order`, fuzzy-match the course name against each source's index, take
the first match scoring ≥ 0.80, stop. On the real 50-course pilot that produced
33 documents from Careers360, 2 from AICTE, 15 from Wikipedia. That single
document then had to ground all 22 `CourseDetail` fields in Stage 2.

The client's cookbook (`docs/specs by fmc/indian_course_library_ai_sources_rag.xlsx`)
describes a fundamentally different model, and the current pipeline contradicts it
in three ways:

1. **Source authority is inverted.** Careers360 is Tier D in the client's Source
   Directory — "discovery and triangulation only," must "never override official
   evidence." The pipeline tries it *first* in every tier, ahead of the regulator.
2. **One document cannot serve 19 segments.** The cookbook assigns each course-page
   segment its own primary/secondary source, tier, verification rule and refresh
   cadence. Eligibility comes from a regulator; fees come from an institution
   prospectus; rankings come from NIRF. A single Careers360 page is not a
   substitute for any of them.
3. **"First match wins" discards evidence.** When two authoritative sources both
   speak to a field, the cookbook wants both retained and linked — as evidence,
   with conflicts preserved for later reconciliation, not silently resolved by
   whichever source happened to be first in a list.

This spec covers the Stage 1 rebuild. Stage 2's schema rebuild (158 fields) and
Stage 3 (validation/human review) are separate, dependent work.

## Scope

**In scope**

- Replace the course-level `retrieval_order` walk with per-segment retrieval intents.
- Redesign the `SourceAdapter` protocol so it resolves intents rather than
  fuzzy-matching a single crawled index.
- Replace `config/pilot_courses.yaml` (50 hand-picked courses) with the full client
  taxonomy (754 courses).
- Rebuild `config/sources.yaml` around the client's 44-source Source Directory and
  Regulator Map.
- New: institution registry, built from Tier A directories.
- New: manifest data model supporting many documents per course with segment/field
  linkage.
- Remove `WikipediaAdapter` and the `general_background` category entirely.

**Out of scope (explicitly deferred)**

- Stage 2 schema rebuild against the cookbook's 158 fields. Stage 1 produces the
  source manifest that rebuild will consume, but the two land separately.
- Stage 3 validation, `review_queue`, and the Mandatory Human Review Matrix workflow.
- The 4 cookbook segments with no F-numbered fields — S02 (course overview), S14
  (skills developed), S18 (further-study pathways), S19 (student reviews). These
  appear on the client's demo page but have no atomic field definitions, so they
  have no retrieval plan yet. Needs its own design pass.
- Coursera/edX adapters. Present in the current config, absent from the client's
  Source Directory.

## Decisions this design encodes

Confirmed with the user across the planning session; recorded here because two
prior sessions lost decisions by leaving them out of the repo.

| # | Decision |
|---|----------|
| 1 | **No LLM fallback.** Ungroundable fields stay `null` and flagged. The client's own Source Precedence table ranks AI-generated text as Tier F: "use only to explain verified records… abstain where evidence is missing." |
| 2 | **Tier D is discovery-only.** Careers360/Shiksha/CollegeDunia/salary portals are never canonical without Tier A/B/C corroboration. A course with no Tier A/B/C source is an honest `unresolved`, not a Tier D fill-in. |
| 3 | **Wikipedia is dropped.** Not in the client's 44-source directory. 15 pilot courses previously resolved through it; those now correctly go unresolved. |
| 4 | **All 44 Source Directory entries are in scope**, not just the ones the 50-course pilot needed. |
| 5 | **Blocked-site escalation:** realistic headers/session → official open-data alternative → Playwright as last resort. **Hard line: no CAPTCHA or anti-bot bypass, ever** — that source stays blocked and its segments go unresolved. |
| 6 | **Course unit = the specialization row** (col 1 of the taxonomy). 754 courses. The 4,254 degree-name variants in col 2 become aliases (F008). |
| 7 | **Intent-first planning.** The planner never emits a `document_url`; adapters are the only component permitted to return real URLs. |
| 8 | **University-backed segments resolve via Tier A institution discovery**, not a "university adapter" and not scoped web search. |

## Architecture

```
COURSE (from taxonomy)
   │
   ▼
PLANNER  ── emits retrieval intents, one per (segment × source)
   │        never emits URLs
   ▼
RETRIEVAL INTENTS  ── {segment, field_ids, source_id, priority, query_terms, doc_types}
   │
   ▼
ADAPTER REGISTRY  ── routes each intent to the adapter owning that source_id
   │
   ▼
SOURCE ADAPTER  ── resolve(intent) → real discovered documents
   │
   ▼
VALIDATE  ── confirm the document resolves and concerns this course
   │
   ▼
DOWNLOAD  ── idempotent fetch + hash + snapshot
   │
   ▼
SOURCE MANIFEST  ── documents + intents + resolutions (many-to-many)
```

The critical property: **URLs only ever originate from an adapter that actually
fetched something.** No component upstream of an adapter can invent one.

### Why intent-first

The alternative considered was discovery-first: crawl every source's index up
front, hand the candidate lists to the planner, let it select. Rejected because it
requires crawling all 44 sources before planning a single course, and most of that
crawl is wasted for any given course. Intent-first crawls only what a course
actually needs.

The decisive argument is correctness, not cost. Asking a model to emit
`document_url` produces confident, plausible, non-existent URLs — instructing it
not to invent URLs names the failure mode without preventing it. Removing the
field from the planner's output makes the failure structurally impossible.

## Components

### 1. Course list loader — `src/courses/taxonomy.py`

Reads `docs/COURSE LIST.xlsx` into course records. Replaces `config/pilot_courses.yaml`.

Measured properties of the real file:

- 30 sheets, each a broad field (Engineering, Medicine, Law, Design…).
- 754 specialization rows in col 1; **750 unique names**.
- 4,284 degree-name variants in col 2 (avg 5.68 per course), newline-separated,
  U+2022 bullet prefix on all but 10 lines — the parser must treat the bullet as
  **optional**.
- Zero rows with an empty col 2.

Four specializations are cross-listed in two sheets each — Interior Design
(Architecture + Design), Engineering Physics (Engineering + Physical Sciences),
Digital Humanities (Arts + Liberal), Physical Education Teaching Track (Education +
Sports). These resolve to **one course with two field associations**, not two
courses: they are the same qualification, and duplicating them would duplicate
retrieval cost and publish two competing pages.

```python
class Course(BaseModel):
    course_id: str
    standard_course_name: str
    fields: list[str]
    aliases: list[str]
    qualification_level: str
```

### 2. Planner — `src/retrieve/planner.py`

One LLM call per course. Inputs: the course record, the Source Directory (44
sources with tiers), the Regulator Map, and the Data Field Directory (F001–F142
grouped into 14 segments). Output: a list of `RetrievalIntent`.

```python
class RetrievalIntent(BaseModel):
    intent_id: str
    course_id: str
    segment: Segment
    field_ids: list[str]
    source_id: str
    priority: int
    role: IntentRole
    query_terms: list[str]
    required_document_type: list[DocumentType]
    qualification_level: str
```

Constraints enforced structurally, not by instruction:

- The model has no `document_url` field to populate.
- `source_id` is validated against the 44-entry Source Directory; an unknown
  source is a hard error, not a warning.
- `role` (`primary`/`secondary`/`discovery`) must be `discovery` when the source's
  tier is D, enforced after generation.

`priority` is the planner's source-preference judgment. It is **not** comparable to
`match_confidence`, which is deterministic and adapter-computed. They are never
compared or thresholded together.

The static blocks (Source Directory, Field Directory) go in a `cache_control`-marked
system block — the same pattern `src/extract/extractor.py` already uses. At 754
courses this is the difference between a viable and an unviable cost.

### 3. Adapter protocol — `src/retrieve/base.py` (redesigned)

The current protocol cannot express an intent:

| Current | Problem |
|---------|---------|
| `build_index() -> dict[str, str]` | Assumes one crawlable listing page per source. True for AICTE's model-syllabus list; false for UGC recognition (a search), NTA (bulletins by year), NIRF (tables by category+year), NAAC/NBA (per-institution records). |
| `match(course_name, index) -> SourceMatch \| None` | Matches on course name alone — no segment, no `query_terms`, no document-type filter. Returns exactly one match. |
| `download(match, tier)` | `tier` is the pilot strong/medium/weak label, which this redesign removes. |

New contract:

```python
class DiscoveredDocument(BaseModel):
    document_url: str
    document_title: str
    match_confidence: float
    match_type: MatchType
    publication_date: str | None = None
    academic_year: str | None = None

class SourceAdapter(Protocol):
    source_id: str
    tiers: list[SourceTier]

    def supports(self, intent: RetrievalIntent) -> bool: ...
    def resolve(self, intent: RetrievalIntent) -> list[DiscoveredDocument]: ...
    def download(self, document: DiscoveredDocument) -> DocumentRecord: ...
```

`resolve()` returns a **list** — the "first match wins" behaviour is removed at the
type level, not by convention.

`build_index()` leaves the protocol. Adapters that genuinely have a crawlable
listing page (AICTE) keep it as a private, lazily-built cache; adapters that
don't (UGC, NTA, NIRF) never implement it. Making it optional is the change that
lets one protocol cover all 44 sources.

Per the existing convention, `resolve()` implementations stay independent per
adapter — no shared base implementation. That duplication was accepted at 2
adapters and held at 3; at 44 it will need a shared helper for the common
"search page → filter links → score" shape. Extract it when the third adapter
repeats the same pattern, not preemptively.

### 4. Institution registry — `src/institutions/`

Curriculum, Fees, and Institution & Offering all need "the official university" —
but Tier B is a *category* covering thousands of institutions, not a crawlable
endpoint. Resolution is two-phase:

- **Phase A — global institution discovery.** Crawl AISHE, UGC HEI Search and NIRF
  **once**, course-independently, into a registry. Doing this per-course would mean
  754 × N redundant directory queries.
- **Phase B — per-course offering resolution.** Query the registry for institutions
  offering the course, then resolve each institution's own official course page.

```
institutions(institution_id, canonical_name, aishe_code, nirf_id,
             institution_type, ownership_type, affiliating_university,
             state, official_url, discovered_from_source_id, retrieved_at)

institution_aliases(institution_id, observed_name, source_id, confidence)

institution_course_offerings(institution_id, course_id, official_course_url,
                             discovered_from_source_id, confidence)
```

This registry also **resolves the entity-resolution dependency** the client's spec
assumes but never provides a store for: "do not create a new entity solely because
of formatting differences" requires something to resolve *against*. `institutions`
+ `institution_aliases` is that store, keyed on AISHE code where available — which
is exactly what the Source Directory recommends ("use AISHE code as an institutional
identifier where available").

Two known risks:

- **AISHE is critical path and currently `unverified`** — Angular SPA, deep-linked
  hash route serves the generic homepage, no REST endpoint identified. Per decision
  5, try the open-data route before Playwright; AISHE data has historically been
  published in downloadable form rather than only through the dashboard UI.
- **UGC HEI Search is a different endpoint** from the UGC PDF path currently marked
  `blocked` (CloudFront 403). It must be tested independently — one path being
  blocked implies nothing about the other.

**NIRF bounds the institution count.** AISHE alone can return hundreds of
institutions per course with no principled cut-off. NIRF's ranked category lists
give a defensible top-N, and rankings are a required segment regardless, so NIRF
does double duty.

### 5. Validate + download — `src/retrieve/validate.py`

A discovered URL that resolves but concerns the wrong course is the other half of
the hallucination problem. Before a document enters the manifest:

1. **Resolves** — HTTP 200, non-empty body, content-type matches
   `required_document_type`.
2. **Concerns this course** — the course name or a known alias appears in title or
   body, above a configured threshold.
3. **In-scope temporally** — for volatile segments (eligibility, fees, exams,
   seats, scholarships, rankings, salary, placements, internships), the document
   carries a publication date or academic year, or is flagged stale.

A document failing (1) or (2) is recorded as a failed resolution with the reason,
not silently dropped. Failing (3) is a warning, not a rejection.

### 6. Manifest data model — `src/retrieve/manifest.py` (rebuilt)

Current shape is one row per course keyed `(course_name, matched_url)` — it cannot
represent many documents per course, one document serving several segments, or the
evidence linkage the cookbook's no-dedup rule requires.

```
documents(document_id PK, source_id, source_tier, document_url UNIQUE,
          document_title, local_path, file_hash, content_type, content_length,
          http_status, publication_date, academic_year, valid_from, valid_until,
          retrieved_at)

retrieval_intents(intent_id PK, course_id, segment, field_ids_json, source_id,
                  priority, role, query_terms_json, status, created_at)

intent_resolutions(intent_id, document_id, match_confidence, match_type,
                   validated, validation_note,
                   PRIMARY KEY (intent_id, document_id))
```

Properties this buys:

- **`documents.document_url UNIQUE`** gives cross-course dedup at the document
  level. One NIRF 2026 engineering table is fetched once and linked from every
  engineering course's Ranking intent.
- **`intent_resolutions` is many-to-many**, so one document legitimately serves
  several segments — which the client's spec explicitly requires — without
  duplicating the document.
- **Two sources asserting the same fact stay as two rows**, linked to the same
  segment/field_ids. That is the cookbook's dedup rule expressed as a schema
  constraint rather than a runtime instruction.
- **`document_id` is the stable surrogate** that `SourceRegistryEntry.source_id`
  (F143) will resolve against when the Stage 2 schema rebuild lands. CLAUDE.md
  currently records this as an unreconciled gap; this closes it.
- **An intent with no resolution row is an unresolved segment** — the honest-gap
  record decisions 1 and 2 require, queryable rather than inferred.

Idempotency (Hard Constraint 5) is preserved: `download()` checks `documents` by
`document_url` before any HTTP request, exactly as the current implementation
checks `(course_name, matched_url)`.

### 7. Intent batching

754 courses × up to 14 segments ≈ **10.5k intents**. Many resolve to the same
document — one UGC nomenclature document serves hundreds of Course Identity
intents.

`documents.document_url UNIQUE` prevents re-*downloading*, but not re-*resolving*:
without batching the pipeline still runs 754 near-identical NIRF discovery
operations. Adapters therefore resolve against a per-run cache keyed on
`(source_id, normalized_query_terms, document_type)`. Course-independent sources
(NIRF category tables, UGC nomenclature, NSP scholarship lists) resolve once per
run; course-specific ones do not benefit and are unaffected.

## Configuration rebuild — `config/sources.yaml`

The current file is 6 flat `SourceCategory` buckets with named sources beneath
them. It is replaced by the client's structure:

- **`sources`** — 44 entries keyed by `source_id`, each with `tiers` (a list —
  NSDC, ICAR and SWAYAM are A/B, LinkedIn Jobs is C/D), `authority_type`,
  `official_url`, `coverage`, `refresh`, and a live `status`
  (`verified`/`blocked`/`needs_scoping`/`unverified`).
- **`regulator_map`** — 12 course-area → primary-regulator + secondary-validation
  entries, from the cookbook's Regulator Map sheet.
- **`segment_sources`** — per-segment preferred/secondary source lists and tier
  floors, from the Segment Sources sheet.

`retrieval_order` and the `strong_tier`/`medium_tier`/`weak_tier` groups are
**removed**. They encode "one ordered list of sources per course," which is the
model being replaced. Course-level tier labels stop existing.

**Consequence for Hard Constraint 6** (metrics always stratified by tier, never
blended): the strong/medium/weak axis disappears with them. **Signed off
2026-08-07** — the protected metric axis becomes:

```
segment × source_tier
```

using the cookbook's Tier A/B/C/D classification. This preserves what the
constraint actually protects — metrics stay stratified by *source authority* —
while making the number meaningful under an architecture where authority is
per-segment, not per-course.

`strong`/`medium`/`weak` are **not** retained for backward compatibility. Source
tier is now the canonical authority axis; a course-level quality label no longer
means anything once different segments of the same course come from different
tiers.

```
Eligibility          Fees                 Salary
  Tier A → …           Tier A → …           Tier C → …
  Tier B → …           Tier B → …           Tier D → …
  Tier D → …           Tier D → …
```

## Build order

Each phase is independently runnable and verifiable, per the project's
re-runnable-step convention.

| Phase | Work | Depends on |
|-------|------|-----------|
| 1 | Course taxonomy loader; intent/document/registry models; `config/sources.yaml` rebuild; new manifest schema | — |
| 2 | Adapter protocol redesign; port `AICTEAdapter` to it; delete `WikipediaAdapter` and `general_background` | 1 |
| 3 | Self-contained Tier A adapters — UGC, NTA, NIRF, NAAC, NBA, NCS, NSDC, NQR, NSP, Apprenticeship India, NATS. Decision-5 escalation applies per source | 2 |
| 4 | Institution registry — AISHE/UGC HEI/NIRF discovery, entity resolution, offering resolution | 3 |
| 5 | University-backed segments — Curriculum, Fees, Institution & Offering | 4 |
| 6 | Planner + orchestration + intent batching; full 754-course run | 2, and as much of 3–5 as exists |
| 7 | Tier D discovery adapters — Careers360, Shiksha, CollegeDunia, salary portals, all `role: discovery` | 6 |

Phases 3–5 can proceed against hand-written intent fixtures before the planner
exists; only the intent *schema* (phase 1) is a hard prerequisite.

## Verification

Per the project's agent-native verification convention, every phase emits
structured JSON with an explicit pass/fail contract, not prose.

- **Phase 1** — taxonomy loader asserts exactly 754 courses, 750 unique names, 4
  cross-listed, 4,284 alias lines, zero empty-variant rows. These are measured
  values; a mismatch means the file changed and is a hard failure.
- **Phase 2–5** — each adapter ships a live resolution check against real intents,
  reporting `{source_id, intents_attempted, resolved, validated, failed, reasons[]}`.
  Adapters are verified live, not only against mocks — the existing convention,
  and the reason NPTEL's status was corrected from `verified` to `blocked` once a
  plain fetch was tried instead of a JS-rendering one.
- **Phase 6** — a full-run report on the signed-off `segment × source_tier` axis:
  `{segment, source_tier, intents, resolved_authoritative, resolved_secondary_only,
  unresolved, reasons[]}`. Never a single blended number, and never collapsed to a
  course-level quality label.
- **Regression** — a golden set of ~20 courses spanning regulated (medicine, law),
  well-covered (engineering) and genuinely uncovered (animation, vocational) areas.

  **Uncovered courses must resolve to `unresolved`.** The expected path is:

  ```
  Course → no permitted authoritative source found → unresolved
  ```

  If those courses resolve *only* because a Tier D source (Careers360, Shiksha)
  was allowed into a canonical role, **the test fails**. This specifically guards
  against the old pipeline's behaviour:

  ```
  try source → fail → try another → eventually find anything → SUCCESS
  ```

  Lack of authoritative coverage is a **valid outcome**, not a system failure. A
  run where every course fully resolves is evidence of tier leakage, not success.

An expected-failure baseline carries over: Aerospace Engineering has no published
AICTE model curriculum. Its Curriculum intent against AICTE must stay unresolved
rather than fuzzy-matching Textile Engineering at 0.69.

## Open questions

1. **Typical vs per-institution curriculum.** Cookbook S06 says "build a typical
   curriculum from multiple institutions; preserve exact institution syllabus
   separately." Does a course page show a synthesised typical curriculum,
   per-institution records, or both?
2. **Institution count per course.** NIRF top-N bounds it, but N is unset, and NIRF
   does not rank every discipline.
3. **The 4 unmapped segments** — S02 overview, S14 skills, S18 further-study, S19
   reviews. On the client's demo page, absent from the field directory.
4. **Playwright.** Not yet needed, but likely for BCI/NPTEL/AISHE if the header and
   open-data routes fail. A real new dependency requiring approval before adoption.

## Resolved

- **754 vs the client's stated 629 target** — resolved 2026-08-07: proceed with the
  full 754-course taxonomy. The 629 figure is not pursued and should not be treated
  as a target elsewhere in the project docs. `CLAUDE.md`, `README.md` and
  `WALKTHROUGH.md` updated accordingly.
- **Hard Constraint 6 restratification** — signed off 2026-08-07. Metric axis is
  `segment × source_tier` (Tier A/B/C/D); `strong`/`medium`/`weak` retired outright,
  not kept for compatibility. See Configuration rebuild above.
- **Regression semantics** — signed off 2026-08-07. `unresolved` is a valid
  outcome; a golden-set run in which uncovered courses resolve is a **test
  failure**, not a pass. See Verification above.
- **Phase-1 hard assertions** — signed off 2026-08-07: `aliases = 4,284`,
  `non-bullet lines = 10`. The earlier 4,254 / 9 values are wrong and must not
  appear in the phase-1 spec or in validation logic.
