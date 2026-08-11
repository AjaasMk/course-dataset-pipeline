import hashlib
import re
from pathlib import Path
from typing import Optional

from src.extract.llm_chunker import LLMChunk, document_text

# Measured live 2026-08-11, before this module existed: the LLM chunker's own
# output averaged 755 chars (~210 tokens) with a median of 426 (~118), and 22%
# of chunks were under 200 chars. Against the real evidence a Curriculum
# extraction cites (mean 3,205 tokens), a top-5 retrieval budget at that size
# carries only 1,050 tokens and covered 6 of 20 calls. At ~700 tokens the same
# top-5 carries 3,500 and covers 15 of 20. The envelope is what makes a small
# top-k viable at all, so these are requirements, not preferences.
CHARS_PER_TOKEN = 3.6
TARGET_TOKENS = 700
MIN_TOKENS = 600
MAX_TOKENS = 800
HARD_MAX_TOKENS = 900
OVERLAP_TOKENS = 100

# Merging and splitting work on the span BEFORE overlap is prepended, so every
# budget is reduced by the overlap the chunk will later grow by. Measured: with
# the caps applied to the pre-overlap span, normalisation raised the number of
# oversized chunks from 110 to 166 -- it was enforcing a ceiling and then
# stepping over it.
_CORE_TARGET = TARGET_TOKENS - OVERLAP_TOKENS
_CORE_MAX = MAX_TOKENS - OVERLAP_TOKENS
_CORE_HARD_MAX = HARD_MAX_TOKENS - OVERLAP_TOKENS

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n{2,}")


def tokens_for(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def _chars(tokens: int) -> int:
    return int(tokens * CHARS_PER_TOKEN)


def source_text_for(path: Path) -> str:
    """The same flattened offset space the chunker indexed against.

    Re-read rather than reconstructed from the stored chunk texts: 154 of 4,772
    chunks have text shorter than their span because slicing strips whitespace,
    so arithmetic on stored text would drift from the real offsets. Re-slicing
    from source is the only way a normalised chunk stays byte-identical to the
    document, which Hard Constraint 2's quoted evidence depends on.
    """
    from src.extract.readers import read_html, read_pdf

    if path.suffix.lower() == ".pdf":
        text, _ = document_text(read_pdf(path))
        return text
    parts: list[str] = []
    for section in read_html(path):
        if section.heading_title:
            parts.append(section.heading_title)
        parts.extend(section.paragraphs)
    return "\n\n".join(parts)


def _boundaries(body: str) -> list[int]:
    """Offsets a split may fall on, best available for this text.

    Sentence ends are preferred, but a curriculum PDF's largest spans are
    tables and subject lists with no sentence punctuation at all -- exactly the
    spans most in need of splitting. Falling back to word boundaries keeps the
    envelope enforceable there; only a text with neither is left oversized.
    """
    ends = [m.end() for m in _SENTENCE_END.finditer(body)]
    if ends:
        return ends
    return [m.end() for m in re.finditer(r"\S+\s+", body)]


def _split_span(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Break an oversized span at a real boundary, never mid-word."""
    body = text[start:end]
    target = _chars(_CORE_TARGET)
    pieces: list[tuple[int, int]] = []
    cursor = 0
    for boundary in _boundaries(body):
        if boundary - cursor >= target:
            pieces.append((start + cursor, start + boundary))
            cursor = boundary
    if cursor < len(body):
        # A tail too small to stand alone belongs with the piece before it
        # rather than as a fragment -- undersized chunks are the problem this
        # module exists to remove. It only absorbs it if the result still fits
        # the envelope, or the fix would reintroduce the oversize it just cut.
        tail_fits = pieces and len(body) - cursor < _chars(MIN_TOKENS)
        absorbed = (pieces[-1][0], end) if pieces else None
        if tail_fits and tokens_for(text[absorbed[0] : absorbed[1]]) <= _CORE_HARD_MAX:
            pieces[-1] = absorbed
        else:
            pieces.append((start + cursor, end))
    return pieces or [(start, end)]


def _merge_spans(spans: list[tuple[int, int]], text: str) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    current: Optional[tuple[int, int]] = None
    for start, end in spans:
        if current is None:
            current = (start, end)
            continue
        candidate = (current[0], max(current[1], end))
        size = tokens_for(text[candidate[0] : candidate[1]])
        if size <= _CORE_MAX:
            current = candidate
            continue
        # Merging past the band is still right when the chunk in hand is
        # undersized -- one 850-token chunk beats a 500 and a 350.
        if tokens_for(text[current[0] : current[1]]) < MIN_TOKENS and size <= _CORE_HARD_MAX:
            current = candidate
            continue
        merged.append(current)
        current = (start, end)
    if current is not None:
        merged.append(current)

    sized: list[tuple[int, int]] = []
    for start, end in merged:
        if tokens_for(text[start:end]) > _CORE_HARD_MAX:
            sized.extend(_split_span(text, start, end))
        else:
            sized.append((start, end))
    return sized


def normalise(chunks: list[LLMChunk], text: str) -> list[LLMChunk]:
    """Bring one document's chunks into the size envelope.

    Groups by segment before merging, so a merge can never join content the
    label fix separated -- a Curriculum span and a Course Identity span stay
    distinct chunks however small either is.
    """
    if not chunks:
        return []

    by_segment: dict[str, list[LLMChunk]] = {}
    for chunk in chunks:
        by_segment.setdefault(str(chunk.segment_id), []).append(chunk)

    produced: list[tuple[int, int, LLMChunk]] = []
    for segment_chunks in by_segment.values():
        ordered = sorted(segment_chunks, key=lambda c: c.char_start)
        spans = _merge_spans([(c.char_start, c.char_end) for c in ordered], text)
        for start, end in spans:
            source = min(
                ordered,
                key=lambda c: abs(c.char_start - start) + abs(c.char_end - end),
            )
            produced.append((start, end, source))

    produced.sort(key=lambda item: item[0])
    out: list[LLMChunk] = []
    for index, (start, end, source) in enumerate(produced):
        # Overlap is taken from the document, not from the previous chunk's
        # object, so the widened span is still one contiguous slice of the
        # source and its text remains quotable verbatim.
        overlap_start = max(0, start - _chars(OVERLAP_TOKENS)) if index else start
        body = text[overlap_start:end]
        if not body.strip():
            continue
        out.append(
            source.model_copy(
                update={
                    "chunk_id": len(out),
                    "text": body,
                    "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
                    "char_start": overlap_start,
                    "char_end": end,
                }
            )
        )
    return out
