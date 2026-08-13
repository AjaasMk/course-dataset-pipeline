import json
import re
from enum import Enum
from typing import Optional, Union, get_args, get_origin

import anthropic
from pydantic import BaseModel, Field, create_model

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
from src.facts.segment_facts import SEGMENT_FACTS
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
- Subject and elective names carry NO course code. A regulator's model curriculum numbers its subjects (PCC ME 201, HSMC 101) but every university renumbers, so the code is not a property of the course. Write "Heat Transfer & Thermal Machines", never "PCC ME 201 Heat Transfer & Thermal Machines".

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

# Keys the pipeline sets itself. They are never extracted, carry no citation
# and must not appear in an entry model or the gate would demand evidence
# for a value we chose.
_BOOKKEEPING = {
    "record_id",
    "course_id",
    "recorded_at",
    "superseded_at",
    # Versioning keys, chosen by the caller and passed to the record
    # explicitly. Leaving them in an entry model would both ask the model to
    # invent a year and collide with the argument the caller already passes.
    "curriculum_year",
    "eligibility_year",
}

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ExtractionTruncatedError(Exception):
    """Raised when the model's response was cut off by max_tokens before
    finishing the JSON object, rather than failing with a confusing JSON
    parse error."""


class _Citation(BaseModel):
    field: str
    document_id: str
    quoted_evidence: str




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
    schema_json = compact_schema(extraction_model_cls)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        # No cache_control. Measured: every system block here is under 1,000
        # tokens and Haiku's minimum cacheable prompt is 2,048, so the marker
        # was a no-op -- it read as an optimisation while doing nothing. With
        # retrieval the document is small and varies per course, so there is
        # genuinely nothing worth caching on this call.
        system=[{"type": "text", "text": SYSTEM_PROMPT.format(topic=topic, schema=schema_json)}],
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


def compact_schema(model) -> str:
    """The field list in the smallest form that still says what to produce.

    model_json_schema() spends most of its tokens on $defs, "title" keys and
    anyOf wrappers that restate what the type already says. Measured on the
    Course model: 707 tokens verbose against 142 compact, for the same
    information. Across the pilot's 56 calls that is ~29k input tokens, 10% of
    the total, bought for nothing.

    Enum members are listed rather than named, because the allowed values are
    the point -- relationship_strength has to come back as one of the five
    route badges the page renders, and a bare type name would not say so.
    """
    return json.dumps({
        name: _describe_annotation(info.annotation)
        for name, info in model.model_fields.items()
        if name != "citations"
    })


def _describe_annotation(annotation) -> object:
    origin = get_origin(annotation)
    if origin is Union:
        inner = [a for a in get_args(annotation) if a is not type(None)]
        described = _describe_annotation(inner[0]) if inner else "string"
        return described if isinstance(described, (list, dict)) else f"{described} or null"
    if origin in (list, set, tuple):
        args = get_args(annotation)
        return [_describe_annotation(args[0])] if args else ["string"]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return "one of: " + " | ".join(str(m.value) for m in annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {n: _describe_annotation(i.annotation) for n, i in annotation.model_fields.items()}
    return {bool: "true or false", int: "integer", float: "number"}.get(annotation, "string")


def _entry_model_for(fact_model, name: str):
    """A per-entry extraction model mirroring a fact model's own fields.

    Generated rather than hand-written seven times: the fields, their types and
    their F-numbers already live in src/facts/segment_facts.py, and a second
    copy would be a second thing to keep in step with the client's sheet.

    Every field is made Optional here even when the fact model requires it. A
    required field missing from the response would fail the whole response and
    lose the entries that were fine; instead the entry is dropped by
    _key_fields_present() and the rest survive.
    """
    fields = {}
    for field_name, info in fact_model.model_fields.items():
        if field_name in _BOOKKEEPING:
            continue
        annotation = info.annotation
        if info.default_factory is not None:
            fields[field_name] = (annotation, Field(default_factory=info.default_factory))
        else:
            fields[field_name] = (Optional[annotation], None)
    fields["citations"] = (list[_Citation], Field(default_factory=list))
    return create_model(name, **fields)


def _key_fields_present(fact_model, values: dict) -> bool:
    return all(
        values.get(name) not in (None, "", [], {})
        for name, info in fact_model.model_fields.items()
        if info.is_required() and name not in _BOOKKEEPING
    )


# Generated from the fact models rather than hand-written. They were written out
# once, and drifted: Curriculum gained `subjects` (P001) as a gated field while
# _CurriculumExtraction did not, so the citation gate demanded evidence for a
# field extraction had no way to populate. Deriving them means the field list
# has exactly one home -- src/facts/ -- and cannot fall out of step again.
_CurriculumExtraction = _entry_model_for(Curriculum, "_CurriculumExtraction")
_EligibilityExtraction = _entry_model_for(EligibilityRule, "_EligibilityExtraction")
_CourseExtraction = _entry_model_for(Course, "_CourseExtraction")
_SpecialisationEntry = _entry_model_for(Specialisation, "_SpecialisationEntry")
_SpecialisationExtraction = create_model(
    "_SpecialisationExtraction",
    specialisations=(list[_SpecialisationEntry], Field(default_factory=list)),
)


def extract_segment_facts(
    segment: str,
    chunks: list[Chunk],
    course,
    client: Optional[anthropic.Anthropic] = None,
) -> list[tuple[object, list[SourceRef]]]:
    """Cited extraction for the seven one-to-many segments.

    All of them are genuinely one-to-many -- a course accepts several entrance
    exams, reports salary by role and experience, and is offered by many
    institutions -- so each returns a list of (record, refs) the way
    extract_specialisation() does, not a single record.
    """
    fact_model, field_ids = SEGMENT_FACTS[segment]
    entry_model = _entry_model_for(fact_model, f"_{fact_model.__name__}Entry")
    wrapper = create_model(
        f"_{fact_model.__name__}Extraction",
        entries=(list[entry_model], Field(default_factory=list)),
    )

    parsed = _run_extraction(
        [Segment(segment)], chunks, segment.lower(), wrapper, course.course_id, client,
    )
    if parsed is None:
        return []

    results = []
    for entry in parsed.entries:
        values = entry.model_dump(exclude={"citations"})
        if not _key_fields_present(fact_model, values):
            continue
        record = fact_model(
            course_id=course.course_id,
            **_drop_uncited(values, entry.citations, field_ids),
        )
        results.append((record, _refs_from_citations(entry.citations, field_ids)))
    return results


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
        values = _drop_uncited(entry.model_dump(exclude={"citations"}), entry.citations,
                               SPECIALISATION_FIELD_IDS)
        # specialisation_name is F051 and therefore citation-gated, so an
        # uncited one is nulled above -- and a specialisation with no name is
        # not a record. Dropping the entry is the honest outcome; the other
        # entries in the same response are unaffected.
        if not _key_fields_present(Specialisation, values):
            continue
        spec = Specialisation(course_id=course.course_id, **values)
        refs = _refs_from_citations(entry.citations, SPECIALISATION_FIELD_IDS)
        results.append((spec, refs))
    return results
