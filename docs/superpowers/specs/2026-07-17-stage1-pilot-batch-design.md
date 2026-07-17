# Stage 1 Pilot Batch Runner — Design

Date: 2026-07-17
Status: Approved

## Context

`retrieve_course()` (built in a prior session) correctly resolves one course at a
time, live-verified against 5 hardcoded engineering courses. To actually retrieve
the **50-course pilot** described in `README.md`'s "Pilot scope" table (20
engineering / 10 medicine / 5 commerce-management / 5 law / 10 animation-media),
three things are still missing:

1. The 50 course names as real data — README only has category *counts*, not names.
2. A batch runner that processes all 50 with failure isolation, rate limiting, and
   a Hard-Constraint-6-compliant tier-stratified report — deliberately deferred
   from the orchestration work until real data existed to design against
   (`docs/superpowers/specs/2026-07-17-stage1-orchestration-design.md`, Scope
   section).
3. A category → tier_group mapping, so a course's `category` (e.g. `"medicine"`)
   resolves to the right `retrieval_order` sequence (`"strong_tier"`).

## Pilot list source: `COURSE LIST.xlsx`

The user supplied `C:\Users\ajaas\Downloads\COURSE LIST.xlsx` — 30 discipline
sheets (754 sub-fields total), each row mapping a sub-field/specialization to its
applicable bachelor's degrees. This is the candidate universe the 50-course pilot
is selected from.

**Hard Constraint 1 note** ("no manual retrieval, matching, or writing anywhere"):
selecting 50 course names from this file and writing them into a config file is
treated as **input scoping** (defining what to search for), not manual retrieval
or matching — the pipeline still does 100% of the actual retrieval/matching/
writing. This is the same category as a search query, not dataset content.

## Pilot list file: `config/pilot_courses.yaml`

50 entries, `{raw_name, category}`, selected from the xlsx to match README's
per-category counts exactly:

- **engineering (20)**: Civil, Mechanical, Electrical, Aerospace, Chemical,
  Biomedical, Electronics & Communication, Automotive, Industrial, Mechatronics,
  Robotics, Metallurgical, Mining, Marine Engineering, Computer Science &
  Engineering, Information Technology (IT), Artificial Intelligence (AI), Data
  Science, Cybersecurity / Information Security, Software Engineering
- **medicine (10)**: Allopathic Medicine & Surgery (Core), Dentistry & Oral
  Surgery, Ayurveda, Homeopathy, Nursing (Core / General), Pharmacy (Core),
  Physiotherapy / Physical Therapy, Optometry & Ophthalmic Sciences, Nutrition &
  Dietetics, Radiography / Medical Imaging
- **commerce_management (5)**: Business Administration / Management (Core),
  Accounting (Core), Finance (Core), Economics (Core), Marketing
- **law (5)**: Law (Core / Professional), Corporate / Business Law, Criminal Law
  / Criminal Justice, International Law / Global Law, Intellectual Property Law
  (IPR)
- **animation_design (5)**: Animation (Core / General), Film Production (Core /
  General), Visual Effects (VFX), Game Design (Core / Mechanics), Fashion Design
- **media_mass_comm (5)**: Mass Communication, Journalism (Core), Advertising,
  Public Relations (PR), Graphic Design

`raw_name` is the exact xlsx sub-field string, kept for provenance (traceable
back to the source file, per this project's citation ethos). `category` is one of
the six values already used elsewhere in `config/sources.yaml`
(`regulatory_primary`'s sub-keys, plus the two weak-tier categories from
`weak_tier_scoped_search_notes`).

## Name normalization: `normalize_course_name()`

The raw xlsx names are noisy for fuzzy-matching (`"Allopathic Medicine & Surgery
(Core)"`, `"Law (Core / Professional)"`) — Careers360/regulator listings use
clean names (`"MBBS"`, `"Law"`). `normalize_course_name(raw_name: str) -> str`,
in `src/retrieve/batch.py`, does **light mechanical cleanup only**:

```python
import re

def normalize_course_name(raw_name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)\s*$", "", raw_name).strip()  # strip trailing "(...)"
    if "/" in name:
        name = name.split("/")[0].strip()  # take the segment before "/"
    return name
```

Examples: `"Allopathic Medicine & Surgery (Core)"` → `"Allopathic Medicine &
Surgery"`; `"Business Administration / Management (Core)"` → `"Business
Administration"`; `"Mechanical Engineering"` → unchanged (no parens/slash).

**Deliberately not done**: hand-mapping to aggregator-canonical terms (e.g.
`"Allopathic Medicine & Surgery (Core)"` → `"MBBS"`). That would cross from input
scoping into manual matching (Hard Constraint 1) and hide exactly the signal the
pilot exists to surface — if a mechanically-normalized name fails to match, that
is a real, valid finding about where automated matching breaks, not something to
paper over by hand-picking the "right" term.

## Category → tier_group map

New `categories:` key in `config/sources.yaml`:

```yaml
categories:
  engineering: strong_tier
  medicine: strong_tier
  commerce_management: medium_tier
  law: medium_tier
  animation_design: weak_tier
  media_mass_comm: weak_tier
```

Read via the existing `load_config()`; a course's `category` (from
`pilot_courses.yaml`) looks up its `tier_group` here before calling
`retrieve_course(..., tier_group=..., ...)`.

## Batch runner: new module `src/retrieve/batch.py`

```python
def run_batch(
    courses: list[dict],                                    # [{"raw_name": ..., "category": ...}, ...]
    categories: dict[str, str],                              # category -> tier_group
    retrieval_order: dict[str, list[str]],
    indices: dict[SourceAdapter, dict[str, str]],
    registry: dict[SourceCategory, dict[str, SourceAdapter]],
    threshold: float,
    delay_seconds: float = 1.0,
) -> BatchReport:
```

For each course: normalize the name, resolve `tier_group` via `categories`, call
`retrieve_course()` **wrapped in try/except**, `time.sleep(delay_seconds)` before
moving to the next course (rate limiting — a fixed delay, no backoff/retry logic;
matches this project's repeated pattern of not designing against failure modes
that haven't been observed yet).

**Outcome per course** (`CourseResult`, pydantic):
- `ManifestEntry` returned → `outcome="matched"`, `source_category` inferred from
  `entry.source_type` (see mapping below).
- `None` returned → `outcome="no_source_found"`.
- Exception raised → caught, logged with the course name and error message,
  `outcome="errored"`, **loop continues** — one bad course (network timeout,
  unexpected page structure) does not abort the other 49. This is a deliberate
  distinction from `no_source_found`: "genuinely tried every source and none
  matched" is different signal from "something broke," per this project's
  no-fabrication / explicit-flag principle (Hard Constraint 4).

```python
class CourseResult(BaseModel):
    raw_name: str
    course_name: str                      # normalized, what was actually matched against
    category: str
    tier_group: str
    outcome: Literal["matched", "no_source_found", "errored"]
    source_category: Optional[str] = None  # which retrieval_order entry matched, if outcome == "matched"
    error: Optional[str] = None            # exception message, if outcome == "errored"
```

`CourseResult` does not duplicate the full `ManifestEntry` — that's already
durably stored in `data/manifest.db` (`manifest.get_entry(course_name,
matched_url)` retrieves it). The report's job is the tier-stratified *outcome*
summary Hard Constraint 6 requires, not a second copy of retrieval detail.

### Inferring `source_category` from `ManifestEntry.source_type`

Rather than widening `retrieve_course()`'s return type (which would touch the
already-reviewed, merged, tested core function and its existing tests/smoke
test), `batch.py` infers which category matched from the downloaded
`ManifestEntry.source_type`:

```python
_SOURCE_TYPE_TO_CATEGORY = {
    SourceType.REGULATOR_PDF: "regulatory_primary",
    SourceType.REGULATOR_WEBPAGE: "regulatory_primary",
    SourceType.AGGREGATOR_WEBPAGE: "fact_supplement_independent_writing_required",
}

def infer_source_category(source_type: SourceType) -> str:
    return _SOURCE_TYPE_TO_CATEGORY.get(source_type, "unknown")
```

**Explicit, documented limitation**: this is a simplification that holds because
today's 2 adapters have a 1:1 `source_type`↔`SourceCategory` mapping (AICTE
always produces `REGULATOR_PDF` under `REGULATORY_PRIMARY`; Careers360 always
produces `AGGREGATOR_WEBPAGE` under `FACT_SUPPLEMENT_...`). It is **not** a sound
general invariant — `SourceType` describes a document's physical shape,
`SourceCategory` describes its grounding-tier classification, and nothing
guarantees they stay 1:1 as more adapters are added (e.g. a `UNIVERSITY_WEBPAGE`
source could plausibly belong to either `fact_supplement` or
`general_background` depending on which adapter produces it). `"unknown"` is the
explicit fallback for anything not in the map — never a guess. Revisit by
widening `retrieve_course()`'s return type (the seam already flagged in the prior
design doc) if/when this mapping stops holding.

### `BatchReport` — the Hard Constraint 6 summary

```python
class TierSummary(BaseModel):
    matched_by_source: dict[str, int]   # e.g. {"fact_supplement_independent_writing_required": 18, "regulatory_primary": 2}
    no_source_found: int
    errored: int

class BatchReport(BaseModel):
    results: list[CourseResult]
    summary_by_tier: dict[str, TierSummary]   # keyed by tier_group: "strong_tier", "medium_tier", "weak_tier"
```

Written to `data/pilot_run_report.json` (gitignored — regenerable output, same
category as `data/raw/` and `data/manifest.db`; `.gitignore` gains a
`data/pilot_run_report.json` line) and printed as a console summary table. Never
blended into one number, per Hard Constraint 6 — `strong_tier`, `medium_tier`,
and `weak_tier` are always reported separately.

## Refactor bundled in: shared registry construction

`orchestrator.py`'s `__main__` block currently constructs the
`{SourceCategory: {category: adapter}}` registry inline. `batch.py` needs the
identical registry. Extracted into a reusable function in `orchestrator.py`:

```python
def default_registry(
    aicte_adapter: SourceAdapter, careers360_adapter: SourceAdapter
) -> dict[SourceCategory, dict[str, SourceAdapter]]:
    return {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
    }
```

`orchestrator.py`'s `__main__` is updated to call this instead of the inline
dict literal. This is the second real use site appearing (not a premature
abstraction) — DRY, not speculative.

## Error handling

- Per-course exceptions are caught in `run_batch()`'s loop, logged with course
  name + error, recorded as `outcome="errored"` — never silently dropped, never
  allowed to abort the batch (see "Batch runner" above).
- A malformed `pilot_courses.yaml` (missing required keys) fails loud at load
  time, before any network activity — not a silent skip.

## Testing

- `tests/test_batch.py` — fake `SourceAdapter` test doubles (no real HTTP), same
  pattern as `tests/test_orchestrator.py`:
  - `normalize_course_name()` — table-driven tests for the documented transform
    rules (trailing-parens stripping, slash-segment-taking, unchanged-when-clean).
  - `run_batch()` processes multiple courses, correctly resolves `tier_group` via
    the `categories` map per course.
  - A course whose `retrieve_course()` call raises is caught, recorded as
    `errored` with the exception message, and the loop continues to the next
    course (verified via a fake adapter whose `match()` raises).
  - `infer_source_category()` — table-driven tests for the `SourceType` → string
    mapping, including the `"unknown"` fallback for an unmapped `SourceType`.
  - `BatchReport.summary_by_tier` correctly aggregates counts per tier from a set
    of scripted `CourseResult`s (matched/no_source_found/errored, broken down by
    `source_category` within `matched`).
- No new tests for `orchestrator.py`'s `default_registry()` extraction beyond
  confirming existing tests still pass — it's a pure refactor of already-tested
  construction logic, not new behavior.
- The `__main__` smoke test in `batch.py` is the live, real-network verification
  (not part of the automated `pytest` suite) — running all 50 real pilot courses
  against the real AICTE/Careers360 sites and inspecting the actual report.
