import json
import re

import anthropic

from src.extract.models import Chunk
from src.schema import CourseDetail

MODEL = "claude-sonnet-5"
# 4096 was tried first and truncated mid-JSON on a real course (confirmed live,
# not a guess) — this schema's full output (job_profiles, top_colleges, faqs,
# syllabus all populated) runs bigger than the narrow 4-field shape did.
MAX_TOKENS = 8192


class ExtractionTruncatedError(Exception):
    """Raised when the model's response was cut off by max_tokens before
    finishing the JSON object, rather than failing with a confusing JSON
    parse error."""

# NOTE: does not use output_config/strict structured outputs — CourseDetail's
# nested schema (9 models, many Optional unions) triggers a real API limit:
# "The compiled grammar is too large" (confirmed live, not theoretical).
# Falls back to schema-in-prompt + client-side Pydantic validation instead.
SYSTEM_PROMPT = """You extract structured information about an Indian academic course \
from a retrieved source document, into the following JSON schema:

{schema}

- Ground each field in the source document when it states the fact.
- If the source document does not cover a field, fill it from general, typical \
knowledge for that kind of course in India rather than leaving it empty.
- Normalize as you extract: convert fee figures to plain integers in the given \
currency (e.g. "Rs. 2 Lakhs" -> 200000), collapse duplicate or synonymous entrance \
exam names into one canonical form, and follow each field's stated length guidance.
- Respond with a single JSON object that validates against the schema above. No \
prose, no markdown code fences, no commentary — output only the JSON object."""

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def reconstruct_document(chunks: list[Chunk]) -> str:
    ordered = sorted(chunks, key=lambda c: c.chunk_id)
    return "\n\n".join(chunk.text for chunk in ordered)


def _strip_markdown_fence(text: str) -> str:
    return _JSON_FENCE_RE.sub("", text).strip()


def extract_course_detail(
    chunks: list[Chunk],
    course_name: str,
    category: str,
    client: anthropic.Anthropic | None = None,
) -> CourseDetail:
    client = client or anthropic.Anthropic()
    document_text = reconstruct_document(chunks)
    schema_json = json.dumps(CourseDetail.model_json_schema())

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        # Explicit cache_control on the system block (not top-level auto-cache,
        # which would cache the last cacheable block — here that's the varying
        # per-course `messages` content, not the identical-every-call schema).
        # The schema (~2,833 tokens) and instructions are byte-identical across
        # every course; only the reconstructed document text below varies.
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT.format(schema=schema_json),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Course name: {course_name}\nCategory: {category}\n\n"
                    f"Source document:\n{document_text}"
                ),
            }
        ],
    )
    if response.stop_reason == "max_tokens":
        raise ExtractionTruncatedError(
            f"Response for {course_name!r} was cut off at max_tokens={MAX_TOKENS} "
            "before the JSON object finished. Raise MAX_TOKENS further."
        )

    text = next(block.text for block in response.content if block.type == "text")
    return CourseDetail.model_validate_json(_strip_markdown_fence(text))
