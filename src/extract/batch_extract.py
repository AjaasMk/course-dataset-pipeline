import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Callable, Literal, Optional

import anthropic
from pydantic import BaseModel

from src.extract.extractor import extract_course_detail
from src.extract.models import Chunk
from src.extract.retry import call_with_retry
from src.schema import CourseDetail

logger = logging.getLogger(__name__)

CHUNKS_DIR = Path("data/chunks")
EXTRACTED_DIR = Path("data/extracted")
HASH_STORE_PATH = Path("data/extracted/.chunk_hashes.json")

# extract_fn (a real, billed model call) is retried only on transient
# connection/rate-limit errors -- unlike a bare re-run, a dropped connection
# mid-request means Claude may have already processed (and billed) the
# request even though the response never arrived, so a retry here can incur
# a real duplicate charge. Accepted for unattended batch runs: completing
# the batch reliably matters more than an occasional duplicate charge on a
# rare connection drop. Real refusals/truncation/auth/billing errors are
# NOT retried -- they'd fail identically every time or mask a real problem.
_RETRYABLE_ERRORS = (anthropic.APIConnectionError, anthropic.RateLimitError)


class ManifestRow(BaseModel):
    course_name: str
    category: str
    source_type: str
    local_path: str


class ExtractionResult(BaseModel):
    course_name: str
    outcome: Literal["extracted", "extraction_failed", "skipped_unchanged"]
    error: Optional[str] = None


class ExtractionBatchReport(BaseModel):
    results: list[ExtractionResult]


def load_chunks(chunk_path: Path) -> list[Chunk]:
    data = json.loads(chunk_path.read_text(encoding="utf-8"))
    return [Chunk.model_validate(item) for item in data]


def compute_chunk_hash(chunks: list[Chunk]) -> str:
    """Hash of a course's reconstructed document text — used to skip
    re-extraction (Hard Constraint 5: idempotent via hash-based diffing) when
    the underlying chunks haven't actually changed since the last run, e.g.
    after a read_html.py fix that only affects some sources."""
    document_text = "\n\n".join(c.text for c in sorted(chunks, key=lambda c: c.chunk_id))
    return hashlib.sha256(document_text.encode("utf-8")).hexdigest()


def load_hash_store(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_hash_store(path: Path, store: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")


def read_manifest_rows(db_path: Path) -> list[ManifestRow]:
    # A course can end up with more than one manifest row if a single-source
    # adapter (e.g. AICTEAdapter's own __main__ block) was run in isolation
    # against a course name that's also in the real pilot list, alongside the
    # real retrieve_course() orchestrated result. Confirmed live: exactly one
    # such case (Mechanical Engineering, AICTE + Careers360). Extraction
    # needs exactly one document per course, so keep the most recently
    # retrieved row -- that's always the real orchestrated retrieve_course()
    # result, since ad-hoc adapter test runs predate the actual pilot batch.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT course_name, tier, source_type, local_path, retrieved_at FROM manifest "
            "ORDER BY retrieved_at ASC"
        ).fetchall()
    finally:
        conn.close()

    latest_by_course: dict[str, tuple] = {}
    for r in rows:
        latest_by_course[r[0]] = r  # later rows (later retrieved_at) overwrite earlier ones

    return [
        ManifestRow(course_name=r[0], category=r[1], source_type=r[2], local_path=r[3])
        for r in latest_by_course.values()
    ]


def extract_all_courses(
    manifest_rows: list[ManifestRow],
    chunks_dir: Path,
    extracted_dir: Path,
    extract_fn: Callable[[list[Chunk], str, str], CourseDetail] = extract_course_detail,
    hash_store_path: Path = HASH_STORE_PATH,
) -> ExtractionBatchReport:
    """Extract CourseDetail for every course in manifest_rows, isolating per-course
    failures the same way src/retrieve/batch.py does for retrieval: an exception
    is caught, logged, recorded as "extraction_failed", and the batch continues
    rather than aborting. extract_fn itself is retried on transient connection/
    rate-limit errors before being treated as a failure (see _RETRYABLE_ERRORS).

    Idempotent via hash-based diffing (Hard Constraint 5): each course's
    chunks are hashed, and a course is only re-sent to extract_fn (a real,
    billed model call) if its hash differs from the last recorded run, or it
    has no prior output on disk yet. Unchanged courses are skipped and their
    existing data/extracted/<slug>.json is left as-is.
    """
    extracted_dir.mkdir(parents=True, exist_ok=True)
    hash_store = load_hash_store(hash_store_path)
    results: list[ExtractionResult] = []

    for row in manifest_rows:
        slug = Path(row.local_path).stem
        chunk_path = chunks_dir / f"{slug}__{row.source_type}.json"
        out_path = extracted_dir / f"{slug}.json"

        try:
            chunks = load_chunks(chunk_path)
        except Exception as exc:
            logger.info("Course %r extraction failed: %s", row.course_name, exc)
            results.append(
                ExtractionResult(course_name=row.course_name, outcome="extraction_failed", error=str(exc))
            )
            continue

        new_hash = compute_chunk_hash(chunks)
        if hash_store.get(slug) == new_hash and out_path.exists():
            logger.info("Course %r unchanged since last run, skipping", row.course_name)
            results.append(ExtractionResult(course_name=row.course_name, outcome="skipped_unchanged"))
            continue

        try:
            course_detail = call_with_retry(
                lambda: extract_fn(chunks, row.course_name, row.category),
                retryable_errors=_RETRYABLE_ERRORS,
                description=f"extract_course_detail({row.course_name!r})",
            )
        except Exception as exc:
            logger.info("Course %r extraction failed: %s", row.course_name, exc)
            results.append(
                ExtractionResult(course_name=row.course_name, outcome="extraction_failed", error=str(exc))
            )
            continue

        out_path.write_text(course_detail.model_dump_json(indent=2), encoding="utf-8")
        hash_store[slug] = new_hash
        results.append(ExtractionResult(course_name=row.course_name, outcome="extracted"))

    save_hash_store(hash_store_path, hash_store)
    return ExtractionBatchReport(results=results)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    manifest_rows = read_manifest_rows(Path("data/manifest.db"))
    report = extract_all_courses(manifest_rows, CHUNKS_DIR, EXTRACTED_DIR)

    extracted = sum(1 for r in report.results if r.outcome == "extracted")
    skipped = sum(1 for r in report.results if r.outcome == "skipped_unchanged")
    failed = sum(1 for r in report.results if r.outcome == "extraction_failed")
    print(
        f"Extracted {extracted}/{len(report.results)} courses "
        f"({skipped} unchanged/skipped, {failed} failed)."
    )
    if failed:
        for r in report.results:
            if r.outcome == "extraction_failed":
                print(f"  FAILED: {r.course_name}: {r.error}")
