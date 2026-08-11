import json
import re
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from src.extract.chunk_io import chunks_for_segment
from src.extract.chunk_retrieval import retrieve
from src.extract.llm_chunker import json_object
from src.extract.models import Chunk
from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
    Course,
    Curriculum,
    EligibilityRule,
    Specialisation,
)
from src.facts.engine import field_ref
from src.facts.models import SourceRef
from src.retrieve.base import document_id_for
from src.retrieve.models import Segment

# Haiku, not Sonnet. Retrieval changed what this call is: it used to be "find
# nine facts somewhere in a 100-page curriculum" (563 chunks, 454k chars on the
# worst real call) and is now "read five pre-selected chunks and quote them".
# The second is a much smaller job, and Haiku is half the price -- $1/$5 per
# million against $2/$10. Extraction quality against the retrieved set is the
# thing to watch, not cost; the live A/B is what settles whether this holds.
MODEL = "claude-haiku-4-5-20251001"
# Off leaves the old whole-segment path intact, which is what makes an A/B
# comparison on real data possible rather than a claim.
RETRIEVAL_ENABLED = True
# 16k is the ceiling before the SDK requires streaming. Raised from 12k after a
# real architecture curriculum (many subjects, each cited) was cut off mid-object.
MAX_TOKENS = 16_000

# Schema-in-prompt, not output_config/messages.parse(). The retired flat
# 22-field course schema hit a real, live API error from strict structured
# output ("the compiled grammar is too large"); these per-segment models are
# small enough that it would likely work now, but one extraction mechanism
# across the stage beats two for no functional gain.
SYSTEM_PROMPT = """You extract structured {topic} information about an Indian academic \
course from retrieved source documents, into the following JSON schema:

{schema}

Each source document below is labeled with its DOCUMENT_ID. For every field you populate:
- Ground it in one of the documents below -- quote the exact supporting text.
- Record which DOCUMENT_ID that quote came from.
- If no document covers a field, leave it null. Never fill a field from general or typical \
knowledge -- an ungroundable field must be null, not a plausible-sounding guess.
- List fields should be empty lists, not null, when nothing is found.

Respond with a single JSON object with this shape: the schema's fields, plus a "citations" \
array of {{"field": "<field name>", "document_id": "<DOCUMENT_ID>", "quoted_evidence": "<exact \
quoted text>"}} entries, one per populated field. No prose, no markdown code fences -- output \
only the JSON object."""

# Restating the task AFTER the documents, not only in the system prompt.
# Measured live on real AICTE Course Identity chunks: with the instruction only
# up front, the model echoed source text and repeated the instruction back with
# no JSON anywhere in the reply (0 braces, 1,641 output tokens). The same call
# with this trailer returned a parsed object with 3 populated fields and 3
# citations in 764 tokens. Assistant prefill would be the stronger fix but this
# model rejects it, so recency is the only lever available.
INSTRUCTION_TRAILER = """

End of source documents.

Now output the single JSON object described in your instructions. Start your \
reply with the character { and end it with }. Output nothing else -- no \
preamble, no explanation, no restatement of these instructions. If the \
documents above support no field at all, output the object with every field \
null or empty and an empty citations array."""

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


class _EligibilityExtraction(BaseModel):
    minimum_qualification: Optional[str] = None
    accepted_streams: list[str] = Field(default_factory=list)
    compulsory_subjects: list[str] = Field(default_factory=list)
    recommended_subjects: list[str] = Field(default_factory=list)
    minimum_percentage: Optional[str] = None
    age_requirement: Optional[str] = None
    medical_requirement: Optional[str] = None
    portfolio_required: Optional[bool] = None
    interview_required: Optional[bool] = None
    lateral_entry_available: Optional[bool] = None
    international_equivalence: Optional[str] = None
    citations: list[_Citation] = Field(default_factory=list)


class _CourseExtraction(BaseModel):
    standard_course_name: Optional[str] = None
    common_course_name: Optional[str] = None
    abbreviation: Optional[str] = None
    qualification_level: Optional[str] = None
    qualification_type: Optional[str] = None
    academic_or_vocational: Optional[str] = None
    regulating_body: Optional[str] = None
    course_aliases: list[str] = Field(default_factory=list)
    minimum_duration: Optional[str] = None
    maximum_duration: Optional[str] = None
    semester_count: Optional[int] = None
    credit_count: Optional[int] = None
    study_mode: Optional[str] = None
    full_time_available: Optional[bool] = None
    part_time_available: Optional[bool] = None
    online_available: Optional[bool] = None
    distance_available: Optional[bool] = None
    exit_options: list[str] = Field(default_factory=list)
    citations: list[_Citation] = Field(default_factory=list)


class _SpecialisationEntry(BaseModel):
    specialisation_name: str
    available_at_level: Optional[str] = None
    parent_course: Optional[str] = None
    typical_subjects: list[str] = Field(default_factory=list)
    career_focus: Optional[str] = None
    specialisation_type: Optional[str] = None
    citations: list[_Citation] = Field(default_factory=list)


class _SpecialisationExtraction(BaseModel):
    specialisations: list[_SpecialisationEntry] = Field(default_factory=list)


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


def _drop_uncited(values: dict, citations: list[_Citation], field_ids: dict[str, str]) -> dict:
    """Null any field the model populated but did not cite.

    Hard Constraint 4 says an ungroundable field must be null, not a
    plausible-sounding guess -- and a field the model could not quote evidence
    for is exactly that. Dropping it keeps the rest of the record: measured
    live, two courses lost a whole Course extraction (8 cited fields between
    them) because one field arrived uncited and record_*() rejected the lot.
    """
    cited = {c.field for c in citations}
    cleaned = dict(values)
    for name in field_ids:
        if name in cited or name not in cleaned:
            continue
        value = cleaned[name]
        if value in (None, "", [], {}):
            continue
        cleaned[name] = [] if isinstance(value, list) else None
    return cleaned


def _chunks_for_segments(chunks: list[Chunk], segments: list[Segment]) -> list[Chunk]:
    matched: list[Chunk] = []
    seen_ids: set[int] = set()
    for segment in segments:
        for chunk in chunks_for_segment(chunks, segment):
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                matched.append(chunk)
    return sorted(matched, key=lambda c: c.chunk_id)


def _run_extraction(
    segments: list[Segment],
    chunks: list[Chunk],
    topic: str,
    extraction_model_cls,
    context_label: str,
    client: Optional[anthropic.Anthropic],
):
    """Shared core for every segment-scoped, cited extraction function in
    this module. Returns None if there is nothing to extract from (no
    point spending an API call on zero evidence); otherwise returns the
    validated extraction_model_cls instance.
    """
    segment_chunks = _chunks_for_segments(chunks, segments)
    if not segment_chunks:
        return None

    # Retrieval, not the whole segment. Measured before this existed: a single
    # Curriculum call sent 563 chunks and 454,462 characters to cite 9 of them,
    # and Curriculum alone was 97.8% of the extraction bill. Ranking first costs
    # nothing per call -- both models run locally -- and cuts the payload by
    # roughly 99%.
    if RETRIEVAL_ENABLED:
        result = retrieve(segment_chunks, segments[0].value)
        if result.chunks:
            segment_chunks = result.chunks

    client = client or anthropic.Anthropic()
    document_text = _document_labeled_text(segment_chunks)
    schema_json = json.dumps(extraction_model_cls.model_json_schema())

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT.format(topic=topic, schema=schema_json),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        # No assistant prefill: it would stop the prose at the source, but this
        # model rejects it outright ("This model does not support assistant
        # message prefill", HTTP 400, measured). Recovery in json_object() is
        # therefore the only line of defence, not a backstop.
        messages=[{"role": "user", "content": document_text + INSTRUCTION_TRAILER}],
    )
    if response.stop_reason == "max_tokens":
        raise ExtractionTruncatedError(
            f"{topic} extraction for {context_label!r} was cut off at "
            f"max_tokens={MAX_TOKENS} before the JSON object finished."
        )

    # Filtering on type rather than taking content[0]: a reasoning model emits a
    # `thinking` block first, and DeepSeek's Anthropic-compatible endpoint does
    # so on every call. That reasoning also SPENDS output tokens, so a budget
    # sized for the JSON alone can be consumed before any text is produced --
    # confirmed live, a max_tokens=16 call returned stop_reason "end_turn" with
    # a thinking block and no text block at all. Raise something that names the
    # cause instead of a bare StopIteration from next().
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise ExtractionTruncatedError(
            f"{topic} extraction for {context_label!r} returned no text block "
            f"(stop_reason={response.stop_reason!r}, output_tokens="
            f"{response.usage.output_tokens}). A reasoning model can spend the "
            f"whole max_tokens={MAX_TOKENS} budget before emitting any answer."
        )
    # json_object(), not just fence-stripping: measured live, the model
    # wrapped valid JSON in prose ("and evaluated with the p... }") and on one
    # call returned prose alone. Losing a whole extraction to a preamble is a
    # cosmetic failure, and the same recovery already proved necessary in the
    # chunker.
    return extraction_model_cls.model_validate_json(json_object(text))


def extract_curriculum(
    chunks: list[Chunk],
    course,
    curriculum_year: str,
    client: Optional[anthropic.Anthropic] = None,
) -> tuple[Curriculum, list[SourceRef]]:
    parsed = _run_extraction(
        [Segment.CURRICULUM], chunks, "curriculum", _CurriculumExtraction, course.course_id, client,
    )
    if parsed is None:
        return Curriculum(course_id=course.course_id, curriculum_year=curriculum_year), []

    curriculum = Curriculum(
        course_id=course.course_id,
        curriculum_year=curriculum_year,
        **_drop_uncited(parsed.model_dump(exclude={"citations"}), parsed.citations,
                        CURRICULUM_FIELD_IDS),
    )
    refs = _refs_from_citations(parsed.citations, CURRICULUM_FIELD_IDS)
    return curriculum, refs


def extract_eligibility(
    chunks: list[Chunk],
    course,
    eligibility_year: str,
    client: Optional[anthropic.Anthropic] = None,
) -> tuple[EligibilityRule, list[SourceRef]]:
    parsed = _run_extraction(
        [Segment.ELIGIBILITY], chunks, "eligibility", _EligibilityExtraction, course.course_id, client,
    )
    if parsed is None:
        return EligibilityRule(course_id=course.course_id, eligibility_year=eligibility_year), []

    rule = EligibilityRule(
        course_id=course.course_id,
        eligibility_year=eligibility_year,
        **_drop_uncited(parsed.model_dump(exclude={"citations"}), parsed.citations,
                        ELIGIBILITY_FIELD_IDS),
    )
    refs = _refs_from_citations(parsed.citations, ELIGIBILITY_FIELD_IDS)
    return rule, refs


def extract_course(
    chunks: list[Chunk],
    course,
    client: Optional[anthropic.Anthropic] = None,
) -> tuple[Optional[Course], list[SourceRef]]:
    # Spans two segments -- Course Identity (F001-F008) and Duration & Mode
    # (F009-F018) share one Facts model (Course), so both need to be in
    # scope for one extraction call rather than two separate ones that
    # would each only see half the relevant evidence.
    parsed = _run_extraction(
        [Segment.COURSE_IDENTITY, Segment.DURATION_MODE], chunks, "course identity and duration/mode",
        _CourseExtraction, course.course_id, client,
    )
    # standard_course_name (F001) is the record's identity and Course requires
    # it. When the documents never state what the programme is called -- common
    # in a syllabus PDF, which assumes you know -- there is no Course fact to
    # record. Returning nothing routes the block to generation instead of
    # crashing on a null, and never borrows our own catalogue name as if a
    # source had said it.
    if parsed is None or not parsed.standard_course_name:
        return None, []

    result = Course(
        course_id=course.course_id,
        **_drop_uncited(parsed.model_dump(exclude={"citations"}), parsed.citations,
                        COURSE_FIELD_IDS),
    )
    refs = _refs_from_citations(parsed.citations, COURSE_FIELD_IDS)
    return result, refs


def extract_specialisation(
    chunks: list[Chunk],
    course,
    client: Optional[anthropic.Anthropic] = None,
) -> list[tuple[Specialisation, list[SourceRef]]]:
    # One-to-many, unlike the other three: an MBA has several
    # specialisations (HR, Finance, Marketing), each its own fact -- the
    # extraction schema is a list of entries, each carrying its own
    # citations, rather than one flat record.
    parsed = _run_extraction(
        [Segment.SPECIALISATION], chunks, "specialisation", _SpecialisationExtraction,
        course.course_id, client,
    )
    if parsed is None:
        return []

    results = []
    for entry in parsed.specialisations:
        spec = Specialisation(
            course_id=course.course_id,
            **_drop_uncited(entry.model_dump(exclude={"citations"}), entry.citations,
                            SPECIALISATION_FIELD_IDS),
        )
        refs = _refs_from_citations(entry.citations, SPECIALISATION_FIELD_IDS)
        results.append((spec, refs))
    return results
