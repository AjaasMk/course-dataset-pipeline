# course-dataset-pipeline

Structured, fixed-schema JSON dataset for Indian courses, grounded entirely in
official regulator/university sources. Pilot: 50 courses. Eventual target: 629.

## Hard constraints

1. No manual retrieval, matching, or writing anywhere in the pipeline.
2. Every generated field carries `source_refs` pointing to a real retrieved
   document chunk.
3. Only primary/official sources are used as grounding material: government
   regulators (AICTE, NMC, BCI, UGC, AISHE, NIRF) and, where no regulator
   exists, university syllabus pages restricted to `.ac.in` / `.edu` domains.
   Competitor catalog content (e.g. Careers360) is never copied or paraphrased.
4. No field fabrication. Ungroundable fields are `null` and flagged for
   review — never a plausible-sounding guess.
5. Idempotent: re-running on unchanged sources must not duplicate records or
   reprocess unnecessarily (hash-based diffing).
6. Metrics are always reported stratified by source-quality tier
   (strong/medium/weak) — never blended into one number.

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
- `src/schema.py` — `CourseDetail` and `ManifestEntry` Pydantic models.
- `config/sources.yaml` — source registry by tier.
  - `strong_tier.engineering` (AICTE): **verified real**,
    `https://www.aicte.gov.in/education/model-syllabus` lists branch names
    each linked to a model-curriculum PDF. Covers 4 of 5 pilot test courses;
    **Aerospace Engineering has no published AICTE model curriculum** — an
    expected `no_source_found` case, not a bug.
  - `strong_tier.medicine` (NMC), `medium_tier.law` (BCI),
    `medium_tier.commerce_management` (UGC): URLs corrected from originally
    broken ones, but **not yet verified for page structure** — marked `TODO`,
    do not build those adapters against them without re-checking.
  - `weak_tier`: scoped-search strategy only (`.ac.in`/`.edu`), no fixed URL.
- `pyproject.toml` — deps for the retrieve stage only (pydantic, requests,
  beautifulsoup4, rapidfuzz, pyyaml, pytest).

**Not built yet:** `src/retrieve/base.py` (SourceAdapter interface — design
proposed, not written), `src/retrieve/aicte.py`, extract/validate/persist/
serve stages, tests, Docker, CI.

**Current task:** implement `AICTEAdapter.build_index()` and `.match()`
against the engineering tier only. `download()` intentionally deferred.
Test set: Mechanical, Civil, Computer Science, Electrical, Aerospace
Engineering — stop after printing matched URLs + confidence scores for
manual review.
