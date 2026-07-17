# Stage 1 Orchestration (`retrieve_course`) — Design

Date: 2026-07-17
Status: Approved

## Context

Stage 1 (Retrieve) has two working adapters (`AICTEAdapter`, `Careers360Adapter`,
both live-verified) and a declared `retrieval_order` per tier group in
`config/sources.yaml` (strong/medium/weak), but nothing consumes it —
`build_index()`/`match()`/`download()` are only ever called directly, one
adapter at a time, from each adapter's own `__main__` smoke test. This spec
covers the orchestration layer that walks a course through its tier's
declared source sequence: try each source in order, use the first one that
matches with acceptable confidence, fall through otherwise.

## Scope

- One function, `retrieve_course()`, in a new module
  `src/retrieve/orchestrator.py`.
- A one-time index-building step per adapter, run before processing any
  courses.
- A `__main__` smoke test against the same 5 engineering test courses used
  by the existing adapters (Mechanical, Civil, Computer Science, Electrical,
  Aerospace).
- Out of scope, explicitly deferred to a future task once real failure data
  exists: per-course failure isolation in a batch loop, rate-limiting/retry
  on transient HTTP errors, tier-stratified aggregate reporting (Hard
  Constraint 6), and the real 50-course pilot list as data (currently only a
  table in `README.md`).

## Prior-turn corrections captured in this design

Two things surfaced and were corrected before finalizing this design,
recorded here so they aren't silently re-discovered later:

1. **README.md drift.** `README.md` (declared the authoritative spec by
   `CLAUDE.md`) still stated the original "regulator-only, Careers360 never
   copied/paraphrased" rule and a stale `Status` section, predating both the
   tiered-category model and the 2026-07-17 Careers360-first retrieval-order
   decision. Fixed in a prior commit (`docs: sync README ...`) — both docs
   now agree.
2. **LangGraph scope.** The project's stack notes list LangGraph for
   "fixed-node orchestration." This refers to orchestrating the 6 pipeline
   *stages* (Retrieve → Extract → ... → Observe) as graph nodes — not the
   retrieval-order fallthrough *within* Stage 1, which is a small, self-
   contained decision tree. `retrieve_course()` is plain Python control flow;
   no LangGraph dependency is introduced by this task.

## Architecture

```python
def retrieve_course(
    course_name: str,
    category: str,                    # e.g. "engineering" — becomes ManifestEntry.tier
    tier_group: str,                  # e.g. "strong_tier" — selects retrieval_order sequence
    indices: dict,                    # pre-built {adapter: index}, keyed by adapter instance, built once per run
    category_regulators: dict,        # {"engineering": AICTEAdapter(), ...} — regulatory_primary, per category
    fact_supplement_adapters: dict,   # {SourceCategory.FACT_SUPPLEMENT_...: Careers360Adapter()} — category-agnostic
    threshold: float = 0.8,
) -> ManifestEntry | None:
```

Walks `sources.yaml`'s `retrieval_order[tier_group]` in order (a list of
category-name strings, e.g. `["fact_supplement_independent_writing_required",
"regulatory_primary", "syllabus_supplement"]`). For each entry:

1. Resolve the adapter for this entry:
   - `"regulatory_primary"` → look up `category_regulators.get(category)`
     (per-category: only `"engineering"` has an entry today).
   - Any other category name → look up
     `fact_supplement_adapters.get(SourceCategory(entry))` (category-agnostic:
     the same `Careers360Adapter` instance serves every category).
2. No adapter resolved (nothing registered for this entry yet, e.g. NMC for
   medicine) → skip silently, move to the next entry in the order.
3. Adapter resolved → look up its pre-built index in `indices`, call
   `adapter.match(course_name, index)`.
4. `match is None` or `match.confidence < threshold` → treat as no real
   match, move to the next entry.
5. `match.confidence >= threshold` → call `adapter.download(match,
   tier=category)` and return the resulting `ManifestEntry` immediately —
   first acceptable match wins, no further sources are tried.
6. Order exhausted with nothing clearing the threshold → return `None`
   (a `no_source_found` result — the same meaning as today's Aerospace
   Engineering case on AICTE alone, now generalized across the whole order).

## Why explicit parameters, not module-level constants

`src/retrieve/manifest.py`'s `DEFAULT_DB_PATH` and each adapter's `RAW_DIR`
already required careful "resolve at call time, not at def time" handling
purely so tests could `monkeypatch` them (see
`docs/superpowers/specs/2026-07-17-stage1-download-idempotency-design.md`).
`retrieve_course()` takes its registries, indices, and threshold as plain
arguments instead — tests inject fake `SourceAdapter`-shaped objects and a
fake `retrieval_order` dict directly, with no monkeypatching and no risk of
state leaking between tests.

## Index building

`build_index()` performs a real HTTP crawl of a listing page. Building it
fresh per course (5 times for 5 courses, once per adapter each time) would
be redundant network traffic for no benefit — the index doesn't change
within a single run. A separate function builds each adapter's index once:

```python
def build_indices(adapters: list) -> dict:
    """Returns {adapter: adapter.build_index()} for each adapter, once.

    Keyed by adapter instance (default object identity hash/eq — no
    SourceAdapter implementation overrides them), not a string id, so
    callers pass the same instance through to retrieve_course() and the
    lookup just works.
    """
```

The `__main__` smoke test calls this once for the adapters in play
(`AICTEAdapter`, `Careers360Adapter`), then passes the resulting `indices`
dict into every `retrieve_course()` call for the 5 test courses.

## Config: reading `retrieval_order`

`retrieve_course()` takes `tier_group` as a plain string parameter rather
than deriving it from `category` — deriving a full category→tier_group
mapping (covering medicine, law, commerce, animation/media, none of which
have adapters yet) is out of scope until the real 50-course pilot list
exists. The `__main__` smoke test hardcodes `tier_group="strong_tier"` for
all 5 engineering courses (matches `config/sources.yaml`'s existing
`# Engineering, Medicine` grouping under `strong_tier`).

`retrieval_order` itself is read from `config/sources.yaml` via a small
loader function (`yaml.safe_load`), not hardcoded — but the loaded dict is
passed into the smoke test's setup, not read globally inside
`retrieve_course()`, keeping the function itself free of file I/O and easy
to unit test with an in-memory fake order.

## Error handling

- Same as the adapters: an HTTP failure inside `download()` propagates (no
  new handling added here — Task 3/4's existing "fail loud, no partial
  manifest row" behavior already covers this). This task does not add
  per-course failure isolation; a course-level exception still aborts the
  `__main__` smoke test's run for the remaining courses. Documented as an
  explicit deferral, not an oversight (see Scope above).

## Testing

- `tests/test_orchestrator.py` — fake `SourceAdapter`-shaped test doubles
  (simple classes with scripted `match()`/`download()` return values, no
  real HTTP, no real `manifest.py`/SQLite involvement) to verify:
  - First source in `retrieval_order` wins when its confidence clears the
    threshold — no fallthrough attempted.
  - Fallthrough to the next source when the first's confidence is below
    threshold (mirrors the real AICTE Aerospace Engineering case, generalized).
  - A `retrieval_order` entry with no registered adapter is skipped
    silently — the walk continues to the next entry rather than erroring.
  - Returns `None` when every entry in the order is exhausted without a
    confident match.
  - `build_indices()` calls each adapter's `build_index()` exactly once,
    regardless of how many courses are subsequently processed.
- The `__main__` smoke test extends coverage to the real adapters/live
  network, following the same manual-verification pattern as the existing
  adapter smoke tests (not part of the automated `pytest` suite).
