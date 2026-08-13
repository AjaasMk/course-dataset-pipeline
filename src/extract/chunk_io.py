import json
import sqlite3
from pathlib import Path

from src.extract.models import Chunk
from src.retrieve.models import Segment


def load_chunks(chunk_path: Path) -> list[Chunk]:
    data = json.loads(chunk_path.read_text(encoding="utf-8"))
    return [Chunk.model_validate(item) for item in data]


CANONICAL_TIERS = ("A", "B", "C")


def tiers_by_document(db_path: str = "data/manifest.db") -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("select document_id, source_tier from documents"))
    finally:
        conn.close()


def course_document_ids(course_id: str, db_path: str = "data/manifest.db") -> set[str]:
    """Every document resolved for a course, across all its segments.

    Pooled rather than looked up per segment. Stage 1 records which SEGMENT an
    intent was issued for, and the chunker independently labels each chunk with
    the segment its content is about; the two disagree often. Intersecting them
    -- loading only a segment's own documents and then filtering those chunks by
    segment_id -- silently drops evidence that exists. Measured on
    mechanical_engineering: five segments had zero candidate chunks that way
    while 45 labelled chunks sat in documents Stage 1 had filed elsewhere.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select distinct r.document_id from retrieval_intents i "
            "join intent_resolutions r on i.intent_id = r.intent_id "
            "join documents d on d.document_id = r.document_id "
            "where i.course_id = ? and d.local_path is not null",
            (course_id,),
        ).fetchall()
    finally:
        conn.close()
    return {document_id for (document_id,) in rows}


def canonical_only(chunks: list[Chunk]) -> tuple[list[Chunk], int]:
    """Drop chunks whose document cannot serve as canonical evidence.

    Hard Constraint 3: Tier D/E/F are discovery and corroboration only, never
    canonical without Tier A/B/C backing. Pooling documents makes this gate
    load-bearing rather than theoretical -- measured on mechanical_engineering,
    pooling surfaced 45 additional chunks and every one of them was Tier D, so
    without this the fix would have quietly promoted commercial-portal content
    into cited facts.

    Returns the survivors and how many were dropped, because a segment left
    empty by this gate is a sourcing gap worth reporting, not a silent zero.
    """
    kept = [c for c in chunks if c.source_tier in CANONICAL_TIERS]
    return kept, len(chunks) - len(kept)


def chunks_for_segment(chunks: list[Chunk], segment: Segment) -> list[Chunk]:
    """Filter a document's chunks down to one segment, by chunk_id order.

    This is the retrieval step ahead of per-segment extraction: every chunk
    already carries segment_id (see src/extract/chunker.py), so the LLM only
    needs the chunks tagged for the segment being extracted -- no embedding or
    similarity search, since per-course per-segment chunk counts are small
    enough to pass whole (decided 2026-08-09).
    """
    matching = [c for c in chunks if c.segment_id == segment]
    return sorted(matching, key=lambda c: c.chunk_id)
