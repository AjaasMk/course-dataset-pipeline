# course-dataset-pipeline

Structured, fixed-schema JSON dataset for Indian courses, grounded entirely in
official regulator/university sources. Pilot: 50 courses. Eventual target: 629.

## Hard constraints

1. No manual retrieval, matching, or writing anywhere in the pipeline.
2. Every generated field carries `source_refs` pointing to a real retrieved
   document chunk.
3. **Source lineup is tiered by category** (see `config/sources.yaml`):
   `regulatory_primary` (AICTE/NMC/BCI/UGC — authoritative, use as-is),
   `syllabus_supplement` (NPTEL — curriculum detail), `fact_supplement_
   independent_writing_required` (Careers360, Coursera, edX, university
   sites — **facts only, never copied/paraphrased sentences**, gated by an
   n-gram/similarity check against the source text on top of the normal
   faithfulness check), `general_background` (Wikipedia, CC BY-SA —
   separate license basis, needs attribution), `aggregate_stats_only`
   (AISHE/AICTE — counts, never from an aggregator), `career_info` (NCS).
   Revises the original "regulator-only" rule: the safeguard that makes
   fact-supplement sources safe is the independent-writing requirement +
   similarity check, not their absence.
   **Retrieval order (2026-07-17):** `fact_supplement_independent_writing_
   required` (Careers360) is tried FIRST in every tier, ahead of
   `regulatory_primary` — including engineering, where AICTE is verified and
   working. Regulator adapters for medicine/law/commerce (NMC/BCI/UGC) are
   blocked or unverified (JS SPAs, CDN bot-blocks), while Careers360 works
   uniformly across tiers; this is an accepted tradeoff for retrieval
   simplicity over "strong tier = regulator-sourced" (see constraint 6).
4. No field fabrication. Ungroundable fields are `null` and flagged for
   review — never a plausible-sounding guess.
5. Idempotent: re-running on unchanged sources must not duplicate records or
   reprocess unnecessarily (hash-based diffing).
6. Metrics are always reported stratified by source-quality tier
   (strong/medium/weak) — never blended into one number. **Exception:** since
   Careers360 is now tried before the regulator in every tier, strong/medium
   tier results may be regulator-backed or Careers360-backed interchangeably
   — the tier label no longer implies "regulator-sourced."

## Pilot scope — 50 courses, stratified

| Tier   | Category                        | Count | Source          |
|--------|----------------------------------|-------|------------------|
| Strong | Engineering And Architecture     | 20    | AICTE            |
| Strong | Medicine And Allied Sciences     | 10    | NMC              |
| Medium | Commerce/Management              | 5     | UGC (+ AICTE for MBA) |
| Medium | Law                               | 5     | BCI              |
| Weak   | Animation/Media/Arts             | 10    | no regulator — scoped university search |

Weak tier is deliberately included to find where automation breaks, not to
avoid it.

## Pipeline architecture

```
STAGE 1 — RETRIEVE   crawl regulator listing page -> {branch: doc_url} index,
                      fuzzy-match course name -> download (idempotent)
STAGE 2 — EXTRACT     chunk doc -> LLM structured extraction (CourseDetail),
                      every field cites source_refs
STAGE 3 — VALIDATE    automated: schema validity, field completeness,
                      faithfulness (NLI/LLM-judge), citation validity,
                      retrieval precision. Below threshold -> review_queue.
STAGE 4 — PERSIST      validated record -> Postgres (source of truth) ->
                      embed -> Chroma
STAGE 5 — SERVE        FastAPI: browse/filter (Postgres), search (Chroma +
                      rerank, ranked results only — no generation yet)
STAGE 6 — OBSERVE      Langfuse trace per run, stratified by tier
```

## Stack

Python 3.11 · requests/beautifulsoup4/rapidfuzz (retrieval) · YAML source
config · LangChain (structured extraction) · LangGraph (fixed-node
orchestration — not autonomous agents) · Pydantic (validation) ·
sentence-transformers + NLI cross-encoder (faithfulness) · PostgreSQL ·
ChromaDB · FastAPI · Langfuse · Pytest · Docker + docker-compose ·
GitHub Actions (monthly re-crawl, hash-diffed)

## Status

**Built:**
- `src/schema.py` — `CourseDetail`, `SourceCategory`, `SourceRef`,
  `SourceType`, `ManifestEntry` Pydantic models.
- `config/sources.yaml` — source registry by tier, with `retrieval_order`
  (Careers360-first, see constraint 3).
- `src/retrieve/base.py` — `SourceAdapter` `Protocol`
  (`build_index()`/`match()`/`download()`).
- `src/retrieve/aicte.py` — `AICTEAdapter`, engineering tier,
  `regulatory_primary`. **Verified live**: `build_index()`, `match()`,
  `download()` all confirmed working against the real AICTE site. Covers 4
  of 5 pilot test courses; **Aerospace Engineering has no published AICTE
  model curriculum** — an expected `no_source_found` case, not a bug
  (reconfirmed live: matches "Textile Engineering" at confidence 0.69).
- `src/retrieve/careers360.py` — `Careers360Adapter`,
  `fact_supplement_independent_writing_required`. **Verified live** the
  same way. Careers360 responses use chunked transfer encoding — no
  `Content-Length` header, so `ManifestEntry.content_length` is `None` for
  those rows (not a bug).
- `src/retrieve/manifest.py` — SQLite manifest (`data/manifest.db`),
  idempotent on `(course_name, matched_url)`.
- 22 tests passing (`pytest`), stdlib `sqlite3` only — no new dependency
  for the manifest.
- `pyproject.toml` — deps for the retrieve stage only (pydantic, requests,
  beautifulsoup4, rapidfuzz, pyyaml, pytest).

**Not built yet:**
- Adapters for NMC (medicine, `needs_scoping`), BCI (law, `blocked` — JS
  SPA), UGC (commerce/management, `blocked` — CDN bot-block), NPTEL
  (`blocked` — JS SPA), AISHE (`unverified`), Coursera/edX. See
  `config/sources.yaml` status notes before attempting any of these — do
  not build against unverified page structure.
- NCS (career info) — doesn't fit the `SourceAdapter` shape
  (course-to-sector matching isn't fuzzy string matching); design deferred.
- **Stage 1 orchestration** — nothing yet consumes `retrieval_order`; no
  code walks a course through its tier's source sequence end to end.
- The actual 50-course pilot list as data (currently only the table above,
  not a file).
- Stages 2–6 (extract/validate/persist/serve/observe).
