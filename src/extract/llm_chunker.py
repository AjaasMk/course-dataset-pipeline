import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Optional, Union

import anthropic
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.extract.llm_clients import Provider, client_for, model_for, resolve
from src.extract.models import PageText
from src.extract.retry import call_with_retry
from src.retrieve.models import RETRIEVAL_SEGMENTS, Segment

SEGMENT_NAMES = [s.value for s in Segment if s in RETRIEVAL_SEGMENTS]
UNCLASSIFIED = "unclassified"

# Reasoning is switched OFF, and that is load-bearing rather than an
# optimisation. DeepSeek's compatibility endpoint reasons before answering and
# the reasoning is unbounded: measured 48k-67k characters of `thinking` on this
# task, exhausting every budget tried and returning stop_reason "max_tokens"
# with NO text block at all -- a silent empty success. Shrinking the window made
# it worse, not better (a 4k window produced MORE reasoning than a 12k one).
# Disabled, the same request answers in 764 output tokens instead of 16,000.
THINKING = {"type": "disabled"}

# 16k is the practical ceiling: above it the SDK requires streaming, because
# the call may exceed ten minutes. With reasoning off the real answers land
# around 1k, so this is headroom for a dense window rather than a target.
MAX_TOKENS = 16_000

# A whole document does not fit in one request, and splitting mid-sentence
# would invent boundaries the model then has to work around. Windows break on
# a blank line near the target size and overlap slightly so a section straddling
# a window boundary is still seen whole once.
WINDOW_CHARS = 24_000
WINDOW_OVERLAP_CHARS = 1_200

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# Spans the model returned that did not land inside the window, kept so a
# caller can report the loss instead of it disappearing quietly.
LAST_DROPPED: list = []

# Windows whose response could not be used, kept so a batch run can report
# partial coverage rather than presenting a document as fully chunked.
LAST_FAILED_WINDOWS: list = []

SYSTEM_PROMPT = """You segment ONE source document about Indian higher education into \
retrieval chunks. You are given the document's plain text with character offsets.

Return ONLY character offsets into that text. Never return the document text itself, \
never rewrite, summarise, normalise or correct it.

Assign every chunk to exactly one segment and one subsegment:

- segment MUST be one of: {segments}, or "unclassified".
  Use "unclassified" whenever the content does not genuinely belong to one of those \
segments -- boilerplate, committee lists, covering letters, navigation text. An honest \
"unclassified" is correct; a forced label is not.

  What each segment means. Judge by what the content is ABOUT, never by which \
words appear in its heading:
  * Course Identity -- the DEGREE PROGRAMME's own identity: its official name, \
common name, abbreviation, aliases, qualification level and type, academic or \
vocational status, regulating body.
  * Duration & Mode -- programme length, semester and credit counts, full-time, \
part-time, online, distance, and exit options.
  * Eligibility -- who may apply: prior qualification, accepted streams, \
compulsory subjects, minimum marks, age, medical fitness, portfolio, lateral entry.
  * Entrance & Admission -- entrance examinations, application and counselling \
process, seat allotment, admission dates.
  * Curriculum -- what is TAUGHT: subject and module lists, syllabi, credits per \
subject, laboratory and practical work, projects, dissertations, and internships \
as a curriculum component.
  * Specialisation -- named branches, streams or electives offered within the \
programme.
  * Institution & Offering -- which institutions run the programme, their \
ownership, location and sanctioned intake.
  * Ranking & Accreditation -- ranking bodies, ranks, scores, accreditation grades.
  * Fees -- tuition and any other cost of study. Scholarships -- financial aid \
schemes. Salary -- pay figures. Recruiters & Placement -- employers and placement \
counts. Career Mapping -- job roles and career routes.

  IMPORTANT, this is the most common mistake: in Indian syllabus documents the \
word "course" almost always means ONE SUBJECT, not the degree. Blocks headed \
"Course Code", "Course Title", "Course Outcomes", "Course Content", "Course \
Objectives" or "Course Articulation Matrix" describe a single subject and are \
therefore Curriculum. Label a chunk Course Identity ONLY when it states what the \
whole degree programme is called or how it is classified.

  Do not emit a chunk that is page furniture with no readable content -- \
table-of-contents dot leaders, bare page numbers, running headers and footers. \
Leave those spans out entirely.
- subsegment: prefer the data-field name the content supports (core_subjects, \
minimum_qualification, tuition_fee, median_salary). Fall back to the document's own \
heading when no field fits. Never claim a field the content does not evidence.

Chunk at REAL structural boundaries -- headings, sections, tables, lists, logical \
blocks. Never cut at a fixed size. Keep paragraphs, lists and tables together when \
they express one fact. If a section has subsections, chunk at the subsection level; \
otherwise chunk the whole section. When a large table must be split, repeat its \
column-header row in table_header so each part reads alone.

Set course_scope to "course_specific" when the content is about one named course, \
"shared" when it covers several, "institution_wide" when it describes an institution \
as a whole (a ranking table, an intake summary) rather than any one course.

Respond with a single JSON object, no prose and no markdown fences:

{{"document_id": "<echo the id given>",
  "segments": [
    {{"segment": "<segment>", "section_id": "<source anchor or empty>",
      "subsegments": [
        {{"subsegment": "<name>", "field_ids": ["F042"],
          "chunks": [
            {{"chunk_index": 0, "char_start": 0, "char_end": 0,
              "heading_path": ["outermost heading", "inner heading"],
              "block_type": "paragraph|list|table|table_rows|heading_block|mixed",
              "page_start": null, "page_end": null, "table_header": null,
              "course_scope": "course_specific|shared|institution_wide",
              "segment_confidence": 0.0}}
          ]}}
      ]}}
  ]}}"""


class ChunkerResponseInvalid(Exception):
    """Raised when the model's output cannot be trusted as chunk boundaries.

    Separate from a parse error so the caller can tell "the model returned
    something unusable" from "the request failed" -- the first is worth
    retrying with a different window, the second is not.
    """


class RawChunk(BaseModel):
    chunk_index: int = 0
    char_start: int
    char_end: int
    heading_path: list[str] = Field(default_factory=list)
    block_type: str = "paragraph"
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    table_header: Optional[Union[str, list[str]]] = None
    course_scope: str = "course_specific"
    segment_confidence: float = 0.0

    @field_validator("table_header", mode="before")
    @classmethod
    def _join_header_cells(cls, value):
        # Real responses return the header either as one string or as a list of
        # its cells; both mean the same thing, so neither should fail a document.
        if isinstance(value, list):
            return " | ".join(str(v) for v in value if v)
        return value


class RawSubsegment(BaseModel):
    subsegment: str = ""
    field_ids: list[str] = Field(default_factory=list)
    chunks: list[RawChunk] = Field(default_factory=list)


class RawSegment(BaseModel):
    segment: str
    section_id: str = ""
    raw_segment: Optional[str] = None
    subsegments: list[RawSubsegment] = Field(default_factory=list)


class ChunkerResponse(BaseModel):
    document_id: str = ""
    segments: list[RawSegment] = Field(default_factory=list)


class LLMChunk(BaseModel):
    """One chunk, with its text sliced from the source rather than echoed by
    the model, so quoted evidence stays byte-identical (Hard Constraint 2)."""

    chunk_id: int
    document_id: str
    text: str
    content_hash: str
    char_start: int
    char_end: int
    segment_id: Union[Segment, Literal["unclassified"]]
    subsegment: Optional[str] = None
    field_ids: list[str] = Field(default_factory=list)
    section_id: str = ""
    raw_segment: Optional[str] = None
    heading_path: list[str] = Field(default_factory=list)
    block_type: str = "paragraph"
    page_number: Optional[int] = None
    table_header: Optional[str] = None
    course_scope: str = "course_specific"
    segment_confidence: float = 0.0


def document_text(pages: list[PageText]) -> tuple[str, list[tuple[int, int, int]]]:
    """Flatten pages into one offset space, keeping a page map.

    The model reasons over a single continuous text, but a citation needs to
    name a page, so each page's span is recorded as (page_number, start, end)
    and looked up after slicing.
    """
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for page in pages:
        body = page.text or ""
        parts.append(body)
        spans.append((page.page_number, cursor, cursor + len(body)))
        cursor += len(body) + 1
    return "\n".join(parts), spans


# How far a boundary may travel to reach whitespace. Beyond this the span is
# left where the model put it: inside a long unbroken run (a URL, a wide table
# row) there is no word boundary to find, and dragging the chunk further from
# the requested position would distort it more than the ragged edge does.
SNAP_LIMIT = 64


def snap_to_word_boundaries(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span outward until both edges sit on whitespace.

    Character offsets are the one thing a language model counts badly: measured
    on the real pilot, 66% of chunks began mid-word and 46% ended mid-word
    ("Concept of Minor Degree" arriving as "ept of Minor Degree"). Correcting it
    here keeps the fix deterministic and keeps chunk text a verbatim slice of
    the source, which is what makes quoted evidence checkable.
    """
    limit = max(0, start - SNAP_LIMIT)
    while start > limit and not text[start - 1].isspace():
        start -= 1

    limit = min(len(text), end + SNAP_LIMIT)
    while end < limit and end < len(text) and not text[end].isspace():
        end += 1
    return start, end


def _page_for(offset: int, spans: list[tuple[int, int, int]]) -> Optional[int]:
    for number, start, end in spans:
        if start <= offset < end:
            return number
    return None


def json_object(raw: str) -> str:
    """Isolate the JSON object from a response that wandered into prose.

    Measured live: some documents came back as "I need to see..." followed by
    the object. Failing the whole document over a preamble throws away good
    boundaries for a cosmetic problem.
    """
    stripped = _JSON_FENCE.sub("", raw or "").strip()
    if stripped.startswith("{"):
        return stripped
    # Every "{" is a candidate start, not just the first one. Measured live: a
    # response echoed part of the source document before answering, and that
    # echoed text contained a brace, so first-brace-to-last-brace sliced a
    # fragment that was not JSON at all. Scanning balanced candidates and
    # keeping the first that actually parses cannot make that mistake.
    for start in _brace_positions(stripped):
        candidate = _balanced_object(stripped, start)
        if candidate is None:
            continue
        try:
            json.loads(candidate)
        except ValueError:
            continue
        return candidate
    return stripped


MIN_READABLE_WORDS = 3
MIN_LETTER_RATIO = 0.35


def is_readable(body: str) -> bool:
    """Whether a span carries enough prose to be about anything.

    Thresholds are deliberately loose: this rejects dot leaders, bare page
    numbers and running headers, not short-but-real content like a table row
    or a one-line heading with a value.
    """
    words = [w for w in re.findall(r"[A-Za-z]{2,}", body)]
    if len(words) < MIN_READABLE_WORDS:
        return False
    letters = sum(1 for c in body if c.isalpha() or c.isspace())
    return letters / len(body) >= MIN_LETTER_RATIO


def _brace_positions(text: str) -> list[int]:
    return [i for i, char in enumerate(text) if char == "{"]


def _balanced_object(text: str, start: int) -> Optional[str]:
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_response(raw: str, strict: bool = True) -> ChunkerResponse:
    stripped = json_object(raw)
    try:
        parsed = ChunkerResponse.model_validate_json(stripped)
    except (ValidationError, ValueError) as exc:
        raise ChunkerResponseInvalid(f"could not parse chunker output: {exc}") from exc

    allowed = set(SEGMENT_NAMES) | {UNCLASSIFIED}
    unknown = sorted({s.segment for s in parsed.segments} - allowed)
    if unknown and strict:
        raise ChunkerResponseInvalid(
            f"segment(s) outside the canonical vocabulary: {', '.join(unknown)}. "
            f"A chunk labelled with an unknown segment cannot route to extraction."
        )
    if unknown:
        # A plausible document heading is not a routing label. Measured live:
        # "Course Outcomes", "Evaluation Scheme", "Examination Pattern". The
        # chunk boundaries are still sound, so keep the text and demote the
        # label to unclassified rather than discarding the whole document --
        # an honest gap, per Hard Constraint 4.
        for segment in parsed.segments:
            if segment.segment not in allowed:
                # Kept in its own field rather than folded into section_id,
                # which often already holds a real source anchor. The rejected
                # label is evidence about the document worth keeping.
                segment.raw_segment = segment.segment
                segment.segment = UNCLASSIFIED
    return parsed


def slice_chunks(
    parsed: ChunkerResponse,
    text: str,
    document_id: str,
    page_spans: Optional[list[tuple[int, int, int]]] = None,
    offset: int = 0,
) -> list[LLMChunk]:
    chunks: list[LLMChunk] = []
    dropped: list[tuple[int, int]] = []
    counter = 0
    for segment in parsed.segments:
        segment_id: Union[Segment, str] = (
            UNCLASSIFIED if segment.segment == UNCLASSIFIED else Segment(segment.segment)
        )
        for sub in segment.subsegments:
            for raw in sub.chunks:
                # Offsets are requested relative to the window the model was
                # shown, but a model handed a base offset will sometimes return
                # absolute ones instead. Accept whichever actually lands inside
                # the window rather than failing on a difference that carries no
                # meaning -- confirmed live, one real document returned
                # window-relative offsets while another returned absolute.
                start, end = raw.char_start, raw.char_end
                if not (0 <= start <= end <= len(text)) and offset:
                    start, end = start - offset, end - offset
                # A single unusable span is dropped, not raised: one hallucinated
                # offset should cost that chunk, not the other 120 real ones in
                # the same document. Dropped counts are reported by the caller
                # so the loss stays visible rather than silent.
                if start > end or start < 0 or end > len(text):
                    dropped.append((raw.char_start, raw.char_end))
                    continue
                # Emptiness is judged BEFORE snapping: a zero-width span means
                # the model pointed at nothing, and widening it would invent an
                # adjacent word rather than recover an intended one.
                if not text[start:end].strip():
                    continue
                start, end = snap_to_word_boundaries(text, start, end)
                body = text[start:end].strip()
                if not body:
                    continue
                # Page furniture cannot carry a segment even when the model
                # labels it confidently. Measured live: a table-of-contents dot
                # leader ("......... 33") was emitted as Course Identity at
                # confidence 0.9. It survives as an unclassified chunk rather
                # than being dropped, so the document's text stays whole.
                chunk_segment = segment_id if is_readable(body) else UNCLASSIFIED
                chunks.append(
                    LLMChunk(
                        chunk_id=counter,
                        document_id=document_id,
                        text=body,
                        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
                        char_start=start + offset,
                        char_end=end + offset,
                        segment_id=chunk_segment,
                        subsegment=sub.subsegment or None,
                        field_ids=sub.field_ids,
                        section_id=segment.section_id,
                        raw_segment=segment.raw_segment,
                        heading_path=raw.heading_path,
                        block_type=raw.block_type,
                        page_number=raw.page_start
                        or (_page_for(start + offset, page_spans) if page_spans else None),
                        table_header=raw.table_header,
                        course_scope=raw.course_scope,
                        segment_confidence=raw.segment_confidence,
                    )
                )
                counter += 1
    if dropped:
        LAST_DROPPED.clear()
        LAST_DROPPED.extend(dropped)
    return chunks


def windows(text: str, size: int = WINDOW_CHARS, overlap: int = WINDOW_OVERLAP_CHARS):
    """Yield (offset, window) pairs broken on blank lines near the target size.

    Cutting mid-sentence would force the model to invent a boundary it can see
    is wrong; breaking on a paragraph gap keeps every window's edges real.
    """
    if len(text) <= size:
        yield 0, text
        return
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            gap = text.rfind("\n\n", start + size // 2, end)
            if gap > start:
                end = gap
        yield start, text[start:end]
        if end >= len(text):
            break
        start = max(end - overlap, end) if overlap >= (end - start) else end - overlap


_RETRYABLE = (anthropic.APIConnectionError, anthropic.RateLimitError)


def chunk_text(
    text: str,
    document_id: str,
    client: Optional[anthropic.Anthropic] = None,
    provider: Optional[Provider] = None,
    page_spans: Optional[list[tuple[int, int, int]]] = None,
    model: Optional[str] = None,
) -> list[LLMChunk]:
    chosen = resolve(provider)
    client = client or client_for(chosen)
    model = model or model_for(chosen, "fast")
    system = SYSTEM_PROMPT.format(segments=", ".join(f'"{s}"' for s in SEGMENT_NAMES))

    collected: list[LLMChunk] = []
    failed_windows: list[tuple[int, str]] = []
    for offset, window in windows(text):
        prompt = (
            f"document_id: {document_id}\n"
            f"char_offset_of_first_character: {offset}\n"
            f"--- DOCUMENT TEXT ---\n{window}"
        )
        response = call_with_retry(
            lambda: client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                thinking=THINKING,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
            ),
            retryable_errors=_RETRYABLE,
            description=f"chunk {document_id}",
        )
        # One window's failure must not cost the rest of the document. The
        # first pilot raised on any bad window and lost 41 of 81 documents
        # outright, most of which had produced good chunks in every other
        # window. Failures are counted and reported instead.
        body = next((b.text for b in response.content if b.type == "text"), None)
        if body is None:
            failed_windows.append((offset, f"no text block (stop={response.stop_reason})"))
            continue
        try:
            parsed = parse_response(body, strict=False)
            collected.extend(
                slice_chunks(parsed, window, document_id, page_spans=page_spans, offset=offset)
            )
        except ChunkerResponseInvalid as exc:
            failed_windows.append((offset, str(exc)[:120]))

    for index, chunk in enumerate(collected):
        chunk.chunk_id = index
    if failed_windows and not collected:
        raise ChunkerResponseInvalid(
            f"every window failed for {document_id}: {failed_windows[0][1]}"
        )
    LAST_FAILED_WINDOWS.clear()
    LAST_FAILED_WINDOWS.extend(failed_windows)
    return collected


def chunk_document(
    path: Path,
    document_id: str,
    client: Optional[anthropic.Anthropic] = None,
    provider: Optional[Provider] = None,
) -> list[LLMChunk]:
    from src.extract.readers import read_html, read_pdf

    if path.suffix.lower() == ".pdf":
        pages = read_pdf(path)
        text, spans = document_text(pages)
    else:
        sections = read_html(path)
        parts = []
        for section in sections:
            if section.heading_title:
                parts.append(section.heading_title)
            parts.extend(section.paragraphs)
        text, spans = "\n\n".join(parts), None
    return chunk_text(text, document_id, client=client, provider=provider, page_spans=spans)


def write_chunks(chunks: list[LLMChunk], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "[\n" + ",\n".join(c.model_dump_json() for c in chunks) + "\n]",
        encoding="utf-8",
    )
