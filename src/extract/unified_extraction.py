import json
import re
from pathlib import Path
from typing import Any, Optional

import anthropic

from src.extract.chunk_retrieval import retrieve
from src.extract.llm_chunker import json_object
from src.extract.llm_clients import client_for, model_for
from src.extract.models import Chunk
from src.extract.segment_queries import SEGMENT_QUERIES
from src.retrieve.base import document_id_for
from src.retrieve.models import RETRIEVAL_SEGMENTS

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 16_000
CLIENT_SCHEMA = Path("docs/specs by fmc/files/course-schema.json")

# One call per course, producing the CLIENT'S page tree directly rather than our
# segment shape translated afterwards. Their schema is the contract, so the model
# fills it; nothing downstream has to re-map field names.
#
# Provenance rides alongside instead of inside. Annotating each of their 152
# leaves as {value, source} would cost roughly 3,800 output tokens against a
# 16,000 ceiling, and their schema has no slot for a citation anyway. A separate
# citations array keyed by JSON path is equivalent, far cheaper, and leaves their
# tree exactly as specified.
#
# The guard that makes a merged extract-and-generate call honest: every claimed
# quote is checked against the evidence actually supplied. A quote that is not
# there loses its citation, so the field silently becomes generated rather than
# passing as sourced on the model's word.
SYSTEM_PROMPT = """You are building one Indian higher-education course page.

Course: {course}
Qualification level: {level}
Field of study: {field}

You will be given retrieved source documents, each labelled with a DOCUMENT_ID,
then the exact JSON schema the page must follow.

Fill EVERY field in the schema. Two ways to fill one:

1. FROM A DOCUMENT, when a supplied document states it. Record it in the
   "citations" array (described below) so it can be verified.

2. GENERATED, when no supplied document states it. Write general, typical
   information for this kind of course in India:
   - numeric values as INDICATIVE RANGES, never single precise figures
   - hedged phrasing: "commonly", "typically", "varies by institution"
   - never a specific institution, deadline, cut-off score or academic year
   - null only when you can say nothing useful and general at all

Never leave an array empty and never leave the page short: the schema's counts
are fixed. quickGrid needs exactly 6 cards, salaryValues exactly 3, fit.boxes
one "positive" and one "caution". Generate what the documents do not supply.

Subject and elective names carry NO course code. A regulator's model curriculum
numbers its subjects (PCC ME 201) but every university renumbers, so the code is
not a property of the course.

Respond with a single JSON object:

{{"course": {{ ...the schema, filled... }},
  "citations": [
    {{"path": "course.sections.subjects.tabs[0].content.items[0].title",
      "document_id": "<DOCUMENT_ID>",
      "quoted_evidence": "<text copied EXACTLY from that document, 15+ chars>"}}
  ]}}

List one citation per field taken from a document. Every quote is checked
character by character against the documents; a quote that does not appear
there is discarded and the field is recorded as generated. Quote precisely, and
never cite a document you were not given. Fields with no citation are
understood to be generated -- that is expected, not an error.

No prose, no markdown."""

TRAILER = """

End of source documents.

Now output the single JSON object described above. Start your reply with the
character {{ and end it with }}. Output nothing else."""

_WS = re.compile(r"\s+")
MIN_QUOTE_CHARS = 15


class UnifiedExtractionFailed(Exception):
    pass


def flatten(text: str) -> str:
    return _WS.sub(" ", text or "").strip().lower()


def client_schema() -> dict:
    return json.loads(CLIENT_SCHEMA.read_text(encoding="utf-8"))


def course_evidence(chunks: list[Chunk]) -> tuple[str, dict[str, str]]:
    """Retrieved evidence for every segment, in one labelled block.

    Also returns a per-document whitespace-flattened index for checking quotes.
    Normalising whitespace for the CHECK only: a PDF text layer collapses runs of
    spaces the model will not reproduce byte for byte, and failing an otherwise
    correct quote on that would push real evidence into the generated bucket.
    """
    selected: list[Chunk] = []
    for segment in sorted(RETRIEVAL_SEGMENTS, key=lambda s: s.value):
        if segment.value not in SEGMENT_QUERIES:
            continue
        matching = [c for c in chunks if c.segment_id == segment]
        if matching:
            selected.extend(retrieve(matching, segment.value).chunks)

    by_document: dict[str, list[Chunk]] = {}
    for chunk in selected:
        by_document.setdefault(document_id_for(chunk.source_url), []).append(chunk)

    blocks, index = [], {}
    for document_id, document_chunks in by_document.items():
        body = "\n\n".join(c.text for c in sorted(document_chunks, key=lambda c: c.chunk_id))
        blocks.append(f"--- DOCUMENT_ID: {document_id} ---\n{body}")
        index[document_id] = flatten(body)
    return "\n\n".join(blocks), index


def resolve_path(tree: dict, path: str) -> tuple[bool, Any]:
    """Follow a citation's JSON path into the produced tree.

    A citation naming a path that does not exist is as unusable as one quoting
    text that is not there -- both mean the model is describing something it did
    not produce.
    """
    node: Any = tree
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(node, list) or index >= len(node):
                return False, None
            node = node[index]
        else:
            if part == "course" and node is tree and "course" in tree:
                node = tree["course"]
                continue
            if not isinstance(node, dict) or part not in node:
                return False, None
            node = node[part]
    return True, node


def verify_citations(tree: dict, citations: list[dict],
                     index: dict[str, str]) -> tuple[list[dict], dict]:
    """Keep only citations whose quote is really in the document they name."""
    verified, audit = [], {"claimed": len(citations), "verified": 0,
                           "rejected": 0, "reasons": []}

    for citation in citations:
        path = citation.get("path") or ""
        document_id = citation.get("document_id")
        quote = (citation.get("quoted_evidence") or "").strip()

        if len(quote) < MIN_QUOTE_CHARS:
            reason = "quote too short to verify"
        elif document_id not in index:
            reason = "document was never supplied"
        elif flatten(quote) not in index[document_id]:
            reason = "quote not found in that document"
        elif not resolve_path(tree, path)[0]:
            reason = "path does not exist in the produced page"
        else:
            verified.append({"path": path, "document_id": document_id,
                             "quoted_evidence": quote})
            audit["verified"] += 1
            continue

        audit["rejected"] += 1
        audit["reasons"].append({"path": path[:80], "document_id": document_id,
                                 "reason": reason, "quote": quote[:60]})
    return verified, audit


def count_leaves(node: Any) -> int:
    if isinstance(node, dict):
        return sum(count_leaves(v) for v in node.values())
    if isinstance(node, list):
        return sum(count_leaves(v) for v in node)
    return 0 if node in (None, "") else 1


def extract_course_page(
    chunks: list[Chunk],
    course,
    client: Optional[anthropic.Anthropic] = None,
    provider: str = "anthropic",
) -> dict:
    """One call: retrieve, extract what is evidenced, generate the rest.

    Returns the client's page tree exactly as their schema specifies, plus a
    verified citation list and an audit of what was rejected. Fields with no
    verified citation are generated -- that is the design, not a gap.
    """
    evidence, index = course_evidence(chunks)
    client = client or client_for(provider)

    system = SYSTEM_PROMPT.format(
        course=getattr(course, "standard_course_name", getattr(course, "name", "")),
        level=getattr(course, "level", "Undergraduate"),
        field=(getattr(course, "fields", None) or ["not specified"])[0],
    ) + "\n\nSchema:\n" + json.dumps(client_schema())

    response = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": evidence + TRAILER}],
    )
    if response.stop_reason == "max_tokens":
        raise UnifiedExtractionFailed(
            f"page for {course.course_id!r} was cut off at max_tokens={MAX_TOKENS}. "
            f"One call per course is bounded by OUTPUT: the client's 152-field "
            f"tree plus citations sits close to the ceiling."
        )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise UnifiedExtractionFailed(
            f"page for {course.course_id!r} returned no text block "
            f"(stop_reason={response.stop_reason!r})"
        )

    parsed = json.loads(json_object(text))
    page = {"course": parsed.get("course", parsed)}
    verified, audit = verify_citations(page, parsed.get("citations") or [], index)

    populated = count_leaves(page)
    return {
        "course_id": course.course_id,
        "page": page,
        "citations": verified,
        "audit": {**audit, "fields_populated": populated,
                  "fields_sourced": len(verified),
                  "fields_generated": max(0, populated - len(verified))},
        "documents_supplied": sorted(index),
    }
