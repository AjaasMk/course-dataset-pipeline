# course-dataset-pipeline

Structured, fixed-schema JSON dataset for Indian courses, grounded entirely in
official regulator/university sources. Pilot: 50 courses. Eventual target: 629.

## Hard constraints

1. No manual retrieval, matching, or writing anywhere in the pipeline.
2. **Revised (2026-07-21): dropped.** Originally: every generated field
   carries `source_refs` pointing to a real retrieved document chunk. This
   project's output is course content for a client-facing site, not an
   auditable research dataset — per-field citation tracking (and the Stage 3
   faithfulness/citation-validity checks it enabled) was judged not worth
   its cost, and is removed. Retrieval (Stage 1) is unaffected — generation
   still starts from real fetched pages; only the after-the-fact citation
   record is gone. `SourceRef` no longer exists in `src/schema.py`.
3. **Source lineup is tiered by category** (see `config/sources.yaml`):
   `regulatory_primary` (AICTE/NMC/BCI/UGC — authoritative, use as-is),
   `syllabus_supplement` (NPTEL — curriculum detail), `fact_supplement_
   independent_writing_required` (Careers360, Coursera, edX, university
   sites), `general_background` (Wikipedia, CC BY-SA — separate license
   basis, needs attribution), `aggregate_stats_only` (AISHE/AICTE — counts,
   never from an aggregator), `career_info` (NCS). Still governs *retrieval
   order* (which source is tried first per tier) even though per-field
   citation tracking is gone (constraint 2). **Revised (2026-07-21):** the
   independent-writing/similarity-check safeguard on
   `fact_supplement_independent_writing_required` no longer applies, since
   it depended on Stage 3 citation validation (now dropped) — accepted,
   deliberate risk of the 2026-07-21 decision.
   **Retrieval order (2026-07-17, revised same day):** `fact_supplement_
   independent_writing_required` (Careers360) is tried FIRST in every tier,
   ahead of `regulatory_primary` — including engineering, where AICTE is
   verified and working. Regulator adapters for medicine/law/commerce (NMC/
   BCI/UGC) are blocked or unverified (JS SPAs, CDN bot-blocks), while
   Careers360 works uniformly across tiers; this is an accepted tradeoff for
   retrieval simplicity over "strong tier = regulator-sourced" (see
   constraint 6). `general_background` (Wikipedia) is the final fallback for
   medium/weak tier if both regulator and Careers360 fail — see constraint 6
   and the Pilot scope note below for the weak-tier policy this revises.
4. **Revised (2026-07-21): fabrication is now allowed for ungrounded gaps.**
   Originally: no field fabrication — ungroundable fields are `null` and
   flagged for review, never a plausible-sounding guess. Reversed by the
   same 2026-07-21 decision as constraint 2: when the retrieved source is
   silent on a fact, the model may fill it from general/typical knowledge
   instead of returning `null`. Known consequence: this undercuts the
   weak-tier intent below — a weak-tier course with no real source match now
   gets a fluent, unverifiable answer instead of a surfaced
   `no_source_found` failure. Accepted tradeoff; revisit if it masks too
   much real automation-breakage signal.
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
avoid it. **Revised (2026-07-17):** Wikipedia (`general_background`) is now
an explicit last-resort fallback after regulator and Careers360 both fail
(see constraint 3/6) — a deliberate, accepted tradeoff between reducing
`no_source_found` counts and keeping automation failures fully visible;
revisit if it later masks too much real signal.

## Pipeline architecture

```
STAGE 1 — RETRIEVE   crawl regulator listing page -> {branch: doc_url} index,
                      fuzzy-match course name -> download (idempotent)
STAGE 2 — EXTRACT     chunk doc -> LLM structured extraction (CourseDetail),
                      no per-field citation tracking (revised 2026-07-21)
STAGE 3 — VALIDATE    automated: schema validity, field completeness,
                      retrieval precision. Faithfulness/citation validity
                      dropped with source_refs (2026-07-21). Below
                      threshold -> review_queue.
STAGE 4 — PERSIST      validated record -> Postgres (source of truth) ->
                      embed -> Chroma
STAGE 5 — SERVE        FastAPI: browse/filter (Postgres), search (Chroma +
                      rerank, ranked results only — no generation yet)
STAGE 6 — OBSERVE      Langfuse trace per run, stratified by tier
```

## Running with Docker

Every push to `main` automatically builds and publishes the image to
GitHub Container Registry (see `.github/workflows/docker-publish.yml`) —
tagged both `:latest` and with the exact commit SHA it was built from. The
package is **private**: pulling it requires a GitHub personal access token
(classic, scope `read:packages`) and being granted access to the package
(repo collaborators get this automatically; anyone else needs to be added
under the package's own access settings on GitHub).

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <your-github-username> --password-stdin
docker pull ghcr.io/ajaasmk/course-dataset-pipeline:latest
```

Everything below works identically whether your image is the one you pulled
(tag it locally first: `docker tag ghcr.io/ajaasmk/course-dataset-pipeline:latest course-dataset-pipeline`)
or one you build yourself:

```bash
docker build -t course-dataset-pipeline .
```

Verify your `ANTHROPIC_API_KEY` (in `.env`, project root) is valid and has a
usable credit balance — no pipeline cost, just a key check:

```bash
docker run --rm --env-file .env course-dataset-pipeline python scripts/verify_anthropic_key.py
```

Run the test suite inside the container (no `.env` needed — all 129 tests
run against fakes/mocks, zero real API calls):

```bash
docker run --rm course-dataset-pipeline pytest
```

Each pipeline stage is run explicitly, with `data/` mounted from the host so
state (the manifest, downloaded documents, chunks, extracted output)
persists across separate `docker run` invocations — the container itself is
stateless:

```bash
# Stage 1 — Retrieve
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" course-dataset-pipeline python -m src.retrieve.batch

# Stage 2 — Chunk
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" course-dataset-pipeline python -m src.extract.run_chunking

# Stage 2 — Extract (billed — verify credit balance first)
docker run --rm --env-file .env -v "$(pwd)/data:/app/data" course-dataset-pipeline python -m src.extract.batch_extract
```

**Windows + Git Bash note:** Git Bash's MSYS layer auto-converts `/app/data`
into a Windows path before Docker sees it, silently breaking the volume
mount (confirmed live — the container ran but wrote to its own empty
`data/manifest.db` instead of the host's, without erroring). Fix by
prefixing the command:

```bash
MSYS_NO_PATHCONV=1 docker run --rm --env-file .env -v "$(pwd)/data:/app/data" course-dataset-pipeline python -m src.retrieve.batch
```

PowerShell doesn't have this issue — use `${PWD}` in place of `$(pwd)` and no
prefix is needed.

## Stack

Python 3.11 · requests/beautifulsoup4/rapidfuzz (retrieval) · YAML source
config · LangChain (structured extraction) · LangGraph (fixed-node
orchestration — not autonomous agents) · Pydantic (validation) ·
sentence-transformers + NLI cross-encoder (faithfulness) · PostgreSQL ·
ChromaDB · FastAPI · Langfuse · Pytest · Docker + docker-compose ·
GitHub Actions (monthly re-crawl, hash-diffed)

## Status

**Built:**
- `src/schema.py` — `CourseDetail` (revised 2026-07-21: richer nested
  shape — `Eligibility`, `EntranceExams`, `Fees`/`FeeRange`,
  `CollegesAvailable`, `JobProfile`, `Syllabus`/`SyllabusSemester`,
  `TopCollege`, `FAQ` — no `source_refs`; a `Seo` model was proposed in the
  same revision and then removed as unrequested scope), `SourceCategory`,
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
