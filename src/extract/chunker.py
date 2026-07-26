import re
import time

import anthropic

from src.extract.models import Chunk, PageText, Section

MODEL = "claude-sonnet-5"
MAX_TOKENS = 1000
OVERLAP_TOKENS = 125

_HEADING_MAX_LEN = 80
_SENTENCE_ENDINGS = (".", ",", ";")

# count_tokens() now runs once per paragraph-append decision across every
# document -- a transient network blip anywhere previously killed the whole
# batch (confirmed live: an APIConnectionError partway through a 50-document
# run). Retry only APIConnectionError -- auth/permission/billing errors are
# real failures that should surface immediately, not be masked by a retry loop.
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2.0


def _token_count(text: str, client: anthropic.Anthropic) -> int:
    last_error: anthropic.APIConnectionError | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.count_tokens(
                model=MODEL, messages=[{"role": "user", "content": text}]
            ).input_tokens
        except anthropic.APIConnectionError as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_error


# _tail_tokens has no offline decoder to cut text at an exact token boundary
# with (Anthropic exposes only count_tokens(), a counting-only endpoint --
# tiktoken used to fill this gap locally, but its boundaries don't match
# Claude's real tokenizer). Instead, iteratively narrow a word-count slice
# toward the target using real counts -- approximate, not exact, but
# converges in a few free API calls rather than trusting a wrong tokenizer.
_TAIL_TRIM_ATTEMPTS = 4


def _tail_tokens(text: str, n: int, client: anthropic.Anthropic) -> str:
    words = text.split()
    if not words:
        return text

    count = min(len(words), n)
    candidate = " ".join(words[-count:])
    for _ in range(_TAIL_TRIM_ATTEMPTS):
        actual = _token_count(candidate, client)
        if actual <= n or count >= len(words):
            return candidate
        count = max(1, int(count * n / actual))
        candidate = " ".join(words[-count:])
    return candidate


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Fallback grouping size (words) for the rare case where a single "sentence"
# has no punctuation to split on (e.g. an unbroken table row/list rendered as
# one line) and is still oversized after sentence splitting.
_WORD_GROUP_SIZE = 150


def _shrink_to_fit(text: str, client: anthropic.Anthropic) -> list[str]:
    if _token_count(text, client) <= MAX_TOKENS:
        return [text]
    words = text.split()
    return [" ".join(words[i : i + _WORD_GROUP_SIZE]) for i in range(0, len(words), _WORD_GROUP_SIZE)]


def _split_oversized_text(text: str, client: anthropic.Anthropic) -> list[str]:
    """Split a single paragraph that alone exceeds MAX_TOKENS into smaller
    pieces, each within MAX_TOKENS. Confirmed live: real-tokenizer chunk
    sizing (see _token_count) surfaced a pre-existing gap -- chunk_document's
    paragraph-packing loop never splits a single paragraph, so one oversized
    paragraph (e.g. a long "What is X" intro block with no internal
    whitespace break) became its own ~2x-over-limit chunk. Splits at sentence
    boundaries first (keeps pieces readable); falls back to fixed-size word
    grouping only if a single sentence is itself still oversized."""
    sentences = _SENTENCE_SPLIT_RE.split(text)
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if buffer and _token_count(candidate, client) > MAX_TOKENS:
            pieces.extend(_shrink_to_fit(buffer, client))
            buffer = sentence
        else:
            buffer = candidate
    if buffer:
        pieces.extend(_shrink_to_fit(buffer, client))
    return pieces


def chunk_document(
    sections: list[Section],
    source_document: str,
    source_url: str,
    client: anthropic.Anthropic | None = None,
) -> list[Chunk]:
    client = client or anthropic.Anthropic()
    chunks: list[Chunk] = []
    chunk_id = 0

    for section in sections:
        buffer = ""
        for paragraph in section.paragraphs:
            pieces = (
                _split_oversized_text(paragraph, client)
                if _token_count(paragraph, client) > MAX_TOKENS
                else [paragraph]
            )
            for piece in pieces:
                candidate = f"{buffer} {piece}".strip() if buffer else piece
                if buffer and _token_count(candidate, client) > MAX_TOKENS:
                    chunks.append(_make_chunk(chunk_id, buffer, section, source_document, source_url, client))
                    chunk_id += 1
                    overlap = _tail_tokens(buffer, OVERLAP_TOKENS, client)
                    buffer = f"{overlap} {piece}".strip() if overlap else piece
                else:
                    buffer = candidate

        if buffer:
            chunks.append(_make_chunk(chunk_id, buffer, section, source_document, source_url, client))
            chunk_id += 1

    return chunks


def _make_chunk(
    chunk_id: int,
    text: str,
    section: Section,
    source_document: str,
    source_url: str,
    client: anthropic.Anthropic,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        source_document=source_document,
        source_url=source_url,
        page_number=section.page_number,
        heading_title=section.heading_title,
        token_count=_token_count(text, client),
    )


def _looks_like_heading(line: str) -> bool:
    # ALL CAPS only, not Title Case: verified against the real AICTE PDF that
    # real section headings ("PREAMBLE", "PROFESSIONAL CORE COURSES") are
    # consistently ALL CAPS, while Title Case false positives (committee-roster
    # names, addresses) are common in this document's front matter.
    if not line or len(line) > _HEADING_MAX_LEN:
        return False
    if not re.search(r"[A-Za-z]", line):
        return False
    if line.endswith(_SENTENCE_ENDINGS):
        return False
    return line.isupper()


def detect_pdf_sections(pages: list[PageText]) -> list[Section]:
    sections: list[Section] = []
    current_heading = None
    current_page = pages[0].page_number if pages else None
    current_paragraphs: list[str] = []
    current_para_lines: list[str] = []

    def flush_paragraph():
        if current_para_lines:
            current_paragraphs.append(" ".join(current_para_lines).strip())
            current_para_lines.clear()

    def flush_section():
        flush_paragraph()
        if current_paragraphs:
            sections.append(
                Section(heading_title=current_heading, page_number=current_page, paragraphs=list(current_paragraphs))
            )
            current_paragraphs.clear()

    for page in pages:
        for raw_line in page.text.split("\n"):
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                continue
            if _looks_like_heading(line):
                flush_section()
                current_heading = line
                current_page = page.page_number
            else:
                current_para_lines.append(line)

    flush_section()
    return sections
