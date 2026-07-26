import re
import time

import anthropic
import tiktoken

from src.extract.models import Chunk, PageText, Section

# Used only for _tail_tokens' overlap slicing (needs encode/decode to cut text
# at an exact token boundary; Anthropic exposes no offline tokenizer/decoder).
# The MAX_TOKENS boundary decision below uses the real API count instead --
# tiktoken confirmed live to undercount Claude's real tokenizer by ~2x on this
# content, so it must not be the source of truth for chunk sizing.
_ENCODING = tiktoken.get_encoding("cl100k_base")
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


def _tail_tokens(text: str, n: int) -> str:
    tokens = _ENCODING.encode(text)
    if len(tokens) <= n:
        return text
    return _ENCODING.decode(tokens[-n:])


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
            candidate = f"{buffer} {paragraph}".strip() if buffer else paragraph
            if buffer and _token_count(candidate, client) > MAX_TOKENS:
                chunks.append(_make_chunk(chunk_id, buffer, section, source_document, source_url, client))
                chunk_id += 1
                overlap = _tail_tokens(buffer, OVERLAP_TOKENS)
                buffer = f"{overlap} {paragraph}".strip() if overlap else paragraph
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
