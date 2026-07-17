# Stage 1 Pilot Batch Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrieve the real 50-course pilot end to end — a real pilot course list, name normalization, a batch runner with per-course failure isolation and rate limiting, and a Hard-Constraint-6-compliant tier-stratified report.

**Architecture:** Config data (`config/pilot_courses.yaml`, `config/sources.yaml`'s new `categories` map) feeds a new `src/retrieve/batch.py` module built across three tasks — normalization/models, the core `run_batch()` loop, then wiring + a live 50-course smoke test. `retrieve_course()` itself (already shipped, reviewed, tested) is not modified.

**Tech Stack:** Python 3.11+, `pydantic` (already a dependency), stdlib `re`/`time`/`logging`, `pytest` (`monkeypatch`, `caplog`).

## Global Constraints

- Type hints required on every function (project convention).
- No new dependencies.
- `retrieve_course()` is not modified — `source_category` is inferred after the fact from `ManifestEntry.source_type`, an explicit, documented simplification (design doc: "Inferring `source_category`").
- A course whose `retrieve_course()` call raises is caught, logged, recorded as `outcome="errored"`, and the batch continues to the next course — never aborts the run (design doc: "Batch runner").
- `normalize_course_name()` does **only** mechanical cleanup (trailing-parens stripping, slash-segment-taking) — never hand-maps to aggregator-canonical terms (design doc: "Name normalization").
- Rate limiting is a fixed delay between courses (`delay_seconds`, default 1.0) — no retry/backoff logic.
- `data/pilot_run_report.json` is gitignored, regenerable output.
- Full design reference: `docs/superpowers/specs/2026-07-17-stage1-pilot-batch-design.md`.

---

### Task 1: Pilot course data — `config/pilot_courses.yaml` + `categories` map

**Files:**
- Create: `config/pilot_courses.yaml`
- Modify: `config/sources.yaml`
- Test: `tests/test_pilot_courses.py` (new file)

**Interfaces:**
- Produces: `config/pilot_courses.yaml` with a top-level `courses:` list of `{raw_name: str, category: str}`, 50 entries.
- Produces: `config/sources.yaml`'s new `categories:` map (`dict[str, str]`, category name → tier_group).

- [ ] **Step 1: Create `config/pilot_courses.yaml`**

```yaml
# Pilot course list — 50 courses, stratified per README.md's "Pilot scope"
# table, selected from C:\Users\ajaas\Downloads\COURSE LIST.xlsx (30-sheet
# taxonomy of sub-fields -> applicable bachelor's degrees). raw_name is the
# exact sub-field string from that file, kept for provenance. Selecting
# these 50 names is input scoping (defining what to search for), not manual
# retrieval/matching/writing -- see design doc's Hard Constraint 1 note.
courses:
  # engineering (20) -> strong_tier
  - raw_name: "Civil Engineering"
    category: engineering
  - raw_name: "Mechanical Engineering"
    category: engineering
  - raw_name: "Electrical Engineering"
    category: engineering
  - raw_name: "Aerospace Engineering"
    category: engineering
  - raw_name: "Chemical Engineering"
    category: engineering
  - raw_name: "Biomedical Engineering"
    category: engineering
  - raw_name: "Electronics & Communication Engineering"
    category: engineering
  - raw_name: "Automotive Engineering"
    category: engineering
  - raw_name: "Industrial Engineering"
    category: engineering
  - raw_name: "Mechatronics Engineering"
    category: engineering
  - raw_name: "Robotics Engineering"
    category: engineering
  - raw_name: "Metallurgical Engineering"
    category: engineering
  - raw_name: "Mining Engineering"
    category: engineering
  - raw_name: "Marine Engineering"
    category: engineering
  - raw_name: "Computer Science & Engineering"
    category: engineering
  - raw_name: "Information Technology (IT)"
    category: engineering
  - raw_name: "Artificial Intelligence (AI)"
    category: engineering
  - raw_name: "Data Science"
    category: engineering
  - raw_name: "Cybersecurity / Information Security"
    category: engineering
  - raw_name: "Software Engineering"
    category: engineering

  # medicine (10) -> strong_tier
  - raw_name: "Allopathic Medicine & Surgery (Core)"
    category: medicine
  - raw_name: "Dentistry & Oral Surgery"
    category: medicine
  - raw_name: "Ayurveda"
    category: medicine
  - raw_name: "Homeopathy"
    category: medicine
  - raw_name: "Nursing (Core / General)"
    category: medicine
  - raw_name: "Pharmacy (Core)"
    category: medicine
  - raw_name: "Physiotherapy / Physical Therapy"
    category: medicine
  - raw_name: "Optometry & Ophthalmic Sciences"
    category: medicine
  - raw_name: "Nutrition & Dietetics"
    category: medicine
  - raw_name: "Radiography / Medical Imaging"
    category: medicine

  # commerce_management (5) -> medium_tier
  - raw_name: "Business Administration / Management (Core)"
    category: commerce_management
  - raw_name: "Accounting (Core)"
    category: commerce_management
  - raw_name: "Finance (Core)"
    category: commerce_management
  - raw_name: "Economics (Core)"
    category: commerce_management
  - raw_name: "Marketing"
    category: commerce_management

  # law (5) -> medium_tier
  - raw_name: "Law (Core / Professional)"
    category: law
  - raw_name: "Corporate / Business Law"
    category: law
  - raw_name: "Criminal Law / Criminal Justice"
    category: law
  - raw_name: "International Law / Global Law"
    category: law
  - raw_name: "Intellectual Property Law (IPR)"
    category: law

  # animation_design (5) -> weak_tier
  - raw_name: "Animation (Core / General)"
    category: animation_design
  - raw_name: "Film Production (Core / General)"
    category: animation_design
  - raw_name: "Visual Effects (VFX)"
    category: animation_design
  - raw_name: "Game Design (Core / Mechanics)"
    category: animation_design
  - raw_name: "Fashion Design"
    category: animation_design

  # media_mass_comm (5) -> weak_tier
  - raw_name: "Mass Communication"
    category: media_mass_comm
  - raw_name: "Journalism (Core)"
    category: media_mass_comm
  - raw_name: "Advertising"
    category: media_mass_comm
  - raw_name: "Public Relations (PR)"
    category: media_mass_comm
  - raw_name: "Graphic Design"
    category: media_mass_comm
```

- [ ] **Step 2: Add the `categories` map to `config/sources.yaml`**

Add this block immediately before the `matching:` section (i.e. right before the `# Confidence threshold for accepting a match() result...` comment):

```yaml
# Maps each pilot category (config/pilot_courses.yaml's `category` field,
# also src/schema.py's ManifestEntry.tier) to the tier_group that selects
# its retrieval_order sequence below.
categories:
  engineering: strong_tier
  medicine: strong_tier
  commerce_management: medium_tier
  law: medium_tier
  animation_design: weak_tier
  media_mass_comm: weak_tier

```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_pilot_courses.py`:

```python
from pathlib import Path

from src.retrieve.orchestrator import load_config

PILOT_COURSES_PATH = Path("config/pilot_courses.yaml")


def test_pilot_courses_has_fifty_entries():
    pilot = load_config(path=PILOT_COURSES_PATH)
    assert len(pilot["courses"]) == 50


def test_pilot_courses_stratified_by_category():
    pilot = load_config(path=PILOT_COURSES_PATH)
    counts = {}
    for course in pilot["courses"]:
        counts[course["category"]] = counts.get(course["category"], 0) + 1

    assert counts == {
        "engineering": 20,
        "medicine": 10,
        "commerce_management": 5,
        "law": 5,
        "animation_design": 5,
        "media_mass_comm": 5,
    }


def test_every_pilot_category_has_a_tier_group_mapping():
    pilot = load_config(path=PILOT_COURSES_PATH)
    sources = load_config()  # real config/sources.yaml

    categories_used = {course["category"] for course in pilot["courses"]}
    categories_mapped = set(sources["categories"].keys())

    assert categories_used <= categories_mapped


def test_every_category_tier_group_is_a_real_retrieval_order_key():
    sources = load_config()

    for category, tier_group in sources["categories"].items():
        assert tier_group in sources["retrieval_order"], (
            f"{category!r} maps to tier_group {tier_group!r}, "
            f"which has no retrieval_order entry"
        )
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pilot_courses.py -v`
Expected: FAIL — `FileNotFoundError` (`config/pilot_courses.yaml` doesn't exist yet) until Step 1/2 land; run this after Steps 1-2 are in place but before verifying content is exactly right, to confirm the test file itself is wired correctly. (In practice: write Steps 1-2 first per TDD-adjacent flow for data files, then Step 3's tests should pass immediately — there's no red/green cycle for static YAML data the way there is for code. Still run once to confirm.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pilot_courses.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add config/pilot_courses.yaml config/sources.yaml tests/test_pilot_courses.py
git commit -m "feat: add 50-course pilot list and category-to-tier_group map"
```

---

### Task 2: Normalization, source-category inference, and report models

**Files:**
- Create: `src/retrieve/batch.py`
- Test: `tests/test_batch.py` (new file)

**Interfaces:**
- Consumes: `SourceType` (existing, `src/schema.py`).
- Produces: `batch.normalize_course_name(raw_name: str) -> str`
- Produces: `batch.infer_source_category(source_type: SourceType) -> str`
- Produces: `batch.CourseResult` (pydantic): `raw_name: str`, `course_name: str`, `category: str`, `tier_group: str`, `outcome: Literal["matched", "no_source_found", "errored"]`, `source_category: Optional[str] = None`, `error: Optional[str] = None`
- Produces: `batch.TierSummary` (pydantic): `matched_by_source: dict[str, int]`, `no_source_found: int`, `errored: int`
- Produces: `batch.BatchReport` (pydantic): `results: list[CourseResult]`, `summary_by_tier: dict[str, TierSummary]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch.py`:

```python
from src.retrieve import batch
from src.schema import SourceType


def test_normalize_strips_trailing_parenthetical():
    assert batch.normalize_course_name("Allopathic Medicine & Surgery (Core)") == "Allopathic Medicine & Surgery"


def test_normalize_strips_trailing_parenthetical_with_slash_inside():
    assert batch.normalize_course_name("Law (Core / Professional)") == "Law"


def test_normalize_takes_segment_before_slash_after_stripping_parens():
    assert batch.normalize_course_name("Business Administration / Management (Core)") == "Business Administration"


def test_normalize_takes_segment_before_slash_with_no_trailing_parens():
    assert batch.normalize_course_name("Physiotherapy / Physical Therapy") == "Physiotherapy"


def test_normalize_leaves_clean_name_unchanged():
    assert batch.normalize_course_name("Mechanical Engineering") == "Mechanical Engineering"


def test_infer_source_category_for_regulator_pdf():
    assert batch.infer_source_category(SourceType.REGULATOR_PDF) == "regulatory_primary"


def test_infer_source_category_for_regulator_webpage():
    assert batch.infer_source_category(SourceType.REGULATOR_WEBPAGE) == "regulatory_primary"


def test_infer_source_category_for_aggregator_webpage():
    assert batch.infer_source_category(SourceType.AGGREGATOR_WEBPAGE) == "fact_supplement_independent_writing_required"


def test_infer_source_category_falls_back_to_unknown():
    assert batch.infer_source_category(SourceType.NONE) == "unknown"


def test_course_result_matched_round_trips_through_json():
    result = batch.CourseResult(
        raw_name="Mechanical Engineering",
        course_name="Mechanical Engineering",
        category="engineering",
        tier_group="strong_tier",
        outcome="matched",
        source_category="fact_supplement_independent_writing_required",
    )
    restored = batch.CourseResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_batch_report_round_trips_through_json():
    report = batch.BatchReport(
        results=[
            batch.CourseResult(
                raw_name="Mechanical Engineering",
                course_name="Mechanical Engineering",
                category="engineering",
                tier_group="strong_tier",
                outcome="matched",
                source_category="fact_supplement_independent_writing_required",
            ),
        ],
        summary_by_tier={
            "strong_tier": batch.TierSummary(
                matched_by_source={"fact_supplement_independent_writing_required": 1},
                no_source_found=0,
                errored=0,
            ),
        },
    )
    restored = batch.BatchReport.model_validate_json(report.model_dump_json())
    assert restored == report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.retrieve.batch'`

- [ ] **Step 3: Create `src/retrieve/batch.py`**

```python
import re
from typing import Literal, Optional

from pydantic import BaseModel

from src.schema import SourceType


def normalize_course_name(raw_name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)\s*$", "", raw_name).strip()
    if "/" in name:
        name = name.split("/")[0].strip()
    return name


_SOURCE_TYPE_TO_CATEGORY = {
    SourceType.REGULATOR_PDF: "regulatory_primary",
    SourceType.REGULATOR_WEBPAGE: "regulatory_primary",
    SourceType.AGGREGATOR_WEBPAGE: "fact_supplement_independent_writing_required",
}


def infer_source_category(source_type: SourceType) -> str:
    return _SOURCE_TYPE_TO_CATEGORY.get(source_type, "unknown")


class CourseResult(BaseModel):
    raw_name: str
    course_name: str
    category: str
    tier_group: str
    outcome: Literal["matched", "no_source_found", "errored"]
    source_category: Optional[str] = None
    error: Optional[str] = None


class TierSummary(BaseModel):
    matched_by_source: dict[str, int]
    no_source_found: int
    errored: int


class BatchReport(BaseModel):
    results: list[CourseResult]
    summary_by_tier: dict[str, TierSummary]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_batch.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/batch.py tests/test_batch.py
git commit -m "feat: add name normalization, source-category inference, and batch report models"
```

---

### Task 3: `run_batch()` — the core loop

**Files:**
- Modify: `src/retrieve/batch.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `normalize_course_name`, `infer_source_category`, `CourseResult`, `TierSummary`, `BatchReport` (Task 2); `retrieve_course` (existing, `src/retrieve/orchestrator.py`); `SourceAdapter` (existing, `src/retrieve/base.py`); `ManifestEntry`, `SourceCategory` (existing, `src/schema.py`).
- Produces: `batch.run_batch(courses: list[dict], categories: dict[str, str], retrieval_order: dict[str, list[str]], indices: dict[SourceAdapter, dict[str, str]], registry: dict[SourceCategory, dict[str, SourceAdapter]], threshold: float, delay_seconds: float = 1.0) -> BatchReport`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_batch.py` (add these imports at the top alongside the existing ones):

```python
import logging
from unittest.mock import patch

from src.retrieve.base import SourceMatch
from src.schema import ManifestEntry
```

Then append:

```python
class _ScriptedAdapter:
    def __init__(self, match_result=None, download_result=None, raise_on_match=None):
        self._match_result = match_result
        self._download_result = download_result
        self._raise_on_match = raise_on_match
        self.match_calls = []

    def build_index(self):
        return {}

    def match(self, course_name, index):
        self.match_calls.append(course_name)
        if self._raise_on_match is not None:
            raise self._raise_on_match
        return self._match_result

    def download(self, match, tier):
        return self._download_result


def _manifest_entry(source_type=SourceType.AGGREGATOR_WEBPAGE):
    return ManifestEntry(
        course_name="X",
        tier="engineering",
        source_type=source_type,
        matched_url="https://example.com/x",
        match_confidence=0.95,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )


def _match(confidence=0.95):
    return SourceMatch(course_name="X", matched_name="X", matched_url="https://example.com/x", confidence=confidence)


def _fixture_env(adapter):
    categories = {"engineering": "strong_tier"}
    retrieval_order = {"strong_tier": ["fact_supplement_independent_writing_required"]}
    registry = {SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": adapter}}
    indices = {adapter: {}}
    return categories, retrieval_order, registry, indices


def test_run_batch_resolves_tier_group_via_categories_map():
    adapter = _ScriptedAdapter(match_result=_match(), download_result=_manifest_entry())
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [{"raw_name": "Mechanical Engineering", "category": "engineering"}]

    report = batch.run_batch(
        courses=courses,
        categories=categories,
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
        delay_seconds=0,
    )

    assert report.results[0].tier_group == "strong_tier"


def test_run_batch_records_matched_outcome_with_inferred_source_category():
    adapter = _ScriptedAdapter(
        match_result=_match(),
        download_result=_manifest_entry(source_type=SourceType.AGGREGATOR_WEBPAGE),
    )
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [{"raw_name": "Mechanical Engineering", "category": "engineering"}]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    result = report.results[0]
    assert result.outcome == "matched"
    assert result.source_category == "fact_supplement_independent_writing_required"
    assert result.course_name == "Mechanical Engineering"  # already clean, unchanged by normalize


def test_run_batch_records_no_source_found_when_nothing_clears_threshold():
    adapter = _ScriptedAdapter(match_result=_match(confidence=0.1))
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [{"raw_name": "Nonexistent Course", "category": "engineering"}]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    assert report.results[0].outcome == "no_source_found"
    assert report.results[0].source_category is None


def test_run_batch_records_errored_outcome_and_continues_to_next_course():
    failing_adapter = _ScriptedAdapter(raise_on_match=RuntimeError("simulated network failure"))
    categories, retrieval_order, registry, indices = _fixture_env(failing_adapter)
    courses = [
        {"raw_name": "Course One", "category": "engineering"},
        {"raw_name": "Course Two", "category": "engineering"},
    ]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    assert len(report.results) == 2
    assert report.results[0].outcome == "errored"
    assert "simulated network failure" in report.results[0].error
    assert report.results[1].outcome == "errored"  # same failing adapter, but the loop reached it
    assert len(failing_adapter.match_calls) == 2  # both courses were attempted


def test_run_batch_logs_errored_course(caplog):
    failing_adapter = _ScriptedAdapter(raise_on_match=RuntimeError("boom"))
    categories, retrieval_order, registry, indices = _fixture_env(failing_adapter)
    courses = [{"raw_name": "Course One", "category": "engineering"}]

    with caplog.at_level(logging.INFO):
        batch.run_batch(
            courses=courses, categories=categories, retrieval_order=retrieval_order,
            indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
        )

    assert any("errored" in record.message for record in caplog.records)


def test_run_batch_sleeps_between_courses():
    adapter = _ScriptedAdapter(match_result=_match(), download_result=_manifest_entry())
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [
        {"raw_name": "Course One", "category": "engineering"},
        {"raw_name": "Course Two", "category": "engineering"},
    ]

    with patch("src.retrieve.batch.time.sleep") as mock_sleep:
        batch.run_batch(
            courses=courses, categories=categories, retrieval_order=retrieval_order,
            indices=indices, registry=registry, threshold=0.8, delay_seconds=2.5,
        )

    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(2.5)


def test_summary_by_tier_aggregates_matched_no_source_found_and_errored():
    adapter = _ScriptedAdapter(match_result=_match(), download_result=_manifest_entry())
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [
        {"raw_name": "Matched Course", "category": "engineering"},
    ]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    tier_summary = report.summary_by_tier["strong_tier"]
    assert tier_summary.matched_by_source == {"fact_supplement_independent_writing_required": 1}
    assert tier_summary.no_source_found == 0
    assert tier_summary.errored == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_batch.py -v`
Expected: FAIL — `AttributeError: module 'src.retrieve.batch' has no attribute 'run_batch'`

- [ ] **Step 3: Implement `run_batch()`**

Add these imports to the top of `src/retrieve/batch.py` (alongside the existing ones):

```python
import logging
import time

from src.retrieve.base import SourceAdapter
from src.retrieve.orchestrator import retrieve_course
from src.schema import SourceCategory
```

Add the module logger below the imports:

```python
logger = logging.getLogger(__name__)
```

Append these functions to the end of the file:

```python
def run_batch(
    courses: list[dict],
    categories: dict[str, str],
    retrieval_order: dict[str, list[str]],
    indices: dict[SourceAdapter, dict[str, str]],
    registry: dict[SourceCategory, dict[str, SourceAdapter]],
    threshold: float,
    delay_seconds: float = 1.0,
) -> BatchReport:
    results: list[CourseResult] = []

    for course in courses:
        raw_name = course["raw_name"]
        category = course["category"]
        tier_group = categories[category]
        course_name = normalize_course_name(raw_name)

        try:
            entry = retrieve_course(
                course_name=course_name,
                category=category,
                tier_group=tier_group,
                retrieval_order=retrieval_order,
                indices=indices,
                registry=registry,
                threshold=threshold,
            )
        except Exception as exc:
            logger.info("Course %r errored: %s", raw_name, exc)
            results.append(
                CourseResult(
                    raw_name=raw_name,
                    course_name=course_name,
                    category=category,
                    tier_group=tier_group,
                    outcome="errored",
                    error=str(exc),
                )
            )
            time.sleep(delay_seconds)
            continue

        if entry is None:
            results.append(
                CourseResult(
                    raw_name=raw_name,
                    course_name=course_name,
                    category=category,
                    tier_group=tier_group,
                    outcome="no_source_found",
                )
            )
        else:
            results.append(
                CourseResult(
                    raw_name=raw_name,
                    course_name=course_name,
                    category=category,
                    tier_group=tier_group,
                    outcome="matched",
                    source_category=infer_source_category(entry.source_type),
                )
            )

        time.sleep(delay_seconds)

    return BatchReport(results=results, summary_by_tier=_summarize(results))


def _summarize(results: list[CourseResult]) -> dict[str, TierSummary]:
    summary: dict[str, TierSummary] = {}
    for result in results:
        tier_summary = summary.setdefault(
            result.tier_group,
            TierSummary(matched_by_source={}, no_source_found=0, errored=0),
        )
        if result.outcome == "matched":
            key = result.source_category or "unknown"
            tier_summary.matched_by_source[key] = tier_summary.matched_by_source.get(key, 0) + 1
        elif result.outcome == "no_source_found":
            tier_summary.no_source_found += 1
        elif result.outcome == "errored":
            tier_summary.errored += 1
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_batch.py -v`
Expected: PASS (18 passed)

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/batch.py tests/test_batch.py
git commit -m "feat: implement run_batch() with failure isolation and rate limiting"
```

---

### Task 4: Registry refactor + batch wiring + live smoke test

**Files:**
- Modify: `src/retrieve/orchestrator.py`
- Modify: `src/retrieve/batch.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `load_config`, `build_indices` (existing, `src/retrieve/orchestrator.py`); `run_batch` (Task 3); `AICTEAdapter` (existing); `Careers360Adapter` (existing).
- Produces: `orchestrator.default_registry(aicte_adapter: SourceAdapter, careers360_adapter: SourceAdapter) -> dict[SourceCategory, dict[str, SourceAdapter]]`
- No new pytest tests beyond confirming existing ones still pass — this task is a pure refactor (Step 2) plus `__main__` wiring (Step 4), matching the pattern of prior `__main__`-only tasks not being part of the automated suite.

- [ ] **Step 1: Run the full test suite as a baseline**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS — all tests (30 pre-existing + 4 from Task 1 + 18 from Tasks 2-3 = 52).

- [ ] **Step 2: Extract `default_registry()` in `src/retrieve/orchestrator.py`**

Add this function directly above the `if __name__ == "__main__":` block:

```python
def default_registry(
    aicte_adapter: SourceAdapter, careers360_adapter: SourceAdapter
) -> dict[SourceCategory, dict[str, SourceAdapter]]:
    return {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
    }
```

Replace the inline registry construction inside the `__main__` block:

```python
    registry = {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
    }
```

with:

```python
    registry = default_registry(aicte_adapter, careers360_adapter)
```

- [ ] **Step 3: Run the full suite to confirm the refactor didn't break anything**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (52 passed) — `default_registry()` returns the identical dict shape the inline literal did, so no existing test should be affected.

- [ ] **Step 4: Add `data/pilot_run_report.json` to `.gitignore`**

In `.gitignore`, in the `# data (gitignored per pipeline design — raw docs + manifest are regenerable)` section, add a line after `data/manifest.db`:

```
data/pilot_run_report.json
```

- [ ] **Step 5: Add the `__main__` block to `src/retrieve/batch.py`**

Append to the end of `src/retrieve/batch.py`:

```python
if __name__ == "__main__":
    from pathlib import Path

    from src.retrieve.aicte import AICTEAdapter
    from src.retrieve.careers360 import Careers360Adapter
    from src.retrieve.orchestrator import build_indices, default_registry, load_config

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = load_config()
    retrieval_order = config["retrieval_order"]
    threshold = config["matching"]["threshold"]
    categories = config["categories"]

    pilot_config = load_config(path=Path("config/pilot_courses.yaml"))
    courses = pilot_config["courses"]

    aicte_adapter = AICTEAdapter()
    careers360_adapter = Careers360Adapter()
    registry = default_registry(aicte_adapter, careers360_adapter)

    print("Building indices...")
    indices = build_indices([aicte_adapter, careers360_adapter])
    print(f"AICTE index: {len(indices[aicte_adapter])} entries")
    print(f"Careers360 index: {len(indices[careers360_adapter])} entries\n")

    print(f"Running batch for {len(courses)} courses (this will take a few minutes)...\n")
    report = run_batch(
        courses=courses,
        categories=categories,
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=threshold,
    )

    report_path = Path("data/pilot_run_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nReport written to {report_path}\n")

    print("=== Summary by tier ===")
    for tier_group, summary in report.summary_by_tier.items():
        print(f"{tier_group}:")
        for source, count in summary.matched_by_source.items():
            print(f"  matched via {source}: {count}")
        print(f"  no_source_found: {summary.no_source_found}")
        print(f"  errored: {summary.errored}")
```

- [ ] **Step 6: Run the smoke test live**

Run: `.venv/Scripts/python.exe -m src.retrieve.batch`
Expected: processes all 50 pilot courses against the real AICTE/Careers360 sites
(with a ~1s delay between each — expect this to take a few minutes, not
seconds). Ends with a per-tier summary printed to stdout and
`data/pilot_run_report.json` written. Inspect the actual counts — this is a
real, unscripted result, not an assertion to match; report whatever the live
run actually shows (including if some courses come back `errored` or
`no_source_found` — that's expected, especially for medicine/law/commerce
where no regulator adapter exists yet, and for animation/media`s scoped-search
gap).

- [ ] **Step 7: Run the full test suite once more**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (52 passed) — the `__main__` block is not imported/executed
during test collection.

- [ ] **Step 8: Commit**

```bash
git add src/retrieve/orchestrator.py src/retrieve/batch.py .gitignore
git commit -m "feat: wire pilot batch runner with shared registry and live smoke test"
```

---

## Post-plan state

After Task 4, the real 50-course pilot can be retrieved end to end with one
command (`python -m src.retrieve.batch`), producing a tier-stratified report
(`data/pilot_run_report.json`) that satisfies Hard Constraint 6 — no blended
single number, ever. `data/raw/` and `data/manifest.db` now hold a real,
multi-category corpus (not just the 5 engineering smoke-test courses), which is
what Stage 2 (Extract) needs to work against instead of a near-empty directory.
Known, accepted gaps going into that corpus: medicine/law/commerce/animation
categories only ever resolve via Careers360 or Wikipedia (no regulator adapter
exists for NMC/BCI/UGC yet, and `general_background` has no adapter registered
at all yet — see `config/sources.yaml`'s `matching`/`categories`/`retrieval_order`
notes) — every `no_source_found` in those tiers is expected, valid signal, not a
bug in this batch runner.
