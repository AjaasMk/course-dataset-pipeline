import json
from pathlib import Path

from src.extract.models import Chunk
from src.retrieve.models import Segment


def load_chunks(chunk_path: Path) -> list[Chunk]:
    data = json.loads(chunk_path.read_text(encoding="utf-8"))
    return [Chunk.model_validate(item) for item in data]


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
