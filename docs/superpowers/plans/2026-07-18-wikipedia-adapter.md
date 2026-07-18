# WikipediaAdapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `WikipediaAdapter` that closes real, confirmed retrieval gaps (Marketing, Accounting, Cybersecurity, Software Engineering, Marine Engineering, and likely several medicine terms) by retrieving real, citable Wikipedia articles — never an LLM's own uncited knowledge.

**Architecture:** Unlike AICTE/Careers360, Wikipedia has no pre-crawlable listing page — `build_index()` returns `{}` and `match()` does a live search per course against Wikipedia's free REST search API, scoring candidates by `max(title_similarity, excerpt_similarity)` rather than title alone. `download()` follows the established idempotent-manifest pattern unchanged. A pre-existing config gap (`strong_tier` missing `general_background` in its `retrieval_order`) is fixed as part of this work, without which the new adapter would never be tried for 3 of its 5 target courses.

**Tech Stack:** Python 3.11+ (`requests`, `rapidfuzz` — already dependencies, no new ones), `pytest`.

## Global Constraints

- Type hints required on every function (project convention).
- No new dependencies.
- `WikipediaAdapter.build_index()` always returns `{}` — this is a documented, intentional deviation from `SourceAdapter`'s "crawl a listing page" contract, not a bug. `match()` returns `None` only when the live search API returns zero results, and ignores the `index` parameter entirely.
- Confidence scoring uses `max(token_set_ratio(query, title), token_set_ratio(query, excerpt_with_html_stripped))` across up to 5 search results — never trust Wikipedia's external rank blindly; the adapter's own scoring selects the best candidate.
- `download()` saves raw article HTML as-is (same boundary as every other adapter — Stage 1 fetches/stores, Stage 2 parses).
- No per-source-category threshold change to `retrieve_course()` — that function and its existing tests are not modified by this plan.
- Full design reference: `docs/superpowers/specs/2026-07-18-wikipedia-adapter-design.md`.

---

### Task 1: Schema, config fix, and inference mapping

**Files:**
- Modify: `src/schema.py`
- Modify: `config/sources.yaml`
- Modify: `src/retrieve/batch.py`
- Test: `tests/test_schema.py`, `tests/test_batch.py`, `tests/test_pilot_courses.py`

**Interfaces:**
- Produces: `SourceType.GENERAL_BACKGROUND_WEBPAGE` (new enum value, `src/schema.py`).
- Produces: `config/sources.yaml`'s `retrieval_order.strong_tier` gains `general_background` as a 4th entry.
- Produces: `batch.py`'s `_SOURCE_TYPE_TO_CATEGORY` gains `SourceType.GENERAL_BACKGROUND_WEBPAGE: "general_background"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_schema.py`:

```python
def test_source_type_has_general_background_webpage_value():
    assert SourceType.GENERAL_BACKGROUND_WEBPAGE.value == "general_background_webpage"
```

(This file already imports `SourceType` at the top — no new import needed.)

Append to `tests/test_batch.py`:

```python
def test_infer_source_category_for_general_background_webpage():
    assert batch.infer_source_category(SourceType.GENERAL_BACKGROUND_WEBPAGE) == "general_background"
```

Append to `tests/test_pilot_courses.py`:

```python
def test_strong_tier_includes_general_background_fallback():
    sources = load_config()
    assert "general_background" in sources["retrieval_order"]["strong_tier"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_schema.py tests/test_batch.py tests/test_pilot_courses.py -v`
Expected: FAIL — `AttributeError: GENERAL_BACKGROUND_WEBPAGE` (schema test), similar for the batch test, and an `AssertionError` for the pilot-courses test (the key isn't in `strong_tier` yet).

- [ ] **Step 3: Add `SourceType.GENERAL_BACKGROUND_WEBPAGE` to `src/schema.py`**

Replace:

```python
class SourceType(str, Enum):
    REGULATOR_PDF = "regulator_pdf"
    REGULATOR_WEBPAGE = "regulator_webpage"
    UNIVERSITY_WEBPAGE = "university_webpage"
    AGGREGATOR_WEBPAGE = "aggregator_webpage"
    NONE = "none"
```

with:

```python
class SourceType(str, Enum):
    REGULATOR_PDF = "regulator_pdf"
    REGULATOR_WEBPAGE = "regulator_webpage"
    UNIVERSITY_WEBPAGE = "university_webpage"
    AGGREGATOR_WEBPAGE = "aggregator_webpage"
    GENERAL_BACKGROUND_WEBPAGE = "general_background_webpage"
    NONE = "none"
```

- [ ] **Step 4: Fix `strong_tier`'s `retrieval_order` in `config/sources.yaml`**

Replace:

```yaml
  strong_tier: # Engineering, Medicine
    - fact_supplement_independent_writing_required
    - regulatory_primary
    - syllabus_supplement
```

with:

```yaml
  strong_tier: # Engineering, Medicine
    - fact_supplement_independent_writing_required
    - regulatory_primary
    - syllabus_supplement
    - general_background
```

- [ ] **Step 5: Add the mapping in `src/retrieve/batch.py`**

Replace:

```python
_SOURCE_TYPE_TO_CATEGORY = {
    SourceType.REGULATOR_PDF: "regulatory_primary",
    SourceType.REGULATOR_WEBPAGE: "regulatory_primary",
    SourceType.AGGREGATOR_WEBPAGE: "fact_supplement_independent_writing_required",
}
```

with:

```python
_SOURCE_TYPE_TO_CATEGORY = {
    SourceType.REGULATOR_PDF: "regulatory_primary",
    SourceType.REGULATOR_WEBPAGE: "regulatory_primary",
    SourceType.AGGREGATOR_WEBPAGE: "fact_supplement_independent_writing_required",
    SourceType.GENERAL_BACKGROUND_WEBPAGE: "general_background",
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_schema.py tests/test_batch.py tests/test_pilot_courses.py -v`
Expected: PASS (all passed, no regressions in these three files)

- [ ] **Step 7: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (55 passed — 52 pre-existing + 3 new)

- [ ] **Step 8: Commit**

```bash
git add src/schema.py config/sources.yaml src/retrieve/batch.py tests/test_schema.py tests/test_batch.py tests/test_pilot_courses.py
git commit -m "fix: add general_background to strong_tier retrieval_order, add GENERAL_BACKGROUND_WEBPAGE source type"
```

---

### Task 2: `WikipediaAdapter.build_index()` + `match()`

**Files:**
- Create: `src/retrieve/wikipedia.py`
- Test: `tests/test_wikipedia.py` (new file)

**Interfaces:**
- Consumes: `SourceMatch` (existing, `src/retrieve/base.py`).
- Produces: `WikipediaAdapter.build_index(self) -> dict[str, str]` — always returns `{}`.
- Produces: `WikipediaAdapter.match(self, course_name: str, index: dict[str, str]) -> SourceMatch | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wikipedia.py`:

```python
from unittest.mock import Mock, patch

import pytest

from src.retrieve.wikipedia import WikipediaAdapter


@pytest.fixture
def adapter():
    return WikipediaAdapter()


def _mock_search_response(pages):
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"pages": pages})
    return response


def test_build_index_returns_empty_dict(adapter):
    assert adapter.build_index() == {}


@patch("src.retrieve.wikipedia.requests.get")
def test_match_returns_none_when_no_pages_found(mock_get, adapter):
    mock_get.return_value = _mock_search_response([])

    result = adapter.match("Nonexistent Zzzqqq Course", {})

    assert result is None


@patch("src.retrieve.wikipedia.requests.get")
def test_match_picks_exact_title_match(mock_get, adapter):
    mock_get.return_value = _mock_search_response([
        {"key": "Marketing", "title": "Marketing", "excerpt": "Marketing is the act of acquiring customers"},
        {"key": "Digital_marketing", "title": "Digital marketing", "excerpt": "search engine marketing (SEM)"},
    ])

    result = adapter.match("Marketing", {})

    assert result.matched_name == "Marketing"
    assert result.matched_url == "https://en.wikipedia.org/wiki/Marketing"
    assert result.confidence == 1.0


@patch("src.retrieve.wikipedia.requests.get")
def test_match_falls_back_to_excerpt_score_when_title_score_is_low(mock_get, adapter):
    mock_get.return_value = _mock_search_response([
        {
            "key": "Computer_security",
            "title": "Computer security",
            "excerpt": 'Emerging field of computer security <span class="searchmatch">Cybersecurity</span> information technology',
        },
    ])

    result = adapter.match("Cybersecurity", {})

    assert result.matched_name == "Computer security"
    assert result.confidence == 1.0  # excerpt contains the exact query term; title alone scores ~0.73


@patch("src.retrieve.wikipedia.requests.get")
def test_match_prefers_better_scoring_candidate_over_first_result(mock_get, adapter):
    mock_get.return_value = _mock_search_response([
        {"key": "Unrelated_Page", "title": "Unrelated Page", "excerpt": "nothing relevant here at all"},
        {"key": "Software_engineering", "title": "Software engineering", "excerpt": "the application of engineering to software"},
    ])

    result = adapter.match("Software Engineering", {})

    assert result.matched_name == "Software engineering"


def test_match_calls_search_api_with_course_name_and_limit(adapter):
    with patch("src.retrieve.wikipedia.requests.get") as mock_get:
        mock_get.return_value = _mock_search_response([{"key": "X", "title": "X", "excerpt": ""}])
        adapter.match("Some Course", {})

    called_kwargs = mock_get.call_args.kwargs
    assert called_kwargs["params"]["q"] == "Some Course"
    assert called_kwargs["params"]["limit"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wikipedia.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.retrieve.wikipedia'`

- [ ] **Step 3: Create `src/retrieve/wikipedia.py`**

```python
import re

import requests
from rapidfuzz import fuzz, utils

from src.retrieve.base import SourceMatch

SEARCH_API = "https://en.wikipedia.org/w/rest.php/v1/search/page"
ARTICLE_BASE_URL = "https://en.wikipedia.org/wiki/"
USER_AGENT = "course-dataset-pipeline/0.1 (educational course dataset project)"
REQUEST_TIMEOUT = 15
SEARCH_LIMIT = 5

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


class WikipediaAdapter:
    def build_index(self) -> dict[str, str]:
        return {}

    def match(self, course_name: str, index: dict[str, str]) -> SourceMatch | None:
        response = requests.get(
            SEARCH_API,
            params={"q": course_name, "limit": SEARCH_LIMIT},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        pages = response.json().get("pages", [])

        if not pages:
            return None

        scored = []
        for page in pages:
            title = page["title"]
            excerpt = _strip_html(page.get("excerpt", ""))
            title_score = fuzz.token_set_ratio(course_name, title, processor=utils.default_process)
            excerpt_score = fuzz.token_set_ratio(course_name, excerpt, processor=utils.default_process)
            scored.append((max(title_score, excerpt_score), page))

        best_score, best_page = max(scored, key=lambda item: item[0])

        return SourceMatch(
            course_name=course_name,
            matched_name=best_page["title"],
            matched_url=ARTICLE_BASE_URL + best_page["key"],
            confidence=best_score / 100,
        )

    def download(self, match: SourceMatch, tier: str):
        raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wikipedia.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/wikipedia.py tests/test_wikipedia.py
git commit -m "feat: implement WikipediaAdapter.build_index() and .match() with excerpt-aware scoring"
```

---

### Task 3: `WikipediaAdapter.download()`

**Files:**
- Modify: `src/retrieve/wikipedia.py`
- Test: `tests/test_wikipedia.py`

**Interfaces:**
- Consumes: `manifest.get_entry`/`manifest.insert_entry` (existing, `src/retrieve/manifest.py`); `ManifestEntry`, `SourceType` (existing, `src/schema.py`).
- Produces: `WikipediaAdapter.download(self, match: SourceMatch, tier: str) -> ManifestEntry`
- Produces: `WikipediaAdapter.SOURCE_TYPE: SourceType` class attribute (`SourceType.GENERAL_BACKGROUND_WEBPAGE`)
- Produces: module-level `RAW_DIR: Path` in `src/retrieve/wikipedia.py` (`Path("data/raw")`), referenced directly (not as a default parameter) so tests can monkeypatch it — same pattern as `aicte.py`/`careers360.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wikipedia.py` (add these imports at the top alongside the existing ones):

```python
import hashlib
from pathlib import Path

from src.retrieve.base import SourceMatch
from src.schema import SourceType

HTML_BYTES = b"<html><body>Computer security article content</body></html>"
```

Then append:

```python
@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.manifest.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.wikipedia.RAW_DIR", tmp_path / "raw")


def _match(
    course_name="Cybersecurity",
    matched_name="Computer security",
    matched_url="https://en.wikipedia.org/wiki/Computer_security",
    confidence=1.0,
):
    return SourceMatch(course_name=course_name, matched_name=matched_name, matched_url=matched_url, confidence=confidence)


def _mock_download_response(content=HTML_BYTES, status_code=200, content_type="text/html; charset=utf-8"):
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.wikipedia.requests.get")
def test_download_writes_html_file_and_manifest_entry(mock_get, adapter):
    mock_get.return_value = _mock_download_response()
    match = _match()

    entry = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert entry.source_type == SourceType.GENERAL_BACKGROUND_WEBPAGE
    assert entry.http_status == 200
    assert entry.content_type == "text/html; charset=utf-8"
    assert entry.file_hash == hashlib.sha256(HTML_BYTES).hexdigest()
    assert Path(entry.local_path).read_bytes() == HTML_BYTES
    assert Path(entry.local_path).suffix == ".html"


@patch("src.retrieve.wikipedia.requests.get")
def test_second_download_for_same_course_and_url_skips_http_call(mock_get, adapter):
    mock_get.return_value = _mock_download_response()
    match = _match()

    first = adapter.download(match, tier="engineering")
    second = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert second == first


@patch("src.retrieve.wikipedia.requests.get")
def test_http_failure_propagates_and_writes_no_manifest_entry(mock_get, adapter):
    match = _match()
    response = _mock_download_response(status_code=404)
    response.raise_for_status.side_effect = Exception("404 Client Error")
    mock_get.return_value = response

    with pytest.raises(Exception, match="404 Client Error"):
        adapter.download(match, tier="engineering")

    from src.retrieve import manifest
    assert manifest.get_entry(match.course_name, match.matched_url) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wikipedia.py -v`
Expected: FAIL — `NotImplementedError` (`download` still raises it)

- [ ] **Step 3: Implement `download()` in `src/retrieve/wikipedia.py`**

Add these imports at the top of `src/retrieve/wikipedia.py` (alongside the existing ones):

```python
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from src.retrieve import manifest
from src.schema import ManifestEntry, SourceType
```

Add module-level constant near `SEARCH_LIMIT`:

```python
RAW_DIR = Path("data/raw")
```

Add a module-level slug helper (above the `WikipediaAdapter` class):

```python
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
```

Add a class attribute inside `WikipediaAdapter` (alongside `build_index`):

```python
    SOURCE_TYPE = SourceType.GENERAL_BACKGROUND_WEBPAGE
```

Replace the existing `download` method:

```python
    def download(self, match: SourceMatch, tier: str) -> ManifestEntry:
        existing = manifest.get_entry(match.course_name, match.matched_url)
        if existing is not None:
            return existing

        response = requests.get(
            match.matched_url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        local_path = RAW_DIR / tier / self.SOURCE_TYPE.value / f"{_slugify(match.course_name)}.html"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(response.content)

        content_length_header = response.headers.get("Content-Length")

        entry = ManifestEntry(
            course_name=match.course_name,
            tier=tier,
            source_type=self.SOURCE_TYPE,
            matched_url=match.matched_url,
            local_path=str(local_path),
            file_hash=hashlib.sha256(response.content).hexdigest(),
            match_confidence=match.confidence,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            content_type=response.headers.get("Content-Type"),
            content_length=int(content_length_header) if content_length_header is not None else None,
            http_status=response.status_code,
        )
        manifest.insert_entry(entry)
        return entry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wikipedia.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (64 passed — 55 from Task 1 + 9 from Tasks 2-3)

- [ ] **Step 6: Commit**

```bash
git add src/retrieve/wikipedia.py tests/test_wikipedia.py
git commit -m "feat: implement WikipediaAdapter.download() with idempotent manifest writes"
```

---

### Task 4: Registry wiring + live smoke tests + full pilot re-run

**Files:**
- Modify: `src/retrieve/wikipedia.py` (add `__main__` block)
- Modify: `src/retrieve/orchestrator.py` (extend `default_registry()`, update its `__main__`)
- Modify: `src/retrieve/batch.py` (update its `__main__`)

**Interfaces:**
- Consumes: `WikipediaAdapter` (Tasks 2-3); `build_indices`, `load_config` (existing, `orchestrator.py`); `run_batch` (existing, `batch.py`).
- Produces: `default_registry(aicte_adapter: SourceAdapter, careers360_adapter: SourceAdapter, wikipedia_adapter: SourceAdapter) -> dict[SourceCategory, dict[str, SourceAdapter]]` — signature widened from 2 to 3 required adapters. This changes an already-shipped function's signature; both of its existing call sites (`orchestrator.py`'s own `__main__`, `batch.py`'s `__main__`) are updated in this same task, so nothing is left calling it with the old 2-argument form.
- No new pytest tests beyond confirming existing ones still pass — this task is `__main__`-block wiring + live verification, matching the pattern of every prior wiring-only task in this project.

- [ ] **Step 1: Run the full test suite as a baseline**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (64 passed)

- [ ] **Step 2: Add `WikipediaAdapter`'s own `__main__` smoke test**

Append to the end of `src/retrieve/wikipedia.py`:

```python
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    TEST_COURSES = [
        "Marketing",
        "Accounting",
        "Cybersecurity",
        "Software Engineering",
        "Marine Engineering",
    ]

    adapter = WikipediaAdapter()
    print("WikipediaAdapter has no listing page to crawl — build_index() is a no-op:")
    print(f"  build_index() -> {adapter.build_index()!r}\n")

    for course in TEST_COURSES:
        print(f"--- {course} ---")
        match = adapter.match(course, {})
        if match is None:
            print("  -> NO MATCH (search API returned zero results)\n")
            continue
        print(f"  -> matched: {match.matched_name!r}")
        print(f"     url:        {match.matched_url}")
        print(f"     confidence: {match.confidence:.2f}")
        if match.confidence >= 0.80:
            entry = adapter.download(match, tier="engineering")
            print(f"     downloaded: {entry.local_path}")
            print(f"     hash:       {entry.file_hash}")
        else:
            print("     (below 0.80 threshold — retrieve_course() would fall through, not download this)")
        print()
```

- [ ] **Step 3: Run the smoke test live**

Run: `.venv/Scripts/python.exe -m src.retrieve.wikipedia`
Expected: for each of the 5 target courses, a real match against Wikipedia's search API. Marketing/Accounting/Software Engineering/Marine Engineering should match at or near confidence 1.00 (exact or near-exact titles). Cybersecurity should match "Computer security" at confidence 1.00 via the excerpt-scoring path (this is the concrete case this adapter was built to handle — confirm it actually resolves live, not just in the mocked unit test). Report the actual output.

- [ ] **Step 4: Extend `default_registry()` in `src/retrieve/orchestrator.py`**

Replace:

```python
def default_registry(
    aicte_adapter: SourceAdapter, careers360_adapter: SourceAdapter
) -> dict[SourceCategory, dict[str, SourceAdapter]]:
    return {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
    }
```

with:

```python
def default_registry(
    aicte_adapter: SourceAdapter,
    careers360_adapter: SourceAdapter,
    wikipedia_adapter: SourceAdapter,
) -> dict[SourceCategory, dict[str, SourceAdapter]]:
    return {
        SourceCategory.REGULATORY_PRIMARY: {"engineering": aicte_adapter},
        SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": careers360_adapter},
        SourceCategory.GENERAL_BACKGROUND: {"*": wikipedia_adapter},
    }
```

- [ ] **Step 5: Update `orchestrator.py`'s own `__main__` block**

In the `__main__` block, add the import and adapter construction alongside the existing two, and update the `build_indices()`/`default_registry()` calls:

Replace:

```python
    from src.retrieve.aicte import AICTEAdapter
    from src.retrieve.careers360 import Careers360Adapter
```

with:

```python
    from src.retrieve.aicte import AICTEAdapter
    from src.retrieve.careers360 import Careers360Adapter
    from src.retrieve.wikipedia import WikipediaAdapter
```

Replace:

```python
    aicte_adapter = AICTEAdapter()
    careers360_adapter = Careers360Adapter()

    registry = default_registry(aicte_adapter, careers360_adapter)

    print("Building indices...")
    indices = build_indices([aicte_adapter, careers360_adapter])
    print(f"AICTE index: {len(indices[aicte_adapter])} entries")
    print(f"Careers360 index: {len(indices[careers360_adapter])} entries\n")
```

with:

```python
    aicte_adapter = AICTEAdapter()
    careers360_adapter = Careers360Adapter()
    wikipedia_adapter = WikipediaAdapter()

    registry = default_registry(aicte_adapter, careers360_adapter, wikipedia_adapter)

    print("Building indices...")
    indices = build_indices([aicte_adapter, careers360_adapter, wikipedia_adapter])
    print(f"AICTE index: {len(indices[aicte_adapter])} entries")
    print(f"Careers360 index: {len(indices[careers360_adapter])} entries")
    print(f"Wikipedia index: {len(indices[wikipedia_adapter])} entries (always empty — no listing page)\n")
```

- [ ] **Step 6: Update `batch.py`'s `__main__` block**

Apply the identical pattern of changes to `src/retrieve/batch.py`'s `__main__` block: import `WikipediaAdapter`, construct `wikipedia_adapter = WikipediaAdapter()`, pass it into `default_registry(...)` and `build_indices([...])` alongside the other two adapters, matching the exact edits from Step 5.

- [ ] **Step 7: Run the full suite to confirm the refactor didn't break anything**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (64 passed) — no test calls `default_registry()` directly (it's only exercised via the `__main__` blocks), so the signature widening doesn't touch any existing test.

- [ ] **Step 8: Re-run the full 50-course pilot batch live**

Run: `.venv/Scripts/python.exe -m src.retrieve.batch`
Expected: takes several minutes (same as the original run — 50 courses, real network calls, now potentially up to 3 HTTP attempts per course instead of 2 for courses that reach the `general_background` fallback). Compare the new `summary_by_tier` against the prior baseline:

```
strong_tier:  19 fact_supplement / 2 regulatory_primary / 9 no_source_found / 0 errored
medium_tier:   7 fact_supplement / 3 no_source_found / 0 errored
weak_tier:     5 fact_supplement / 5 no_source_found / 0 errored
```

Report the actual new counts — some prior `no_source_found` courses should now show `matched via general_background`. Not every one will necessarily resolve (Wikipedia doesn't have an article for every course either) — report whatever the live run actually shows.

- [ ] **Step 9: Commit**

```bash
git add src/retrieve/wikipedia.py src/retrieve/orchestrator.py src/retrieve/batch.py
git commit -m "feat: wire WikipediaAdapter into the registry and re-verify full pilot coverage"
```

---

## Post-plan state

After Task 4, `general_background` is no longer a no-op fallback — `WikipediaAdapter` is a third, fully working source registered across every tier that declares it in `retrieval_order` (now all three: strong/medium/weak). The five specific gaps that motivated this work (Marketing, Accounting, Cybersecurity, Software Engineering, Marine Engineering) are live-verified against the real Wikipedia API, and the full 50-course pilot is re-run to measure the actual coverage improvement — not assumed, observed. Remaining known gaps (NMC/BCI/UGC regulator adapters, scoped-search for weak tier) are unchanged by this plan and remain separate, explicitly deferred work.
