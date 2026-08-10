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
        # Document-scoped, not course-scoped: chunking is a property of the
        # document's content alone. A course-scoped filename would mean the
        # same real document gets chunked from scratch once per course that
        # resolves to it -- confirmed live 2026-08-10 this produced 7,886
        # chunk inputs for ~163 real unique documents (a ~48x redundancy in
        # real, paid API calls) before this was fixed. The row-per-course
        # structure below is still correct and unchanged -- extraction needs
        # it to know which document answers which of a course's segments --
        # only the FILE (and the chunking work that produces it) is
        # deduplicated, in run_chunking.py::chunk_all_documents().
        return f"{self.document_id}.json"


def read_chunk_inputs(db_path: Optional[Path] = None) -> list[ChunkInput]:
    """One input per (course, resolved document).

    A document may serve several courses -- one NIRF ranking table covers every
    engineering course -- so it appears once per course. Deduplicating the
    underlying fetch is the store's job via the unique document_url; this level
    needs a row per course so extraction can find a course's own evidence.
    Deduplicating the actual chunking WORK (the expensive part -- see
    chunk_filename above) is chunk_all_documents()'s job, not this function's.
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
