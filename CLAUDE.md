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
   (strong/medium/weak) — never blended into a single number.

The **weak tier is included on purpose** — to find where automation breaks, not to
avoid it. Don't "fix" weak-tier failures by falling back to manual or non-official
sources; a surfaced failure there is a valid result.

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

Each source type is implemented as a `SourceAdapter` (interface **designed but not
yet written** — `src/retrieve/base.py`). The contract is `build_index()` (crawl
listing page → `{branch: doc_url}`) and `match()` (fuzzy-map a course name to an
indexed URL with a confidence score). Depend on this interface, not on any concrete
adapter, so new regulators/sources can be added without touching later stages.

### Data model — `src/schema.py`

- `CourseDetail` — the output record. Most fields are `Optional` and default to
  `None` (constraint #4). Note: `colleges_available` comes from **AISHE, not
  curriculum docs** (see inline comment) — don't populate it from an extracted
  syllabus. `source_refs` is `list[SourceRef]`, not `list[str]` — each entry
  is tagged with `field` (which `CourseDetail` field it grounds) and
  `category` (drives the Validation rules similarity check above). A field
  can have more than one `SourceRef`.
- `ManifestEntry` — one retrieval record per course: `tier`, `source_type`
  (`regulator_pdf | regulator_webpage | university_webpage | none`), `matched_url`,
  `file_hash` (for idempotency), `match_confidence`.

### Data / persistence

`data/` is **gitignored** — raw docs (`data/raw/`) and the manifest
(`data/manifest.db`) are regenerable pipeline output, not source. Postgres is the
eventual source of truth; Chroma holds embeddings for search.

## Current status & gotchas

**Built:** `src/schema.py`, `config/sources.yaml`. `pyproject.toml` currently
declares deps for the **retrieve stage only** (pydantic, requests, beautifulsoup4,
rapidfuzz, pyyaml, pytest) — later stages' deps aren't added yet.

**Not built:** the `SourceAdapter` interface, any adapter, and stages 2–6.

**Source verification state (critical):**
- Only `strong_tier.engineering` (AICTE) is **verified real** — the listing page
  lists branch names each linked to a model-curriculum PDF.
- **Aerospace Engineering has no published AICTE model curriculum** — this is an
  expected `no_source_found` case, **not a bug**.
- `sources.yaml` `TODO` markers (NMC, BCI, UGC) have **URLs corrected but page
  structure not yet verified**. Do **not** build adapters against those URLs
  without re-checking the actual page layout first.

**Current task:** implement `AICTEAdapter.build_index()` and `.match()` for the
**engineering tier only**. `download()` is intentionally deferred. Test set:
Mechanical, Civil, Computer Science, Electrical, Aerospace Engineering — stop after
printing matched URLs + confidence scores for manual review.

## Notes

- `docs/architecture.html` is a **personal, gitignored reference** — not part of the
  tracked project and not the spec. Treat `README.md` as authoritative.
