import logging
import sqlite3
from pathlib import Path

from src.extract.chunker import chunk_document, detect_pdf_sections
from src.extract.readers import read_html, read_pdf

logger = logging.getLogger(__name__)

CHUNKS_DIR = Path("data/chunks")


def chunk_all_documents(db_path: Path = Path("data/manifest.db")) -> dict[str, int]:
    """Chunk every document referenced in the manifest. Returns {course_name: chunk_count}."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT course_name, tier, source_type, matched_url, local_path FROM manifest"
        ).fetchall()
    finally:
        conn.close()

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}

    for course_name, tier, source_type, matched_url, local_path in rows:
        path = Path(local_path)
        if path.suffix == ".pdf":
            pages = read_pdf(path)
            sections = detect_pdf_sections(pages)
        else:
            sections = read_html(path)

        chunks = chunk_document(sections, source_document=str(path), source_url=matched_url)

        slug = path.stem
        out_path = CHUNKS_DIR / f"{slug}__{source_type}.json"
        out_path.write_text(
            "[\n" + ",\n".join(c.model_dump_json() for c in chunks) + "\n]",
            encoding="utf-8",
        )

        logger.info("%s (%s, %s): %d chunks -> %s", course_name, tier, source_type, len(chunks), out_path)
        results[f"{course_name} ({source_type})"] = len(chunks)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    results = chunk_all_documents()
    print(f"\nChunked {len(results)} documents (from {len(set(k.split(' (')[0] for k in results))} distinct courses).")
    print(f"Total chunks: {sum(results.values())}")
