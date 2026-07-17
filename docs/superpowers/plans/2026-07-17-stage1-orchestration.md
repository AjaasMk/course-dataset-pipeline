# Stage 1 Orchestration (`retrieve_course`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the orchestration layer that walks a course through its tier's declared `retrieval_order` in `config/sources.yaml`, trying each source in order and using the first one whose match confidence clears a threshold.

**Architecture:** A single module, `src/retrieve/orchestrator.py`, built up across three tasks: config/index scaffolding, the core `retrieve_course()` decision-tree function, then registry wiring + a live smoke test against the real AICTE/Careers360 adapters. All dependencies (registry, indices, threshold, retrieval order) are passed as explicit parameters — no module-level constants, no global config reads inside the core function.

**Tech Stack:** Python 3.11+, `pyyaml` (already a dependency), stdlib `logging`, `pytest` (`caplog`, `tmp_path`).

## Global Constraints

- Type hints required on every function (project convention).
- No new dependencies — `pyyaml`, `logging` are already available.
- `retrieve_course()`'s `threshold` parameter has **no default value** — `config/sources.yaml`'s `matching.threshold` is the single source of truth (design doc: "Threshold lives in config, not a Python default").
- Registry is a single dict, `dict[SourceCategory, dict[str, SourceAdapter]]`, with `"*"` as the wildcard key for category-agnostic adapters (design doc: "Registry").
- `retrieval_order` is passed as an explicit parameter to `retrieve_course()`, never read from a global or reloaded from disk inside it.
- `build_indices()` calls each adapter's `build_index()` exactly once per run, keyed by adapter instance (default object identity hash/eq).
- Accept condition is written in the affirmative: `if match is not None and match.confidence >= threshold:`.
- Logging via stdlib `logging` at each decision point (trying / no-match-falling-through / matched-downloading / exhausted), not `print`.
- This task does not add per-course failure isolation, rate-limiting, or tier-stratified reporting — those are explicitly deferred (design doc: "Scope").
- Full design reference: `docs/superpowers/specs/2026-07-17-stage1-orchestration-design.md`.

---

### Task 1: Config scaffolding — `matching.threshold`, `load_config()`, `build_indices()`

**Files:**
- Modify: `config/sources.yaml`
- Create: `src/retrieve/orchestrator.py`
- Test: `tests/test_orchestrator.py` (new file)

**Interfaces:**
- Consumes: `SourceAdapter` (existing, `src/retrieve/base.py`).
- Produces: `orchestrator.DEFAULT_CONFIG_PATH: Path` (`Path("config/sources.yaml")`)
- Produces: `orchestrator.load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict`
- Produces: `orchestrator.build_indices(adapters: list[SourceAdapter]) -> dict[SourceAdapter, dict[str, str]]`

- [ ] **Step 1: Add `matching.threshold` to `config/sources.yaml`**

Add this block immediately before the existing `# Declarative retrieval order per tier.` comment (i.e. right before the `retrieval_order:` section):

```yaml
# Confidence threshold for accepting a match() result during orchestrated
# retrieval (src/retrieve/orchestrator.py). Below this, retrieve_course()
# falls through to the next source in retrieval_order rather than
# downloading a low-confidence match — this is what correctly rejects
# AICTE's Aerospace Engineering "Textile Engineering" match (confidence
# 0.69) instead of downloading the wrong document.
matching:
  threshold: 0.80

```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_orchestrator.py`:

```python
from src.retrieve import orchestrator


def test_load_config_returns_dict_from_real_file():
    config = orchestrator.load_config()

    assert "retrieval_order" in config
    assert config["matching"]["threshold"] == 0.80


def test_load_config_reads_given_path(tmp_path):
    config_path = tmp_path / "fake_sources.yaml"
    config_path.write_text("matching:\n  threshold: 0.5\n", encoding="utf-8")

    config = orchestrator.load_config(path=config_path)

    assert config == {"matching": {"threshold": 0.5}}


class _FakeAdapter:
    def __init__(self, index):
        self._index = index
        self.build_index_calls = 0

    def build_index(self):
        self.build_index_calls += 1
        return self._index

    def match(self, course_name, index):
        raise NotImplementedError

    def download(self, match, tier):
        raise NotImplementedError


def test_build_indices_calls_build_index_once_per_adapter():
    adapter_a = _FakeAdapter(index={"a": "url-a"})
    adapter_b = _FakeAdapter(index={"b": "url-b"})

    indices = orchestrator.build_indices([adapter_a, adapter_b])

    assert indices == {adapter_a: {"a": "url-a"}, adapter_b: {"b": "url-b"}}
    assert adapter_a.build_index_calls == 1
    assert adapter_b.build_index_calls == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.retrieve.orchestrator'`

- [ ] **Step 4: Create `src/retrieve/orchestrator.py`**

```python
from pathlib import Path

import yaml

from src.retrieve.base import SourceAdapter

DEFAULT_CONFIG_PATH = Path("config/sources.yaml")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_indices(adapters: list[SourceAdapter]) -> dict[SourceAdapter, dict[str, str]]:
    return {adapter: adapter.build_index() for adapter in adapters}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_orchestrator.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add config/sources.yaml src/retrieve/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add config-driven matching threshold and orchestrator scaffolding"
```

---

### Task 2: `retrieve_course()` — core decision-tree logic

**Files:**
- Modify: `src/retrieve/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `load_config`, `build_indices` (Task 1); `SourceAdapter`, `SourceMatch` (existing, `src/retrieve/base.py`); `ManifestEntry`, `SourceCategory` (existing, `src/schema.py`).
- Produces: `orchestrator.retrieve_course(course_name: str, category: str, tier_group: str, retrieval_order: dict[str, list[str]], indices: dict[SourceAdapter, dict[str, str]], registry: dict[SourceCategory, dict[str, SourceAdapter]], threshold: float) -> ManifestEntry | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orchestrator.py` (add these imports at the top alongside the existing `from src.retrieve import orchestrator`):

```python
import logging

from src.retrieve.base import SourceMatch
from src.schema import ManifestEntry, SourceCategory, SourceType
```

Then append:

```python
class _ScriptedAdapter:
    def __init__(self, match_result=None, download_result=None):
        self._match_result = match_result
        self._download_result = download_result
        self.match_calls = []
        self.download_calls = []

    def build_index(self):
        return {}

    def match(self, course_name, index):
        self.match_calls.append(course_name)
        return self._match_result

    def download(self, match, tier):
        self.download_calls.append((match, tier))
        return self._download_result


def _manifest_entry():
    return ManifestEntry(
        course_name="Mechanical Engineering",
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        matched_url="https://example.com/m.pdf",
        match_confidence=0.95,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )


def _match(confidence):
    return SourceMatch(
        course_name="Mechanical Engineering",
        matched_name="Mechanical Engineering",
        matched_url="https://example.com/m.pdf",
        confidence=confidence,
    )


def test_first_source_wins_when_confidence_clears_threshold(caplog):
    winning_entry = _manifest_entry()
    first_adapter = _ScriptedAdapter(match_result=_match(0.95), download_result=winning_entry)
    second_adapter = _ScriptedAdapter(match_result=_match(0.99), download_result=_manifest_entry())

    retrieval_order = {
        "strong_tier": [
            "fact_supplement_independent_writing_required",
            "regulatory_primary",
        ]
    }
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": first_adapter},
        SourceCategory.REGULATORY_PRIMARY: {"engineering": second_adapter},
    }
    indices = {first_adapter: {}, second_adapter: {}}

    with caplog.at_level(logging.INFO):
        result = orchestrator.retrieve_course(
            course_name="Mechanical Engineering",
            category="engineering",
            tier_group="strong_tier",
            retrieval_order=retrieval_order,
            indices=indices,
            registry=registry,
            threshold=0.8,
        )

    assert result == winning_entry
    assert len(first_adapter.match_calls) == 1
    assert len(first_adapter.download_calls) == 1
    assert len(second_adapter.match_calls) == 0
    assert any("Matched" in record.message for record in caplog.records)


def test_falls_through_to_next_source_when_confidence_below_threshold(caplog):
    winning_entry = _manifest_entry()
    low_confidence_adapter = _ScriptedAdapter(match_result=_match(0.69))
    high_confidence_adapter = _ScriptedAdapter(match_result=_match(0.95), download_result=winning_entry)

    retrieval_order = {
        "strong_tier": [
            "fact_supplement_independent_writing_required",
            "regulatory_primary",
        ]
    }
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": low_confidence_adapter},
        SourceCategory.REGULATORY_PRIMARY: {"engineering": high_confidence_adapter},
    }
    indices = {low_confidence_adapter: {}, high_confidence_adapter: {}}

    with caplog.at_level(logging.INFO):
        result = orchestrator.retrieve_course(
            course_name="Aerospace Engineering",
            category="engineering",
            tier_group="strong_tier",
            retrieval_order=retrieval_order,
            indices=indices,
            registry=registry,
            threshold=0.8,
        )

    assert result == winning_entry
    assert len(low_confidence_adapter.download_calls) == 0
    assert len(high_confidence_adapter.match_calls) == 1
    assert any("falling through" in record.message for record in caplog.records)


def test_skips_entry_with_no_registered_adapter():
    fallback_entry = _manifest_entry()
    fallback_adapter = _ScriptedAdapter(match_result=_match(0.9), download_result=fallback_entry)

    # regulatory_primary has no entry in the registry at all — e.g. medicine, no NMC adapter built
    retrieval_order = {"strong_tier": ["regulatory_primary", "fact_supplement_independent_writing_required"]}
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": fallback_adapter},
    }
    indices = {fallback_adapter: {}}

    result = orchestrator.retrieve_course(
        course_name="Cardiology",
        category="medicine",
        tier_group="strong_tier",
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
    )

    assert result == fallback_entry


def test_returns_none_when_every_source_falls_through():
    weak_adapter = _ScriptedAdapter(match_result=_match(0.1))

    retrieval_order = {"strong_tier": ["fact_supplement_independent_writing_required"]}
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": weak_adapter},
    }
    indices = {weak_adapter: {}}

    result = orchestrator.retrieve_course(
        course_name="Nonexistent Course",
        category="engineering",
        tier_group="strong_tier",
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
    )

    assert result is None


def test_returns_none_when_match_is_none():
    # match() returns None only when its index is empty, per SourceAdapter's contract
    empty_index_adapter = _ScriptedAdapter(match_result=None)

    retrieval_order = {"strong_tier": ["fact_supplement_independent_writing_required"]}
    registry = {
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": empty_index_adapter},
    }
    indices = {empty_index_adapter: {}}

    result = orchestrator.retrieve_course(
        course_name="Any Course",
        category="engineering",
        tier_group="strong_tier",
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
    )

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `AttributeError: module 'src.retrieve.orchestrator' has no attribute 'retrieve_course'`

- [ ] **Step 3: Implement `retrieve_course()`**

Add these imports to the top of `src/retrieve/orchestrator.py` (alongside the existing ones):

```python
import logging

from src.schema import ManifestEntry, SourceCategory
```

Add the module logger below the existing `DEFAULT_CONFIG_PATH` constant:

```python
logger = logging.getLogger(__name__)
```

Append the function:

```python
def retrieve_course(
    course_name: str,
    category: str,
    tier_group: str,
    retrieval_order: dict[str, list[str]],
    indices: dict[SourceAdapter, dict[str, str]],
    registry: dict[SourceCategory, dict[str, SourceAdapter]],
    threshold: float,
) -> ManifestEntry | None:
    order = retrieval_order[tier_group]

    for entry in order:
        source_category = SourceCategory(entry)
        category_map = registry.get(source_category, {})
        adapter = category_map.get(category) or category_map.get("*")

        if adapter is None:
            logger.info("No adapter registered for %s (category=%s) — skipping", entry, category)
            continue

        logger.info("Trying %s for %r...", entry, course_name)
        index = indices[adapter]
        match = adapter.match(course_name, index)

        if match is not None and match.confidence >= threshold:
            logger.info("Matched %s at confidence %.2f — downloading", entry, match.confidence)
            return adapter.download(match, tier=category)

        confidence_display = f"{match.confidence:.2f}" if match is not None else "n/a"
        logger.info(
            "No match / confidence %s below threshold %.2f for %s — falling through",
            confidence_display, threshold, entry,
        )

    logger.info("Exhausted retrieval_order for %s — no source found for %r", tier_group, course_name)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_orchestrator.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: implement retrieve_course() retrieval-order fallthrough logic"
```

---

### Task 3: Registry construction + live smoke test

**Files:**
- Modify: `src/retrieve/orchestrator.py`

**Interfaces:**
- Consumes: `load_config`, `build_indices`, `retrieve_course` (Tasks 1-2); `AICTEAdapter` (existing, `src/retrieve/aicte.py`); `Careers360Adapter` (existing, `src/retrieve/careers360.py`).
- Produces: no new interfaces — this is the `__main__` wiring task, matching the manual-verification pattern each adapter's own `__main__` block already uses. No new pytest tests (consistent with existing adapter smoke tests not being part of the automated suite).

- [ ] **Step 1: Run the full test suite as a baseline**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS — all 32 tests (22 pre-existing + 10 from Tasks 1-2).

- [ ] **Step 2: Add the `__main__` smoke test block**

Append to the end of `src/retrieve/orchestrator.py`:

```python
if __name__ == "__main__":
    from src.retrieve.aicte import AICTEAdapter
    from src.retrieve.careers360 import Careers360Adapter

    TEST_COURSES = [
        "Mechanical Engineering",
        "Civil Engineering",
        "Computer Science Engineering",
        "Electrical Engineering",
        "Aerospace Engineering",
    ]

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = load_config()
    retrieval_order = config["retrieval_order"]
    threshold = config["matching"]["threshold"]

    aicte_adapter = AICTEAdapter()
    careers360_adapter = Careers360Adapter()

    registry = {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
    }

    print("Building indices...")
    indices = build_indices([aicte_adapter, careers360_adapter])
    print(f"AICTE index: {len(indices[aicte_adapter])} entries")
    print(f"Careers360 index: {len(indices[careers360_adapter])} entries\n")

    for course in TEST_COURSES:
        print(f"--- {course} ---")
        result = retrieve_course(
            course_name=course,
            category="engineering",
            tier_group="strong_tier",
            retrieval_order=retrieval_order,
            indices=indices,
            registry=registry,
            threshold=threshold,
        )
        if result is None:
            print("  -> NO SOURCE FOUND\n")
        else:
            print(f"  -> source_type: {result.source_type.value}")
            print(f"     local_path:  {result.local_path}")
            print(f"     confidence:  {result.match_confidence:.2f}\n")
```

- [ ] **Step 3: Run the smoke test live**

Run: `.venv/Scripts/python.exe -m src.retrieve.orchestrator`
Expected: for each of the 5 courses, either a `Matched fact_supplement_independent_writing_required ... downloading` log line (Careers360 wins first, per the Careers360-first retrieval order) or, if that log shows a fallthrough, a subsequent AICTE attempt. Mechanical/Civil/Computer Science/Electrical should resolve via Careers360 (confidence 1.00 per the live runs already recorded in `CLAUDE.md`); Aerospace Engineering's outcome depends on Careers360's live confidence for that course — inspect the log to see which source (if any) it resolves through.

- [ ] **Step 4: Run the full test suite once more**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (32 passed) — the `__main__` block is not imported/executed during test collection, so this should be unaffected by Step 2-3.

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/orchestrator.py
git commit -m "feat: wire orchestrator registry and add live smoke test against real adapters"
```

---

## Post-plan state

After Task 3, Stage 1's declared `retrieval_order` is no longer a dead config value — `retrieve_course()` consumes it end to end for the engineering category, live-verified against the real AICTE and Careers360 sites. Extending to medicine/law/commerce/animation categories only requires adding entries to the `registry` dict (and, for regulator categories, writing the adapter itself) — no changes to `retrieve_course()`'s traversal logic. The batch wrapper (per-course failure isolation, rate-limiting, tier-stratified reporting) remains a separate, deliberately deferred task per the design doc's Scope section.
