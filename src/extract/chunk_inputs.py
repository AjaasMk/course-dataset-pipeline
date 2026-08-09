from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.retrieve import store
from src.retrieve.models import Segment, SourceTier


class ChunkInput(BaseModel):
    course_id: str
    document_id: str
    source_id: str
    source_tier: SourceTier
    local_path: str
    document_url: str
    segments: list[Segment]

    @property
    def chunk_filename(self) -> str:
        return f"{self.course_id}__{self.document_id}.json"


def read_chunk_inputs(db_path: Optional[Path] = None) -> list[ChunkInput]:
    """One input per (course, resolved document).

    A document may serve several courses -- one NIRF ranking table covers every
    engineering course -- so it appears once per course. Deduplicating the
    underlying fetch is the store's job via the unique document_url; this level
    needs a row per course so extraction can find a course's own evidence.
    """
    inputs: list[ChunkInput] = []
    for course_id in store.courses_with_documents(db_path=db_path):
        for document in store.documents_for_course(course_id, db_path=db_path):
            if not document.local_path:
                continue
            inputs.append(
                ChunkInput(
                    course_id=course_id,
                    document_id=document.document_id,
                    source_id=document.source_id,
                    source_tier=document.source_tier,
                    local_path=document.local_path,
                    document_url=document.document_url,
                    segments=document.segments,
                )
            )
    return inputs
