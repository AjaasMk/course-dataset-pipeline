import json
import re
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from src.extract.extractor import chunks_for_segment
from src.extract.models import Chunk
from src.facts.course_facts import CURRICULUM_FIELD_IDS, Curriculum
from src.facts.engine import field_ref
from src.facts.models import SourceRef
from src.retrieve.base import document_id_for
from src.retrieve.models import Segment

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096

# Schema-in-prompt, not output_config/messages.parse(): the legacy CourseDetail
# extractor (src/extract/extractor.py) hit a real, live API error ("the
# compiled grammar is too large") from a much bigger schema. This model is
# small enough that strict structured output would likely work, but the
# pattern is kept consistent with the rest of this stage rather than mixing
# two different extraction mechanisms for no functional reason.
SYSTEM_PROMPT = """You extract structured curriculum information about an Indian academic \
course from retrieved source documents, into the following JSON schema:

{schema}

Each source document below is labeled with its DOCUMENT_ID. For every field you populate:
- Ground it in one of the documents below -- quote the exact supporting text.
- Record which DOCUMENT_ID that quote came from.
- If no document covers a field, leave it null. Never fill a field from general or typical \
knowledge -- an ungroundable field must be null, not a plausible-sounding guess.
- List fields (foundation_subjects, core_subjects, electives) should be empty lists, not null, \
when nothing is found.

Respond with a single JSON object with this shape: the schema's fields, plus a "citations" \
array of {{"field": "<field name>", "document_id": "<DOCUMENT_ID>", "quoted_evidence": "<exact \
quoted text>"}} entries, one per populated field. No prose, no markdown code fences -- output \
only the JSON object."""

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ExtractionTruncatedError(Exception):
    """Raised when the model's response was cut off by max_tokens before
    finishing the JSON object, rather than failing with a confusing JSON
    parse error."""


class _Citation(BaseModel):
    field: str
    document_id: str
    quoted_evidence: str


class _CurriculumExtraction(BaseModel):
    foundation_subjects: list[str] = Field(default_factory=list)
    core_subjects: list[str] = Field(default_factory=list)
    electives: list[str] = Field(default_factory=list)
    practical_components: Optional[str] = None
    laboratory_components: Optional[str] = None
    internship: Optional[str] = None
    fieldwork: Optional[str] = None
    project: Optional[str] = None
    dissertation: Optional[str] = None
    citations: list[_Citation] = Field(default_factory=list)


def _strip_markdown_fence(text: str) -> str:
    return _JSON_FENCE_RE.sub("", text).strip()


def _document_labeled_text(chunks: list[Chunk]) -> str:
    # One segment's chunks can legitimately come from more than one document
    # (the intent-first design's whole premise: "one segment may need many
    # sources") -- grouping by source_url and labeling each block with its
    # real document_id (the same id() function the retrieve store already
    # uses, src/retrieve/base.py::document_id_for) is what lets the model's
    # citation output point back to a specific document, not just "somewhere
    # in the input."
    by_document: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_document.setdefault(chunk.source_url, []).append(chunk)

    blocks = []
    for source_url, doc_chunks in by_document.items():
        ordered = sorted(doc_chunks, key=lambda c: c.chunk_id)
        text = "\n\n".join(c.text for c in ordered)
        blocks.append(f"--- DOCUMENT_ID: {document_id_for(source_url)} ---\n{text}")
    return "\n\n".join(blocks)


def _refs_from_citations(citations: list[_Citation], field_ids: dict[str, str]) -> list[SourceRef]:
    refs = []
    for citation in citations:
        field_id = field_ids.get(citation.field)
        if field_id is None:
            continue
        refs.append(field_ref(field_id, citation.document_id, citation.quoted_evidence))
    return refs


def extract_curriculum(
    chunks: list[Chunk],
    course,
    curriculum_year: str,
    client: Optional[anthropic.Anthropic] = None,
) -> tuple[Curriculum, list[SourceRef]]:
    segment_chunks = chunks_for_segment(chunks, Segment.CURRICULUM)
    if not segment_chunks:
        return Curriculum(course_id=course.course_id, curriculum_year=curriculum_year), []

    client = client or anthropic.Anthropic()
    document_text = _document_labeled_text(segment_chunks)
    schema_json = json.dumps(_CurriculumExtraction.model_json_schema())

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT.format(schema=schema_json),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": document_text}],
    )
    if response.stop_reason == "max_tokens":
        raise ExtractionTruncatedError(
            f"Curriculum extraction for {course.course_id!r} was cut off at "
            f"max_tokens={MAX_TOKENS} before the JSON object finished."
        )

    text = next(block.text for block in response.content if block.type == "text")
    parsed = _CurriculumExtraction.model_validate_json(_strip_markdown_fence(text))

    curriculum = Curriculum(
        course_id=course.course_id,
        curriculum_year=curriculum_year,
        **parsed.model_dump(exclude={"citations"}),
    )
    refs = _refs_from_citations(parsed.citations, CURRICULUM_FIELD_IDS)
    return curriculum, refs
