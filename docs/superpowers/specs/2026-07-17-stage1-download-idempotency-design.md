# Stage 1 Retrieve: `download()` + idempotency — Design

Date: 2026-07-17
Status: Approved

## Context

Stage 1 (Retrieve) per `README.md`/`CLAUDE.md` is: crawl regulator listing page →
`{branch: doc_url}` index, fuzzy-match course name (rapidfuzz) → download (idempotent).

`build_index()` and `match()` are already implemented and working for both
`AICTEAdapter` (`src/retrieve/aicte.py`, regulatory_primary/engineering tier) and
`Careers360Adapter` (`src/retrieve/careers360.py`, fact_supplement tier). `download()`
is stubbed (`raise NotImplementedError`) on both. This spec covers finishing
`download()` for both adapters, with hash-based idempotency (Hard Constraint 5) and
manifest persistence (`data/manifest.db`, per `CLAUDE.md`).

## Scope

- `download()` implemented on `AICTEAdapter` and `Careers360Adapter`.
- Shared manifest module (`src/retrieve/manifest.py`) backed by SQLite.
- `ManifestEntry.source_type` becomes a real `Enum`, gaining a new
  `AGGREGATOR_WEBPAGE` value for Careers360/Coursera/edX-style sources.
- Out of scope: NMC/BCI/UGC adapters (page structure unverified — see
  `config/sources.yaml`), Stage 2+ (Extract/Validate/Persist/Serve/Observe), Coursera/edX
  adapters themselves (only the schema value is added now, not the adapters).

## Architecture

```
download(match: SourceMatch, tier: str) -> ManifestEntry
```

1. Check the manifest: does a row already exist for `(course_name, matched_url)`?
   If yes → skip the HTTP request, return the existing `ManifestEntry`. This is the
   idempotency gate — re-running on an unchanged source does not re-fetch or
   duplicate records (Hard Constraint 5).
2. If not: `requests.get(match.matched_url)`, compute `sha256` of the response
   bytes.
3. Write the content to `data/raw/<tier>/<source_type>/<course_name_slug>.<ext>`
   — `.pdf` for AICTE, `.html` for Careers360. Content is saved as-is; Stage 1 does
   not parse or normalize it (that's Stage 2's job).
4. Insert a new row into `data/manifest.db` (SQLite): course_name, tier,
   source_type, matched_url, local_path, file_hash, match_confidence, retrieved_at,
   content_type, content_length, http_status (see "Manifest fields" below).
5. Return the `ManifestEntry`.

`src/retrieve/manifest.py` owns all SQLite access (`get_entry(course_name, url)`,
`insert_entry(entry)`) so both adapters share one code path instead of each rolling
its own SQL. This is the one shared piece of retrieve-stage logic; `build_index()`
and `match()` stay adapter-local per the existing `SourceAdapter` pattern.

## Schema change (`src/schema.py`)

```python
class SourceType(str, Enum):
    REGULATOR_PDF = "regulator_pdf"
    REGULATOR_WEBPAGE = "regulator_webpage"
    UNIVERSITY_WEBPAGE = "university_webpage"
    AGGREGATOR_WEBPAGE = "aggregator_webpage"  # new — Careers360/Coursera/edX
    NONE = "none"
```

`ManifestEntry.source_type: str` becomes `ManifestEntry.source_type: SourceType`.
`AICTEAdapter.download()` always produces `REGULATOR_PDF`; `Careers360Adapter.download()`
always produces `AGGREGATOR_WEBPAGE`.

## Manifest fields (added)

Three fields are added to `ManifestEntry`, captured from the `requests.Response`
at download time:

```python
class ManifestEntry(BaseModel):
    ...
    content_type: Optional[str] = None    # response.headers.get("Content-Type")
    content_length: Optional[int] = None  # response.headers.get("Content-Length"); not always sent (e.g. chunked encoding) -> None
    http_status: Optional[int] = None     # response.status_code
    retrieved_at: str                     # already existed; ISO 8601 timestamp
```

These are only ever populated on a successful download (see "Error handling"
below) — a manifest row always reflects a real, saved file, never a failed
attempt. `http_status` will therefore always be 2xx in practice, but is stored
explicitly rather than assumed, since it's cheap and makes the manifest
self-describing without cross-referencing code.

## Error handling

- HTTP failure (timeout, 404, 5xx) on `requests.get` → propagates, no silent
  fallback, and no manifest row is written. A failed download is a failed
  download (Hard Constraint 4 — no fabrication; fail loud, per project
  conventions). This was an explicit choice on revisiting the design: failed
  attempts are not logged to the manifest with their status code, to keep
  every manifest row representing a real, saved file rather than a mix of
  successes and failures. Revisit if failure visibility becomes a real need.
- Manifest DB missing on first run → `manifest.py` creates the table via
  `CREATE TABLE IF NOT EXISTS`, no separate init step required.

## Idempotency semantics

Idempotency is keyed on `(course_name, matched_url)` already present in the
manifest — if found, the HTTP request is skipped entirely. This trades off
detecting silent source-content edits (same URL, changed PDF) against fast,
network-call-free re-runs. Accepted trade-off for this pass; revisit if silent
source edits become a real problem.

## File layout

`data/raw/<tier>/<source_type>/<course_name_slug>.<ext>` — e.g.
`data/raw/engineering/regulator_pdf/mechanical_engineering.pdf`. Human-browsable,
mirrors the tier model in `config/sources.yaml`.

## Testing

- `tests/test_manifest.py` — `get_entry`/`insert_entry` against a temp SQLite file
  (pytest `tmp_path` fixture), real SQLite, no mocking. Includes round-tripping
  the new `content_type`/`content_length`/`http_status` fields.
- `tests/test_aicte.py` (new) and `tests/test_careers360.py` (extended) — mock
  `requests.get` (stdlib `unittest.mock.patch`, no new dependency) to verify:
  first download writes file + manifest row with `content_type`/`content_length`/
  `http_status` correctly populated from the mocked response headers/status;
  second call for the same course+URL skips the HTTP call (idempotency); a
  different course/URL triggers a real download.
- Existing `__main__` smoke-test blocks in each adapter are extended to call
  `download()`, same pattern as their existing `match()` smoke test.
