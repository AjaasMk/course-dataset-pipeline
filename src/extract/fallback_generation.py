import json
import re
from typing import Optional

import anthropic

from src.extract.block_schemas import schema_for_block
from src.extract.llm_chunker import json_object
from src.extract.llm_clients import client_for, model_for
from src.extract.retry import call_with_retry
from src.facts.generated import (
    GenerationReason,
    GenerationRecord,
    Provenance,
    validate_generated,
)

MAX_TOKENS = 4096
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# Generation runs on the strong tier, not the cheap one. The chunker's job is
# mechanical and high volume; this one writes text that will be read as fact
# about a real course, so it gets the better model.
TIER = "strong"

SYSTEM_PROMPT = """You are writing the {segment} section for an Indian higher-education \
course library, for a course where NO official source document could be retrieved.

Course: {course}
Qualification level: {level}
Field of study: {field}

Sources that were checked and had nothing for this course: {attempted}

Write general, typical information for this kind of course in India, into this JSON schema:

{schema}

Rules:
- Describe what is TYPICAL or COMMON for this kind of course in India.
- Numeric values (fees, salaries, durations, marks) must be written as INDICATIVE \
RANGES, never single precise figures: "Rs 20,000 - Rs 3,00,000 per year", not \
"Rs 85,000 per year". A range communicates the real spread; a single number reads as \
a verified fact about this course, which it is not. This matches how the client's own \
course pages present indicative figures.
- Use hedged phrasing throughout: "commonly", "typically", "varies by institution and \
state".
- Never name a specific institution, a specific admission deadline, a specific cut-off \
score, or a specific academic year. Those are checkable claims and you have nothing to \
check them against.
- Leave a field null when you cannot say anything useful and general about it. A null \
is better than a confident invention.

Respond with a single JSON object matching the schema. No prose, no markdown fences."""


BLOCK_SYSTEM_PROMPT = """You are writing the "{block}" section of an Indian \
higher-education course page, for students in Grades 8-12 and their parents.

Course: {course}
Qualification level: {level}
Field of study: {field}

This section is advisory guidance. No regulator or university publishes it, so \
there is no source document to quote and none is expected.

Write it into this JSON schema:

{schema}

Rules:
- Be specific to THIS course. Guidance that would read identically for any \
degree is not useful to a family deciding between two of them.
- Say what is TYPICAL in India, hedged: "commonly", "varies by institution".
- Never name a specific institution, deadline, cut-off score or academic year.
- Numeric values must be indicative ranges, never single precise figures.
- Never state or imply that a graduate is guaranteed a job, a salary or a seat.
- Respect the item counts the schema asks for exactly.

Respond with a single JSON object matching the schema. No prose, no markdown fences."""


class GenerationFailed(Exception):
    pass


def generate_segment(
    course_id: str,
    course_name: str,
    segment: str,
    schema: dict,
    field_of_study: str = "",
    qualification_level: str = "Undergraduate",
    sources_attempted: Optional[list[str]] = None,
    reason: GenerationReason = GenerationReason.NO_SOURCE_FOUND,
    client: Optional[anthropic.Anthropic] = None,
    provider: str = "anthropic",
) -> GenerationRecord:
    """Produce content for a segment that has no source, marked as generated.

    The record it returns can never pass as sourced: validate_generated()
    rejects any citation on it, and the high-risk segments named in the
    client's Mandatory Human Review Matrix stay unpublishable regardless of
    how plausible the text reads.
    """
    client = client or client_for(provider)
    model = model_for(provider, TIER)
    attempted = sources_attempted or []

    system = SYSTEM_PROMPT.format(
        segment=segment,
        course=course_name,
        level=qualification_level,
        field=field_of_study or "not specified",
        attempted=", ".join(attempted) if attempted else "none recorded",
        schema=json.dumps(schema),
    )

    fields = _generate_fields(client, model, system, segment, course_id, course_name)

    record = GenerationRecord(
        course_id=course_id,
        segment=segment,
        provenance=Provenance.GENERATED,
        reason=reason,
        generator_model=model,
        sources_attempted=attempted,
        fields=fields,
    )
    validate_generated(record)
    return record


def _generate_fields(client, model, system, label, course_id, course_name) -> dict:
    response = call_with_retry(
        lambda: client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": f"Write the {label} section for {course_name}."}
            ],
        ),
        retryable_errors=(anthropic.APIConnectionError, anthropic.RateLimitError),
        description=f"generate {label} for {course_id}",
    )

    body = next((b.text for b in response.content if b.type == "text"), None)
    if body is None:
        raise GenerationFailed(
            f"no text block generating {label} for {course_id} "
            f"(stop_reason={response.stop_reason!r})"
        )

    try:
        fields = json.loads(json_object(_JSON_FENCE.sub("", body).strip()))
    except json.JSONDecodeError as exc:
        raise GenerationFailed(
            f"generated {label} for {course_id} was not valid JSON: {exc}"
        ) from exc

    fields.pop("citations", None)
    return fields


def generate_block(
    course_id: str,
    course_name: str,
    block: str,
    field_of_study: str = "",
    qualification_level: str = "Undergraduate",
    client: Optional[anthropic.Anthropic] = None,
    provider: str = "anthropic",
) -> GenerationRecord:
    """Produce one of the client page's advisory blocks.

    Separate from generate_segment() because the reason differs and that
    difference is the point: a generated segment records a retrieval gap
    somebody could close, a generated block records content that has no
    source to find.
    """
    client = client or client_for(provider)
    model = model_for(provider, TIER)

    system = BLOCK_SYSTEM_PROMPT.format(
        block=block,
        course=course_name,
        level=qualification_level,
        field=field_of_study or "not specified",
        schema=json.dumps(schema_for_block(block)),
    )
    fields = _generate_fields(client, model, system, block, course_id, course_name)

    record = GenerationRecord(
        course_id=course_id,
        segment=block,
        provenance=Provenance.GENERATED,
        reason=GenerationReason.NO_ATOMIC_SOURCE_EXISTS,
        generator_model=model,
        sources_attempted=[],
        fields=fields,
    )
    validate_generated(record)
    return record
