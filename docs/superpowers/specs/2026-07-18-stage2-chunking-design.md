# Stage 2 Phase 1: Document Reading + Chunking Pipeline — Design

Date: 2026-07-18
Status: Approved

## Scope

Phase 1 of Stage 2 (Extract): read the 50 real documents already downloaded
in Stage 1 (`data/raw/`), split each into hierarchical, metadata-tagged
chunks. No LLM involvement, no extraction logic — this is purely the
reading/chunking layer Phase 2 (extraction orchestration, deferred until an
`LLMProvider` is chosen) will consume. Fully buildable and testable today
against real documents, independent of any provider decision.

## Engineering decisions (user-specified, not renegotiated)

- No LangChain/LlamaIndex/text-splitting libraries — chunking logic is
  hand-written. Libraries are used only for *reading* documents: `pypdf`
  (new dependency) for PDF, `BeautifulSoup` (existing dependency) for HTML.
- `tiktoken` (new dependency) measures chunk size in real tokens — this is
  measurement, not chunking logic, so it doesn't conflict with the
  hand-written-chunking rule (same category as `pypdf`/`BeautifulSoup`:
  a reading/measurement tool, not the splitting algorithm itself).
- Chunking strategy: preserve document hierarchy, split primarily by
  heading/section, split large sections further by paragraph, target
  700–1000 tokens per chunk, ~100–150 token overlap between adjacent
  chunks, never split mid-sentence.
- Per-chunk metadata: `chunk_id`, source document, page number (PDF only),
  heading/section title, source URL.
- `LLMProvider` as a `Protocol` (no concrete implementation) is Phase 2's
  concern, not Phase 1's — Phase 1 doesn't reference it at all.

## Verified against real documents before finalizing

- **HTML**: real `<h1>`/`<h2>`/`<h3>` tags exist and are usable directly
  (confirmed: Careers360's Mechanical Engineering page has 1 `h1`, 17 `h2`,
  35 `h3`). No heuristics needed for HTML heading detection.
- **PDF**: `pypdf`'s `extract_text()` gives raw text with real ALL-CAPS
  section headings on their own line (confirmed: "PREAMBLE", "PROFESSIONAL
  CORE COURSES [PCC] (Total 16)" in the real AICTE Mechanical Engineering
  PDF) — heuristic pattern-matching is viable for this document type.
- **New requirement discovered from real data, not in the original spec**:
  every page of the AICTE PDF repeats the same header line ("AICTE revised
  Model Curriculum for UG Degree Course in Mechanical Engineering") plus a
  page number. Left unstripped, this noise would appear at the start of
  nearly every chunk from that document. Phase 1 must strip repeated
  page-header/footer lines before chunking, not just extract raw text
  per page.
- **Known, accepted limitation**: some PDF pages are pure tabular data
  (e.g. course-code/credit tables with no real sentences). "Avoid
  splitting mid-sentence" doesn't meaningfully apply to a table — Phase 1
  chunks tables as their own paragraph-like unit rather than attempting
  sentence-aware splitting on non-prose content. Not solved further in
  this phase; a real, visible limitation if it causes problems downstream.

## Architecture

```
src/extract/
  readers.py     # read_pdf(path) -> list[PageText], read_html(path) -> HtmlDoc
  chunker.py      # chunk_document(...) -> list[Chunk]
```

### Reading

`readers.py`:
- `read_pdf(path: Path) -> list[PageText]` — one `PageText` per page
  (`page_number: int`, `raw_text: str`), using `pypdf.PdfReader`. Before
  returning, strips repeated header/footer lines: any line that appears
  identically on ≥3 pages is treated as page-furniture and removed from
  every page's text.
- `read_html(path: Path) -> HtmlDoc` — parses with `BeautifulSoup`, walks
  the DOM preserving heading hierarchy (`h1`/`h2`/`h3` → nesting level),
  returns a tree of `(heading_title, level, text)` sections in document
  order.

### Chunking

`chunker.py`:
- `chunk_document(sections, source_document: str, source_url: str) -> list[Chunk]`
  — takes the heading-delimited sections from either reader (PDF sections
  are derived from the ALL-CAPS/numbered-heading heuristic over the
  cleaned page text; HTML sections come directly from real tags), and:
  1. For each section, if its token count (via `tiktoken`) fits in
     700–1000 tokens, it's one chunk.
  2. If larger, split further by paragraph boundaries, greedily packing
     paragraphs up to ~1000 tokens without exceeding it, never splitting
     inside a paragraph/sentence.
  3. Add ~100–150 tokens of trailing overlap from the previous chunk's end
     to each chunk after the first (so context isn't lost at a boundary).
  4. Assign a sequential `chunk_id` and attach metadata.

```python
class Chunk(BaseModel):
    chunk_id: int
    text: str
    source_document: str    # e.g. "data/raw/engineering/regulator_pdf/mechanical_engineering.pdf"
    source_url: str         # from the manifest entry
    page_number: Optional[int] = None   # PDF only, None for HTML
    heading_title: Optional[str] = None
    token_count: int
```

### PDF heading detection (heuristic)

A line is treated as a heading if, after stripping page-furniture:
- it is short (under ~80 characters),
- it is ALL CAPS or Title Case,
- it does not end in typical sentence punctuation (`.`, `,`, `;`),
- and the next non-blank line starts a new block (blank line or indent
  change) rather than continuing the same sentence.

This is deliberately approximate — verified against the actual AICTE PDF's
real heading style, not designed in the abstract. Sections between
detected headings become the unit passed into the paragraph-splitting step.

## Output: chunks are persisted to disk

Per this project's own debuggability standard ("every meaningful step
should be traceable in isolation"), chunks are **not** computed in-memory
and immediately discarded — each course's chunks are written to
`data/chunks/<course_slug>.json` (gitignored, regenerable, same treatment
as `data/raw/`), so the chunking step can be inspected, re-run, and
debugged independently of Phase 2's extraction logic once it exists.

## Testing

- `tests/test_readers.py` — `read_pdf()`/`read_html()` against small,
  hand-crafted fixture files (not the full real 162-page PDF, for fast
  tests) covering: repeated-header stripping, heading-hierarchy extraction
  from HTML, page number tracking.
- `tests/test_chunker.py` — `chunk_document()` against synthetic section
  inputs: a short section fits in one chunk; a long section splits by
  paragraph without exceeding ~1000 tokens; adjacent chunks share the
  expected ~100–150 token overlap; sentences are never split mid-way.
- Manual verification: run the full pipeline against the real 50
  documents in `data/raw/`, inspect a sample of `data/chunks/*.json` by
  eye for sane chunk boundaries and metadata — not a scripted assertion
  (chunk quality is a judgment call, not a pass/fail unit test), reported
  honestly either way.
