from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.extract.chunk_inputs import read_chunk_inputs
from src.retrieve.models import Segment


class ExtractionInput(BaseModel):
    course_id: str
    chunk_filenames: list[str]
    documents_by_segment: dict[Segment, list[str]]

    @property
    def segments(self) -> list[Segment]:
        return list(self.documents_by_segment)


def read_extraction_inputs(db_path: Optional[Path] = None) -> list[ExtractionInput]:
    """One input per course, carrying its chunk files and a segment index.

    documents_by_segment is what makes segment-scoped extraction possible: a
    segment's fields can be filled from the documents actually resolved for that
    segment, rather than from every document retrieved for the course.
    """
    by_course: dict[str, ExtractionInput] = {}
    for chunk_input in read_chunk_inputs(db_path=db_path):
        found = by_course.get(chunk_input.course_id)
        if found is None:
            found = ExtractionInput(
                course_id=chunk_input.course_id, chunk_filenames=[], documents_by_segment={}
            )
            by_course[chunk_input.course_id] = found

        if chunk_input.chunk_filename not in found.chunk_filenames:
            found.chunk_filenames.append(chunk_input.chunk_filename)

        for segment in chunk_input.segments:
            documents = found.documents_by_segment.setdefault(segment, [])
            if chunk_input.document_id not in documents:
                documents.append(chunk_input.document_id)

    return [by_course[course_id] for course_id in sorted(by_course)]
