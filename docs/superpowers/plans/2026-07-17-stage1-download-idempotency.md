# Stage 1 Retrieve: download() + Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `download()` on `AICTEAdapter` and `Careers360Adapter` with hash-based idempotency and SQLite manifest persistence, completing Stage 1 (Retrieve) end to end.

**Architecture:** A shared `src/retrieve/manifest.py` module owns all SQLite access (`get_entry`, `insert_entry`) against `data/manifest.db`. Each adapter's `download()` checks the manifest for an existing `(course_name, matched_url)` row first (idempotency gate); on a miss it fetches via `requests.get`, hashes the content (sha256), writes it to `data/raw/<tier>/<source_type>/<course_slug>.<ext>`, and inserts a new manifest row.

**Tech Stack:** Python 3.11+, `sqlite3` (stdlib), `requests`, `pydantic`, `pytest` + `unittest.mock`.

## Global Constraints

- Type hints required on every function (project convention).
- No new dependencies — `sqlite3` is stdlib; no new entries in `pyproject.toml`.
- Failed HTTP requests (4xx/5xx/timeout) propagate the exception; no manifest row is written for a failed attempt (spec: "Error handling").
- Idempotency is keyed on `(course_name, matched_url)` already present in the manifest — a hit skips the HTTP request entirely (spec: "Idempotency semantics").
- `content_type`/`content_length`/`http_status` are only ever populated on success (spec: "Manifest fields").
- `data/raw/<tier>/<source_type>/<course_name_slug>.<ext>` is the file layout; `source_type` uses the new `SourceType` enum's value (spec: "File layout").
- Full design reference: `docs/superpowers/specs/2026-07-17-stage1-download-idempotency-design.md`.

---

### Task 1: Schema — `SourceType` enum + `ManifestEntry` new fields

**Files:**
- Modify: `src/schema.py`
- Test: `tests/test_schema.py` (new file)

**Interfaces:**
- Produces: `SourceType` enum (`REGULATOR_PDF`, `REGULATOR_WEBPAGE`, `UNIVERSITY_WEBPAGE`, `AGGREGATOR_WEBPAGE`, `NONE`) importable as `from src.schema import SourceType`.
- Produces: `ManifestEntry.source_type: SourceType` (was `str`), plus new optional fields `content_type: Optional[str]`, `content_length: Optional[int]`, `http_status: Optional[int]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_schema.py`:

```python
from src.schema import ManifestEntry, SourceType


def test_manifest_entry_defaults_new_fields_to_none():
    entry = ManifestEntry(
        course_name="Mechanical Engineering",
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        match_confidence=0.92,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )
    assert entry.content_type is None
    assert entry.content_length is None
    assert entry.http_status is None


def test_source_type_has_aggregator_webpage_value():
    assert SourceType.AGGREGATOR_WEBPAGE.value == "aggregator_webpage"


def test_manifest_entry_accepts_source_type_enum():
    entry = ManifestEntry(
        course_name="Some Course",
        tier="engineering",
        source_type=SourceType.AGGREGATOR_WEBPAGE,
        match_confidence=0.5,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )
    assert entry.source_type == SourceType.AGGREGATOR_WEBPAGE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'SourceType' from 'src.schema'`

- [ ] **Step 3: Implement the schema change**

In `src/schema.py`, add the `SourceType` enum directly after the existing `SourceCategory` enum (before `class SourceRef`):

```python
class SourceType(str, Enum):
    REGULATOR_PDF = "regulator_pdf"
    REGULATOR_WEBPAGE = "regulator_webpage"
    UNIVERSITY_WEBPAGE = "university_webpage"
    AGGREGATOR_WEBPAGE = "aggregator_webpage"
    NONE = "none"
```

Then replace the `ManifestEntry` class (currently the last class in the file) with:

```python
class ManifestEntry(BaseModel):
    course_name: str
    tier: str
    source_type: SourceType
    matched_url: Optional[str] = None
    local_path: Optional[str] = None
    file_hash: Optional[str] = None
    match_confidence: float = 0.0
    retrieved_at: str
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    http_status: Optional[int] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/schema.py tests/test_schema.py
git commit -m "feat: add SourceType enum and HTTP metadata fields to ManifestEntry"
```

---

### Task 2: `src/retrieve/manifest.py` — SQLite manifest module

**Files:**
- Create: `src/retrieve/manifest.py`
- Test: `tests/test_manifest.py` (new file)

**Interfaces:**
- Consumes: `ManifestEntry`, `SourceType` from `src.schema` (Task 1).
- Produces: `manifest.get_entry(course_name: str, matched_url: str, db_path: Path | None = None) -> ManifestEntry | None`
- Produces: `manifest.insert_entry(entry: ManifestEntry, db_path: Path | None = None) -> None`
- Produces: `manifest.DEFAULT_DB_PATH: Path` (module-level constant, `Path("data/manifest.db")`)

**Important implementation note:** `db_path` must default to `None` and resolve to `DEFAULT_DB_PATH` *inside* the function body (`if db_path is None: db_path = DEFAULT_DB_PATH`), not as the parameter's default value directly. Python evaluates parameter defaults once at function-definition time, so `db_path: Path = DEFAULT_DB_PATH` would bake in the path at import time and tests wouldn't be able to isolate it via a temp path passed explicitly. (Tests here pass `db_path` explicitly, so this mainly matters for consistency with Task 3/4's adapter tests, which rely on the same call-time-lookup behavior for `RAW_DIR`.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manifest.py`:

```python
from src.retrieve import manifest
from src.schema import ManifestEntry, SourceType


def _entry(course_name="Mechanical Engineering", matched_url="https://example.com/mech.pdf"):
    return ManifestEntry(
        course_name=course_name,
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        matched_url=matched_url,
        local_path="data/raw/engineering/regulator_pdf/mechanical_engineering.pdf",
        file_hash="abc123",
        match_confidence=0.92,
        retrieved_at="2026-07-17T12:00:00+00:00",
        content_type="application/pdf",
        content_length=1024,
        http_status=200,
    )


def test_get_entry_returns_none_when_missing(tmp_path):
    db_path = tmp_path / "manifest.db"
    result = manifest.get_entry(
        "Mechanical Engineering", "https://example.com/mech.pdf", db_path=db_path
    )
    assert result is None


def test_insert_then_get_round_trips_all_fields(tmp_path):
    db_path = tmp_path / "manifest.db"
    entry = _entry()

    manifest.insert_entry(entry, db_path=db_path)
    result = manifest.get_entry(entry.course_name, entry.matched_url, db_path=db_path)

    assert result == entry


def test_get_entry_keys_on_course_name_and_url(tmp_path):
    db_path = tmp_path / "manifest.db"
    manifest.insert_entry(_entry(), db_path=db_path)

    assert manifest.get_entry(
        "Mechanical Engineering", "https://example.com/other.pdf", db_path=db_path
    ) is None
    assert manifest.get_entry(
        "Civil Engineering", "https://example.com/mech.pdf", db_path=db_path
    ) is None


def test_get_entry_creates_db_file_if_missing(tmp_path):
    db_path = tmp_path / "nested" / "manifest.db"
    result = manifest.get_entry("X", "https://example.com/x.pdf", db_path=db_path)
    assert result is None
    assert db_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.retrieve.manifest'`

- [ ] **Step 3: Implement `src/retrieve/manifest.py`**

```python
import sqlite3
from pathlib import Path
from typing import Optional

from src.schema import ManifestEntry, SourceType

DEFAULT_DB_PATH = Path("data/manifest.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS manifest (
    course_name TEXT NOT NULL,
    tier TEXT NOT NULL,
    source_type TEXT NOT NULL,
    matched_url TEXT,
    local_path TEXT,
    file_hash TEXT,
    match_confidence REAL NOT NULL,
    retrieved_at TEXT NOT NULL,
    content_type TEXT,
    content_length INTEGER,
    http_status INTEGER,
    PRIMARY KEY (course_name, matched_url)
)
"""

_SELECT = """
SELECT course_name, tier, source_type, matched_url, local_path, file_hash,
       match_confidence, retrieved_at, content_type, content_length, http_status
FROM manifest WHERE course_name = ? AND matched_url = ?
"""

_INSERT = """
INSERT INTO manifest (
    course_name, tier, source_type, matched_url, local_path, file_hash,
    match_confidence, retrieved_at, content_type, content_length, http_status
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _connect(db_path: Optional[Path]) -> sqlite3.Connection:
    resolved = db_path if db_path is not None else DEFAULT_DB_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def get_entry(
    course_name: str, matched_url: str, db_path: Optional[Path] = None
) -> Optional[ManifestEntry]:
    conn = _connect(db_path)
    try:
        row = conn.execute(_SELECT, (course_name, matched_url)).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return ManifestEntry(
        course_name=row[0],
        tier=row[1],
        source_type=SourceType(row[2]),
        matched_url=row[3],
        local_path=row[4],
        file_hash=row[5],
        match_confidence=row[6],
        retrieved_at=row[7],
        content_type=row[8],
        content_length=row[9],
        http_status=row[10],
    )


def insert_entry(entry: ManifestEntry, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            _INSERT,
            (
                entry.course_name,
                entry.tier,
                entry.source_type.value,
                entry.matched_url,
                entry.local_path,
                entry.file_hash,
                entry.match_confidence,
                entry.retrieved_at,
                entry.content_type,
                entry.content_length,
                entry.http_status,
            ),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/manifest.py tests/test_manifest.py
git commit -m "feat: add SQLite manifest module for Stage 1 idempotency"
```

---

### Task 3: `AICTEAdapter.download()`

**Files:**
- Modify: `src/retrieve/base.py` (update `SourceAdapter.download` signature)
- Modify: `src/retrieve/aicte.py`
- Test: `tests/test_aicte.py` (new file)

**Interfaces:**
- Consumes: `manifest.get_entry`, `manifest.insert_entry` (Task 2); `ManifestEntry`, `SourceType` (Task 1); `SourceMatch` (existing, `src/retrieve/base.py`).
- Produces: `AICTEAdapter.download(self, match: SourceMatch, tier: str) -> ManifestEntry`
- Produces: `AICTEAdapter.SOURCE_TYPE: SourceType` class attribute (`SourceType.REGULATOR_PDF`)
- Produces: module-level `RAW_DIR: Path` in `src/retrieve/aicte.py` (`Path("data/raw")`), referenced directly (not as a default parameter) inside `download()` so tests can monkeypatch it.

- [ ] **Step 1: Update the `SourceAdapter` protocol**

In `src/retrieve/base.py`, replace the `download` method signature:

```python
    def download(self, match: SourceMatch, tier: str) -> ManifestEntry:
        """Download match's content, save it, and record a manifest entry.

        Idempotent: if a manifest entry already exists for
        (course_name, matched_url), returns it without making an HTTP request.
        """
        ...
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_aicte.py`:

```python
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.retrieve.aicte import AICTEAdapter
from src.retrieve.base import SourceMatch
from src.schema import SourceType

PDF_BYTES = b"%PDF-1.4 fake pdf bytes"


@pytest.fixture
def adapter():
    return AICTEAdapter()


@pytest.fixture
def match():
    return SourceMatch(
        course_name="Mechanical Engineering",
        matched_name="Revised Model Curriculum for UG Degree Course in Mechanical Engineering",
        matched_url="https://www.aicte.gov.in/sites/default/files/mechanical.pdf",
        confidence=0.92,
    )


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.manifest.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.aicte.RAW_DIR", tmp_path / "raw")


def _mock_response(content=PDF_BYTES, status_code=200, content_type="application/pdf"):
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.aicte.requests.get")
def test_download_writes_file_and_manifest_entry(mock_get, adapter, match):
    mock_get.return_value = _mock_response()

    entry = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert entry.course_name == "Mechanical Engineering"
    assert entry.tier == "engineering"
    assert entry.source_type == SourceType.REGULATOR_PDF
    assert entry.http_status == 200
    assert entry.content_type == "application/pdf"
    assert entry.content_length == len(PDF_BYTES)
    assert entry.file_hash == hashlib.sha256(PDF_BYTES).hexdigest()
    assert Path(entry.local_path).read_bytes() == PDF_BYTES
    assert Path(entry.local_path).name == "mechanical_engineering.pdf"


@patch("src.retrieve.aicte.requests.get")
def test_second_download_for_same_course_and_url_skips_http_call(mock_get, adapter, match):
    mock_get.return_value = _mock_response()

    first = adapter.download(match, tier="engineering")
    second = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert second == first


@patch("src.retrieve.aicte.requests.get")
def test_different_url_triggers_new_download(mock_get, adapter, match):
    mock_get.return_value = _mock_response()
    adapter.download(match, tier="engineering")

    other_match = SourceMatch(
        course_name="Civil Engineering",
        matched_name="Revised Model Curriculum for UG Degree Course in Civil Engineering",
        matched_url="https://www.aicte.gov.in/sites/default/files/civil.pdf",
        confidence=0.9,
    )
    adapter.download(other_match, tier="engineering")

    assert mock_get.call_count == 2


@patch("src.retrieve.aicte.requests.get")
def test_http_failure_propagates_and_writes_no_manifest_entry(mock_get, adapter, match):
    response = _mock_response(status_code=404)
    response.raise_for_status.side_effect = Exception("404 Client Error")
    mock_get.return_value = response

    with pytest.raises(Exception, match="404 Client Error"):
        adapter.download(match, tier="engineering")

    from src.retrieve import manifest

    assert manifest.get_entry(match.course_name, match.matched_url) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_aicte.py -v`
Expected: FAIL — `AttributeError` / `NotImplementedError` (`download` still raises `NotImplementedError`)

- [ ] **Step 4: Implement `download()` in `src/retrieve/aicte.py`**

Add these imports at the top of `src/retrieve/aicte.py` (alongside the existing ones):

```python
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from src.retrieve import manifest
from src.schema import ManifestEntry, SourceType
```

Add module-level constant near `REQUEST_TIMEOUT`:

```python
RAW_DIR = Path("data/raw")
```

Add a module-level slug helper (above the `AICTEAdapter` class):

```python
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
```

Add a class attribute inside `AICTEAdapter` (alongside `__init__`):

```python
    SOURCE_TYPE = SourceType.REGULATOR_PDF
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

        local_path = RAW_DIR / tier / self.SOURCE_TYPE.value / f"{_slugify(match.course_name)}.pdf"
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_aicte.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/retrieve/base.py src/retrieve/aicte.py tests/test_aicte.py
git commit -m "feat: implement AICTEAdapter.download() with idempotent manifest writes"
```

---

### Task 4: `Careers360Adapter.download()`

**Files:**
- Modify: `src/retrieve/careers360.py`
- Test: `tests/test_careers360.py` (extend existing file)

**Interfaces:**
- Consumes: `manifest.get_entry`, `manifest.insert_entry` (Task 2); `ManifestEntry`, `SourceType` (Task 1); `SourceMatch` (existing).
- Produces: `Careers360Adapter.download(self, match: SourceMatch, tier: str) -> ManifestEntry`
- Produces: `Careers360Adapter.SOURCE_TYPE: SourceType` class attribute (`SourceType.AGGREGATOR_WEBPAGE`)
- Produces: module-level `RAW_DIR: Path` in `src/retrieve/careers360.py` (`Path("data/raw")`)

This mirrors Task 3 exactly, except the saved file extension is `.html` (not `.pdf`) and `SOURCE_TYPE` is `AGGREGATOR_WEBPAGE`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_careers360.py` (add these imports at the top alongside the existing `import pytest`):

```python
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

from src.schema import SourceType

HTML_BYTES = b"<html><body>Mechanical Engineering course page</body></html>"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieve.manifest.DEFAULT_DB_PATH", tmp_path / "manifest.db")
    monkeypatch.setattr("src.retrieve.careers360.RAW_DIR", tmp_path / "raw")


def _mock_response(content=HTML_BYTES, status_code=200, content_type="text/html; charset=utf-8"):
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    response.raise_for_status = Mock()
    return response


@patch("src.retrieve.careers360.requests.get")
def test_download_writes_html_file_and_manifest_entry(mock_get, adapter):
    mock_get.return_value = _mock_response()
    match = adapter.match("Mechanical Engineering", FIXTURE_INDEX)

    entry = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert entry.source_type == SourceType.AGGREGATOR_WEBPAGE
    assert entry.http_status == 200
    assert entry.content_type == "text/html; charset=utf-8"
    assert entry.content_length == len(HTML_BYTES)
    assert entry.file_hash == hashlib.sha256(HTML_BYTES).hexdigest()
    assert Path(entry.local_path).read_bytes() == HTML_BYTES
    assert Path(entry.local_path).suffix == ".html"


@patch("src.retrieve.careers360.requests.get")
def test_second_download_for_same_course_and_url_skips_http_call(mock_get, adapter):
    mock_get.return_value = _mock_response()
    match = adapter.match("Mechanical Engineering", FIXTURE_INDEX)

    first = adapter.download(match, tier="engineering")
    second = adapter.download(match, tier="engineering")

    assert mock_get.call_count == 1
    assert second == first


@patch("src.retrieve.careers360.requests.get")
def test_http_failure_propagates_and_writes_no_manifest_entry(mock_get, adapter):
    match = adapter.match("Mechanical Engineering", FIXTURE_INDEX)
    response = _mock_response(status_code=403)
    response.raise_for_status.side_effect = Exception("403 Client Error")
    mock_get.return_value = response

    with pytest.raises(Exception, match="403 Client Error"):
        adapter.download(match, tier="engineering")

    from src.retrieve import manifest

    assert manifest.get_entry(match.course_name, match.matched_url) is None
```

(`adapter` and `FIXTURE_INDEX` are already defined earlier in this file — reuse them, don't redefine.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_careers360.py -v`
Expected: FAIL — `NotImplementedError` (`download` still raises it)

- [ ] **Step 3: Implement `download()` in `src/retrieve/careers360.py`**

Add these imports at the top of `src/retrieve/careers360.py`:

```python
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from src.retrieve import manifest
from src.schema import ManifestEntry, SourceType
```

Add module-level constant near `REQUEST_TIMEOUT`:

```python
RAW_DIR = Path("data/raw")
```

Add the slug helper (above the `Careers360Adapter` class):

```python
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
```

Add a class attribute inside `Careers360Adapter`:

```python
    SOURCE_TYPE = SourceType.AGGREGATOR_WEBPAGE
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

Run: `pytest tests/test_careers360.py -v`
Expected: PASS (all tests, existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add src/retrieve/careers360.py tests/test_careers360.py
git commit -m "feat: implement Careers360Adapter.download() with idempotent manifest writes"
```

---

### Task 5: Full-suite verification + smoke-test wiring

**Files:**
- Modify: `src/retrieve/aicte.py` (extend `__main__` block)
- Modify: `src/retrieve/careers360.py` (extend `__main__` block)

**Interfaces:**
- Consumes: everything from Tasks 1–4. No new interfaces produced — this task wires the existing `download()` into each adapter's manual smoke-test entrypoint and runs the full test suite as a final gate.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS — all tests from `tests/test_schema.py`, `tests/test_manifest.py`, `tests/test_aicte.py`, `tests/test_careers360.py`, plus any pre-existing tests.

- [ ] **Step 2: Extend `AICTEAdapter`'s `__main__` smoke test**

In `src/retrieve/aicte.py`, inside the `if __name__ == "__main__":` block, after the existing match-printing loop, add:

```python
    print("--- download() smoke test (first match only) ---")
    first_match = adapter.match(TEST_COURSES[0], index)
    if first_match is not None:
        entry = adapter.download(first_match, tier="engineering")
        print(f"downloaded: {entry.local_path}")
        print(f"  hash:   {entry.file_hash}")
        print(f"  status: {entry.http_status}")
```

- [ ] **Step 3: Extend `Careers360Adapter`'s `__main__` smoke test**

In `src/retrieve/careers360.py`, inside the `if __name__ == "__main__":` block, after the existing match-printing loop, add:

```python
    print("--- download() smoke test (first match only) ---")
    first_match = adapter.match(TEST_COURSES[0], index)
    if first_match is not None:
        entry = adapter.download(first_match, tier="engineering")
        print(f"downloaded: {entry.local_path}")
        print(f"  hash:   {entry.file_hash}")
        print(f"  status: {entry.http_status}")
```

- [ ] **Step 4: Commit**

```bash
git add src/retrieve/aicte.py src/retrieve/careers360.py
git commit -m "chore: wire download() into adapter smoke tests"
```

---

## Post-plan state

After Task 5, Stage 1 (Retrieve) is functionally complete for the engineering tier: `build_index()` → `match()` → `download()`, idempotent via the SQLite manifest, for both `AICTEAdapter` (regulatory_primary) and `Careers360Adapter` (fact_supplement). Manual verification against the real AICTE/Careers360 sites (running each adapter's `__main__` block for real, not mocked) is a separate, explicit step the user should run themselves before trusting real downloaded content — this plan's tests only prove the logic against mocked HTTP responses.
