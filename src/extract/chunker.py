import re

import tiktoken

from src.extract.models import Chunk, PageText, Section

_ENCODING = tiktoken.get_encoding("cl100k_base")
MAX_TOKENS = 1000
OVERLAP_TOKENS = 125

_HEADING_MAX_LEN = 80
_SENTENCE_ENDINGS = (".", ",", ";")


def _token_count(text: str) -> int:
    return len(_ENCODING.encode(text))


def _tail_tokens(text: str, n: int) -> str:
    tokens = _ENCODING.encode(text)
    if len(tokens) <= n:
        return text
    return _ENCODING.decode(tokens[-n:])


def chunk_document(sections: list[Section], source_document: str, source_url: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    chunk_id = 0

    for section in sections:
        buffer = ""
        for paragraph in section.paragraphs:
            candidate = f"{buffer} {paragraph}".strip() if buffer else paragraph
            if buffer and _token_count(candidate) > MAX_TOKENS:
                chunks.append(_make_chunk(chunk_id, buffer, section, source_document, source_url))
                chunk_id += 1
                overlap = _tail_tokens(buffer, OVERLAP_TOKENS)
                buffer = f"{overlap} {paragraph}".strip() if overlap else paragraph
            else:
                buffer = candidate

        if buffer:
            chunks.append(_make_chunk(chunk_id, buffer, section, source_document, source_url))
            chunk_id += 1

    return chunks


def _make_chunk(chunk_id: int, text: str, section: Section, source_document: str, source_url: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        source_document=source_document,
        source_url=source_url,
        page_number=section.page_number,
        heading_title=section.heading_title,
        token_count=_token_count(text),
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
