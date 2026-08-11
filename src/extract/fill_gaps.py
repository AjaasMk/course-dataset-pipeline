import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from src.extract.fallback_generation import TIER, _generate_fields
from src.extract.llm_clients import client_for, model_for
from src.extract.segment_schemas import schema_for
from src.facts.generated import GenerationReason, Provenance, provenance_for
from src.facts.models import SourceRef

# Three states a segment can be in, and they are not the same thing:
#
#   no chunks at all        -> nothing was retrieved. generate_segment(), with
#                              reason NO_SOURCE_FOUND. Handled by the caller;
#                              this module is never reached.
#   chunks, some fields     -> extraction cited what it could. This module
#                              fills the rest, reason SOURCE_SILENT.
#   chunks, zero fields     -> documents existed and said nothing usable. Still
#                              SOURCE_SILENT, not NO_SOURCE_FOUND: conflating
#                              them would hide a real sourcing signal behind a
#                              retrieval one, and they call for different fixes.
#
# The distinction is the whole reason this is a separate step rather than a
# branch inside generation.
SYSTEM_PROMPT = """You are completing the {segment} section for an Indian \
higher-education course. Official source documents WERE retrieved for this \
course, but they are silent on the fields below -- so these must be written as \
general, typical information, not quoted from anything.

Course: {course}
Qualification level: {level}
Field of study: {field}

Fields already established from the sources, for consistency. Do not contradict \
or repeat them:
{known}

Write ONLY these missing fields, into this JSON schema:

{schema}

Rules:
- Describe what is TYPICAL or COMMON for this kind of course in India.
- Numeric values must be INDICATIVE RANGES, never single precise figures.
- Use hedged phrasing: "commonly", "typically", "varies by institution".
- Never name a specific institution, admission deadline, cut-off score or
  academic year.
- Leave a field null when you cannot say anything useful and general about it.
  A null is better than a confident invention.
- Do not output any field that is not listed in the schema above.

Respond with a single JSON object. No prose, no markdown fences."""


@dataclass
class FilledRecord:
    """A record whose fields no longer come from one place.

    generated_fields is the audit trail: it names exactly which values have no
    evidence behind them, so a reader is never left inferring it from an empty
    citation list.
    """

    record: object
    refs: list[SourceRef]
    generated_fields: set[str] = field(default_factory=set)
    provenance: Provenance = Provenance.SOURCED
    reason: Optional[GenerationReason] = None

    @property
    def is_complete(self) -> bool:
        return not self.empty_fields

    empty_fields: set[str] = field(default_factory=set)


def _name(course) -> str:
    return getattr(course, "standard_course_name", None) or getattr(course, "name", "")


def _field(course) -> str:
    fields = getattr(course, "fields", None)
    if fields:
        return fields[0]
    return getattr(course, "field", "") or ""


def _is_empty(value) -> bool:
    return value in (None, "", [], {})


def fill_gaps(
    record,
    field_ids: dict[str, str],
    refs: list[SourceRef],
    course,
    segment: str,
    client: Optional[anthropic.Anthropic] = None,
    provider: str = "anthropic",
) -> FilledRecord:
    """Generate values for the fields extraction could not ground.

    Generated values can never acquire a citation: refs is returned exactly as
    extraction produced it, and nothing here appends to it. That is what keeps
    provenance_for() honest -- cited_fields can only ever count real evidence.
    """
    values = record.model_dump()
    missing = sorted(name for name in field_ids if _is_empty(values.get(name)))
    populated = {name for name in field_ids if not _is_empty(values.get(name))}

    if not missing:
        return FilledRecord(
            record=record,
            refs=refs,
            provenance=provenance_for(len(populated), len(populated)),
        )

    schema = schema_for(segment)
    known = {name: values[name] for name in sorted(populated)} or {"": "none established"}

    client = client or client_for(provider)
    model = model_for(provider, TIER)
    system = SYSTEM_PROMPT.format(
        segment=segment,
        course=_name(course),
        level=getattr(course, "level", "Undergraduate"),
        field=_field(course) or "not specified",
        known=json.dumps(known, default=str)[:2000],
        schema=json.dumps({name: schema.get(name, "string or list of strings") for name in missing}),
    )
    produced = _generate_fields(client, model, system, segment, course.course_id, _name(course))

    generated: set[str] = set()
    update = {}
    for name in missing:
        value = produced.get(name)
        if _is_empty(value):
            continue
        update[name] = value
        generated.add(name)

    filled = record.model_copy(update=update) if update else record
    after = record.model_dump() | update
    still_empty = {name for name in field_ids if _is_empty(after.get(name))}

    return FilledRecord(
        record=filled,
        refs=refs,
        generated_fields=generated,
        provenance=provenance_for(len(populated) + len(generated), len(populated)),
        reason=GenerationReason.SOURCE_SILENT if generated else None,
        empty_fields=still_empty,
    )
