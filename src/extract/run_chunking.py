import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel

from src.extract.chunker import chunk_document, detect_pdf_sections
from src.extract.readers import read_html, read_pdf

logger = logging.getLogger(__name__)

CHUNKS_DIR = Path("data/chunks")
DEFAULT_MAX_WORKERS = 8


class ChunkResult(BaseModel):
    course_name: str
    source_type: str
    outcome: Literal["chunked", "failed"]
    chunk_count: int = 0
    error: Optional[str] = None


class ChunkBatchReport(BaseModel):
    results: list[ChunkResult]


def _chunk_one_document(
    course_name: str,
    tier: str,
    source_type: str,
    matched_url: str,
    local_path: str,
    client: anthropic.Anthropic,
    chunks_dir: Path,
) -> ChunkResult:
    path = Path(local_path)
    try:
        if path.suffix == ".pdf":
            pages = read_pdf(path)
            sections = detect_pdf_sections(pages)
        else:
            sections = read_html(path)

        chunks = chunk_document(sections, source_document=str(path), source_url=matched_url, client=client)

        slug = path.stem
        out_path = chunks_dir / f"{slug}__{source_type}.json"
        out_path.write_text(
            "[\n" + ",\n".join(c.model_dump_json() for c in chunks) + "\n]",
            encoding="utf-8",
        )

        logger.info("%s (%s, %s): %d chunks -> %s", course_name, tier, source_type, len(chunks), out_path)
        return ChunkResult(
            course_name=course_name, source_type=source_type, outcome="chunked", chunk_count=len(chunks)
        )
    except Exception as exc:
        logger.info("Course %r chunking failed: %s", course_name, exc)
        return ChunkResult(course_name=course_name, source_type=source_type, outcome="failed", error=str(exc))


def chunk_all_documents(
    db_path: Path = Path("data/manifest.db"),
    client: anthropic.Anthropic | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunks_dir: Path = CHUNKS_DIR,
) -> ChunkBatchReport:
    """Chunk every document referenced in the manifest, concurrently.

    Each document's read+chunk+write is independent of every other document,
    but chunk_document()'s _token_count() now makes one count_tokens() network
    call per paragraph-append decision (real tokenizer fix, see chunker.py) --
    confirmed live to take ~9.3 hours for 51 documents run sequentially. A
    thread pool parallelizes across documents (I/O-bound network calls, shared
    anthropic.Anthropic client -- its underlying httpx.Client is thread-safe
    for concurrent requests). Each document's failure is isolated the same
    way retrieve/batch.py and extract/batch_extract.py isolate per-item
    failures -- one document's exception doesn't abort the batch.
    """
    client = client or anthropic.Anthropic()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT course_name, tier, source_type, matched_url, local_path FROM manifest"
        ).fetchall()
    finally:
        conn.close()

    chunks_dir.mkdir(parents=True, exist_ok=True)
    results: list[ChunkResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _chunk_one_document, course_name, tier, source_type, matched_url, local_path, client, chunks_dir
            )
            for course_name, tier, source_type, matched_url, local_path in rows
        ]
        for future in as_completed(futures):
            results.append(future.result())

    return ChunkBatchReport(results=results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    report = chunk_all_documents()
    chunked = [r for r in report.results if r.outcome == "chunked"]
    failed = [r for r in report.results if r.outcome == "failed"]

    print(f"\nChunked {len(chunked)}/{len(report.results)} documents.")
    print(f"Total chunks: {sum(r.chunk_count for r in chunked)}")
    if failed:
        print(f"Failed: {len(failed)}")
        for r in failed:
            print(f"  FAILED: {r.course_name}: {r.error}")
