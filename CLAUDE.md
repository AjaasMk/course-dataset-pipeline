# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that builds a **fixed-schema JSON dataset of Indian courses**, grounded
entirely in official regulator/university sources. Pilot = 50 courses (stratified),
eventual target = 629. `README.md` is the authoritative spec; read it before making
design decisions.

## Hard constraints (design laws — not preferences)

These are non-negotiable and shape every stage. Violating one is a bug even if the
code "works":

1. **No manual retrieval, matching, or writing anywhere.** The pipeline must be
   fully automated end to end.
2. **Every generated field carries `source_refs`** pointing to a real retrieved
   document chunk. A field with content but no citation is invalid.
3. **Source lineup is tiered by category** (see `config/sources.yaml`):
   `regulatory_primary` (AICTE/NMC/BCI/UGC — authoritative, use as-is),
   `syllabus_supplement` (NPTEL — curriculum detail), `fact_supplement_
   independent_writing_required` (Careers360, Coursera, edX, university
   sites — **facts only, never copied/paraphrased sentences**, gated by the
   similarity check in Validation rules below), `general_background`
   (Wikipedia, CC BY-SA — separate license basis, needs attribution),
   `aggregate_stats_only` (AISHE/AICTE — counts, never from an aggregator),
   `career_info` (NCS). **This supersedes the original "regulator-only"
   rule** — the safeguard that makes fact-supplement sources safe to use is
   the independent-writing requirement + similarity check, not their
   absence.
4. **No fabrication.** Ungroundable fields are `null` and flagged for review —
   never a plausible-sounding guess. Prefer explicit `null` + flag over a filled
   value you can't cite.
5. **Idempotent** via hash-based diffing: re-running on unchanged sources must not
   duplicate records or reprocess unnecessarily.
6. **Metrics are always reported stratified by source-quality tier**
   (strong/medium/weak) — never blended into a single number. **Exception, by
   deliberate decision (2026-07-17):** since retrieval order now tries
   Careers360 before the regulator in every tier (see below), strong/medium
   tier results may be regulator-backed or Careers360-backed interchangeably
   — the tier label no longer implies "regulator-sourced." This blending is
   an accepted tradeoff for retrieval simplicity, not an oversight of this
   constraint.

The **weak tier is included on purpose** — to find where automation breaks, not to
avoid it. Don't "fix" weak-tier failures by falling back to manual or non-official
sources; a surfaced failure there is a valid result.

**Retrieval order (2026-07-17 decision):** `config/sources.yaml`'s
`retrieval_order` tries `fact_supplement_independent_writing_required`
(Careers360) FIRST in every tier, ahead of `regulatory_primary` — including
engineering, where AICTE is verified and working. Rationale: NMC/BCI/UGC are
blocked or unverified (JS SPAs, CDN bot-blocks, ambiguous doc structure),
while Careers360 already works uniformly across tiers — rather than block
retrieval on hard-to-access regulator sites, Careers360 is now the default
primary source everywhere. **Not yet consumed by any adapter** — this is a
config-level intent, not runtime behavior, until Stage 1 orchestration is
written.

## Tier model (drives everything)

Sources, metrics, and expectations are organized by tier in `config/sources.yaml`:

- **strong** — engineering (AICTE), medicine (NMC)
- **medium** — commerce/management (UGC, +AICTE for MBA), law (BCI)
- **weak** — animation/media/arts: **no regulator**, scoped search only
  (`method: scoped_search`, `allowed_domains: [.ac.in, .edu]`, no fixed URL)

## Commands

Environment: Python **3.11+** (host has 3.13). On this Windows host the interpreter
is `python`, **not** `python3`.

```bash
pip install -e ".[dev]"          # editable install + dev deps (pytest)
pytest                            # run all tests
pytest tests/test_x.py::test_y -v # run a single test
```

`pyproject.toml` sets `pythonpath = ["."]`, so tests import as `src.schema` from the
repo root. No linter/formatter is configured yet — don't assume one exists.

## Architecture

Six fixed stages (see `README.md` for the full diagram). LangGraph is used for
**fixed-node orchestration, not autonomous agents** — the graph topology is
predetermined per stage.

```
STAGE 1 RETRIEVE  crawl regulator listing page -> {branch: doc_url} index,
                  fuzzy-match course name (rapidfuzz) -> download (idempotent)
STAGE 2 EXTRACT   chunk doc -> LLM structured extraction into CourseDetail,
                  every field cites source_refs
STAGE 3 VALIDATE  automated gate: schema validity, completeness, faithfulness
                  (NLI/LLM-judge), citation validity, retrieval precision.
                  Below threshold -> review_queue
STAGE 4 PERSIST   validated record -> Postgres (source of truth) -> embed -> Chroma
STAGE 5 SERVE     FastAPI: browse/filter (Postgres), search (Chroma + rerank);
                  ranked results only, no generation yet
STAGE 6 OBSERVE   Langfuse trace per run, stratified by tier
```

## Validation rules

Stage 3 runs the checks listed in Architecture above (schema validity,
completeness, faithfulness, citation validity, retrieval precision) for every
field. **Additional rule, added with the fact-supplement source lineup**
(Hard Constraint 3, `config/sources.yaml`):

- For any field whose `source_refs` includes an entry with
  `category == fact_supplement_independent_writing_required` (Careers360,
  Coursera, edX, university sites), Stage 3 must **also** run an
  n-gram/similarity check between the generated field text and that source's
  original text — on top of, not instead of, the faithfulness check.
- A field can be faithful (factually correct per its citation) and still
  **fail** this check if it's structurally too close to the source's original
  wording. Failing routes to `review_queue` for rewrite — it is never
  auto-published, and it is never silently reworded and republished without
  going through the queue.
- This check does not apply to `regulatory_primary`, `syllabus_supplement`,
  `general_background`, `aggregate_stats_only`, or `career_info` refs — the
  independent-writing risk is specific to competitor/aggregator catalogs.

### Retrieval adapter pattern

Each source type is implemented as a `SourceAdapter` (`src/retrieve/base.py`,
a `Protocol`). The contract is `build_index()` (crawl listing page →
`{branch: doc_url}`), `match()` (fuzzy-map a course name to an indexed URL with
a confidence score), and `download()` (idempotent fetch + hash + save + manifest
write — see Data model below). Depend on this interface, not on any concrete
adapter, so new regulators/sources can be added without touching later stages.

Two adapters exist: `AICTEAdapter` (`src/retrieve/aicte.py`, engineering,
`regulatory_primary`, verified live) and `Careers360Adapter`
(`src/retrieve/careers360.py`, `fact_supplement_independent_writing_required`,
verified live). Both fully implement `build_index()`/`match()`/`download()`.
`build_index()`/`match()` are deliberately independent per adapter (no shared
base implementation) — `download()` follows the same pattern (see
`docs/superpowers/specs/2026-07-17-stage1-download-idempotency-design.md`).
This duplication is accepted for 2 adapters; extract a shared helper if a
third adapter arrives.

### Data model — `src/schema.py`

- `CourseDetail` — the output record. Most fields are `Optional` and default to
  `None` (constraint #4). Note: `colleges_available` comes from **AISHE, not
  curriculum docs** (see inline comment) — don't populate it from an extracted
  syllabus. `source_refs` is `list[SourceRef]`, not `list[str]` — each entry
  is tagged with `field` (which `CourseDetail` field it grounds) and
  `category` (drives the Validation rules similarity check above). A field
  can have more than one `SourceRef`.
- `ManifestEntry` — one retrieval record per course: `tier`, `source_type`
  (`SourceType` enum: `regulator_pdf | regulator_webpage | university_webpage |
  aggregator_webpage | none`), `matched_url`, `local_path`, `file_hash` (for
  idempotency), `match_confidence`, `retrieved_at`, plus HTTP metadata
  (`content_type`, `content_length`, `http_status`) captured on successful
  download only — a failed download writes no manifest row at all.

### Data / persistence

`data/` is **gitignored** — raw docs (`data/raw/`) and the manifest
(`data/manifest.db`) are regenerable pipeline output, not source. Postgres is the
eventual source of truth; Chroma holds embeddings for search.

`src/retrieve/manifest.py` is the only code that touches `data/manifest.db`
(SQLite, stdlib `sqlite3`, no new dependency) — `get_entry(course_name,
matched_url)` / `insert_entry(entry)`. Idempotency is keyed on
`(course_name, matched_url)`: if a manifest row already exists for that pair,
`download()` returns it without making an HTTP request at all — re-running on
an unchanged source does not re-fetch or duplicate records. Files save to
`data/raw/<tier>/<source_type>/<course_name_slug>.<ext>`.

## Current status & gotchas

**Built:** `src/schema.py` (`CourseDetail`, `SourceCategory`, `SourceRef`,
`SourceType`, `ManifestEntry`), `config/sources.yaml`, the `SourceAdapter`
interface (`src/retrieve/base.py`), `AICTEAdapter` and `Careers360Adapter`
(both adapters fully implement `build_index()`/`match()`/`download()`),
`src/retrieve/manifest.py` (SQLite manifest, idempotency). 22 tests passing
(`tests/test_schema.py`, `tests/test_manifest.py`, `tests/test_aicte.py`,
`tests/test_careers360.py`). `pyproject.toml` currently declares deps for the
**retrieve stage only** (pydantic, requests, beautifulsoup4, rapidfuzz, pyyaml,
pytest) — later stages' deps aren't added yet; `sqlite3` is stdlib, no new
dependency needed for the manifest.

**Not built:** NMC/BCI/UGC/NPTEL/AISHE adapters (blocked/unverified — see
below), Coursera/edX adapters, NCS (career info — doesn't fit the
`SourceAdapter` shape, see `config/sources.yaml`), Stage 1 orchestration
(nothing yet consumes `retrieval_order`), Stages 2–6.

**Source verification state (critical):**
- `strong_tier.engineering` (AICTE) and `fact_supplement.Careers360` are both
  **verified live** (not just unit-tested against mocks) — `build_index()`,
  `match()`, and `download()` all confirmed working end to end against the
  real sites as of 2026-07-17.
- **Aerospace Engineering has no published AICTE model curriculum** — reconfirmed
  live (matched "Textile Engineering" at confidence 0.69, correctly signaling
  no real match). This is an expected `no_source_found` case, **not a bug**.
- NMC (`needs_scoping`), BCI (`blocked`, JS SPA), UGC (`blocked`, CDN bot-block),
  NPTEL (`blocked`, JS SPA), AISHE (`unverified`) are all still **not usable by
  a plain `requests`+`bs4` adapter** — see `config/sources.yaml` status notes.
  Retrieval order now routes around this by trying Careers360 first in every
  tier (see Hard Constraint 6 / Retrieval order note above) rather than
  requiring these to be fixed first.
- Careers360 responses use chunked transfer encoding in practice — no
  `Content-Length` header, so `ManifestEntry.content_length` is `None` for
  those rows. Confirmed live, not a bug.

## Notes

- `docs/architecture.html` is a **personal, gitignored reference** — not part of the
  tracked project and not the spec. Treat `README.md` as authoritative.
