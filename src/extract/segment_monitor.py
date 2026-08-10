from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.extract.chunk_inputs import ChunkInput, read_chunk_inputs
from src.extract.models import Chunk
from src.retrieve.models import Segment

# A document's own retrieval-level segment(s) come from WHY it was fetched
# (the intent that resolved it); chunk-level segment_id comes from WHAT its
# content actually says, classified independently per section. A small
# stray share between the two is a legitimate incidental find -- one UGC
# regulations PDF fetched for Eligibility may contain a Duration clause.
# ~40% is the point at which that stops looking incidental and starts
# looking like either a wrong document-level tag or a systemic
# heading-matcher gap for that source type. This is a monitoring policy
# choice taken directly from the task's own example, not a fuzzy-match
# score calibrated against real data the way SEGMENT_MATCH_THRESHOLD is.
MISMATCH_WARN_RATIO = 0.40


class SegmentDistribution(BaseModel):
    document_id: str
    total_chunks: int
    by_segment: dict[str, int]
    document_segments: list[Segment]
    stray_ratio: Optional[float]
    flagged: bool


def check_document_segment_distribution(
    document_id: str,
    chunks: list[Chunk],
    document_segments: list[Segment],
) -> SegmentDistribution:
    """Chunk-level segment_id is authoritative for extraction routing; this
    is a diagnostic cross-check against the document's own retrieval-level
    tag(s), not a gate -- it never changes what gets extracted, only whether
    a human should look at this document/source type."""
    by_segment: dict[str, int] = {}
    for chunk in chunks:
        key = chunk.segment_id if isinstance(chunk.segment_id, str) else chunk.segment_id.value
        by_segment[key] = by_segment.get(key, 0) + 1

    if not chunks or not document_segments:
        return SegmentDistribution(
            document_id=document_id, total_chunks=len(chunks), by_segment=by_segment,
            document_segments=document_segments, stray_ratio=None, flagged=False,
        )

    matching_values = {s.value for s in document_segments}
    matching = sum(n for seg, n in by_segment.items() if seg in matching_values)
    stray_ratio = 1 - (matching / len(chunks))

    return SegmentDistribution(
        document_id=document_id, total_chunks=len(chunks), by_segment=by_segment,
        document_segments=document_segments, stray_ratio=stray_ratio,
        flagged=stray_ratio >= MISMATCH_WARN_RATIO,
    )


def check_course_segment_distribution(
    course_id: str, chunks_dir: Path = Path("data/chunks"), db_path: Optional[Path] = None
) -> list[SegmentDistribution]:
    """Live wrapper: reads real chunk files and real retrieval-level document
    tags for a course and cross-checks each document. Requires chunks to have
    already been produced with segment_id populated (post Task 3)."""
    from src.extract.chunk_io import load_chunks

    results: list[SegmentDistribution] = []
    inputs: list[ChunkInput] = [
        i for i in read_chunk_inputs(db_path=db_path) if i.course_id == course_id
    ]
    for chunk_input in inputs:
        chunk_path = chunks_dir / chunk_input.chunk_filename
        if not chunk_path.exists():
            continue
        chunks = load_chunks(chunk_path)
        results.append(
            check_document_segment_distribution(
                chunk_input.document_id, chunks, document_segments=chunk_input.segments
            )
        )
    return results
