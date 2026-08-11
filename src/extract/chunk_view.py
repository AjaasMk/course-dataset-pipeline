import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.retrieve import store

CHUNKS_DIR = Path("data/chunks_llm")


class ViewSource(BaseModel):
    source_id: str
    source_name: str
    source_tier: str


class ViewChunk(BaseModel):
    chunk_id: str
    text: str
    heading_path: list[str] = Field(default_factory=list)


class ChunkGroup(BaseModel):
    """One (course, source, segment, subsegment) group.

    The delivery shape, not the storage shape. Chunks are stored once per
    DOCUMENT (data/chunks_llm/<document_id>.json) because a single NIRF ranking
    table serves 166 courses -- writing this shape to disk would copy it 166
    times. The course dimension is joined on here instead, from the retrieval
    store's course->document links.
    """

    course: str
    source: ViewSource
    segment: str
    subsegment: str
    document_id: str
    chunks: list[ViewChunk] = Field(default_factory=list)


def _load(document_id: str, chunks_dir: Path) -> list[dict]:
    path = chunks_dir / f"{document_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def course_chunk_groups(
    course_id: str,
    chunks_dir: Path = CHUNKS_DIR,
    db_path: Optional[Path] = None,
    segment: Optional[str] = None,
) -> list[ChunkGroup]:
    """Project stored chunks into course -> source -> segment -> subsegment.

    Only the documents actually resolved for this course are read, so a chunk
    reaches a course because retrieval bound that document to it, never because
    the text merely mentions the course.
    """
    groups: dict[tuple, ChunkGroup] = {}

    for document in store.documents_for_course(course_id, db_path=db_path):
        source = ViewSource(
            source_id=document.source_id,
            source_name=document.source_id,
            source_tier=document.source_tier.value,
        )
        for raw in _load(document.document_id, chunks_dir):
            seg = str(raw.get("segment_id") or "unclassified")
            if segment is not None and seg != segment:
                continue
            sub = raw.get("subsegment") or seg
            key = (document.source_id, seg, sub, document.document_id)
            group = groups.get(key)
            if group is None:
                group = ChunkGroup(
                    course=course_id,
                    source=source,
                    segment=seg,
                    subsegment=sub,
                    document_id=document.document_id,
                )
                groups[key] = group
            group.chunks.append(
                ViewChunk(
                    chunk_id=f"CH-{len(group.chunks) + 1:03d}",
                    text=raw.get("text", ""),
                    # The hierarchy path, not the document's internal headings:
                    # those stay on the stored chunk as evidence of where the
                    # text came from, while this names where it sits in the
                    # course taxonomy.
                    heading_path=[course_id, seg, sub],
                )
            )
    return list(groups.values())


def course_tree(
    course_id: str, chunks_dir: Path = CHUNKS_DIR, db_path: Optional[Path] = None
) -> dict:
    """The same data as a nested course -> source -> segment -> subsegment map,
    for reading rather than iterating."""
    tree: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for group in course_chunk_groups(course_id, chunks_dir=chunks_dir, db_path=db_path):
        tree[group.source.source_id][group.segment][group.subsegment] += len(group.chunks)
    return {s: {seg: dict(subs) for seg, subs in v.items()} for s, v in tree.items()}
