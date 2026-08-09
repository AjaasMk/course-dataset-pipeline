import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel

from src.extract.chunk_inputs import ChunkInput, read_chunk_inputs
from src.extract.chunker import chunk_document, detect_pdf_sections
from src.extract.readers import read_html, read_pdf

logger = logging.getLogger(__name__)

CHUNKS_DIR = Path("data/chunks")
DEFAULT_MAX_WORKERS = 8


class ChunkResult(BaseModel):
    course_name: str
    source_type: str
    document_id: str = ""
    outcome: Literal["chunked", "failed"]
    chunk_count: int = 0
    error: Optional[str] = None


class ChunkBatchReport(BaseModel):
    results: list[ChunkResult]


def _chunk_one_document(
    chunk_input: ChunkInput,
    client: anthropic.Anthropic,
    chunks_dir: Path,
) -> ChunkResult:
    path = Path(chunk_input.local_path)
    try:
        if path.suffix == ".pdf":
            pages = read_pdf(path)
            sections = detect_pdf_sections(pages)
        else:
            sections = read_html(path)

        chunks = chunk_document(
            sections,
            source_document=str(path),
            source_url=chunk_input.document_url,
            client=client,
        )

        out_path = chunks_dir / chunk_input.chunk_filename
        out_path.write_text(
            "[\n" + ",\n".join(c.model_dump_json() for c in chunks) + "\n]",
            encoding="utf-8",
        )

        logger.info(
            "%s (%s, tier %s): %d chunks -> %s",
            chunk_input.course_id,
            chunk_input.source_id,
            chunk_input.source_tier.value,
            len(chunks),
            out_path,
        )
        return ChunkResult(
            course_name=chunk_input.course_id,
            source_type=chunk_input.source_id,
            document_id=chunk_input.document_id,
            outcome="chunked",
            chunk_count=len(chunks),
        )
    except Exception as exc:
        logger.info("%s / %s chunking failed: %s", chunk_input.course_id, chunk_input.document_id, exc)
        return ChunkResult(
            course_name=chunk_input.course_id,
            source_type=chunk_input.source_id,
            document_id=chunk_input.document_id,
            outcome="failed",
            error=str(exc),
        )


def chunk_all_documents(
    db_path: Optional[Path] = None,
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
    inputs = read_chunk_inputs(db_path=db_path)

    chunks_dir.mkdir(parents=True, exist_ok=True)
    results: list[ChunkResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_chunk_one_document, chunk_input, client, chunks_dir)
            for chunk_input in inputs
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
