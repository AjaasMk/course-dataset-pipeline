from __future__ import annotations

import json
from typing import Any

from .chunks import Chunk

SYSTEM_PROMPT = (
    "You research and structure course information for a school careers portal read by "
    "students in Grades 8-12 and their parents.\n"
    "\n"
    "Rules that override everything else:\n"
    "1. Return one JSON object matching the supplied schema. No prose, no markdown fence, no "
    "commentary before or after.\n"
    "2. Every factual claim must come from the sources you searched. If you cannot ground a "
    "figure, give the mainstream published range rather than inventing precision.\n"
    "3. Money is an integer in the base unit of the stated currency. Write 250000, never "
    "\"2.5 LPA\", \"2,50,000\" or \"INR 250000\".\n"
    "4. A fee field named annual means one academic year. If a source quotes the whole programme "
    "(\"40,000 for the full 4-year course\"), divide by the number of years before writing it into "
    "an annual field. Only a fees row explicitly marked frequency \"Total programme\" may carry a "
    "whole-programme figure.\n"
    "5. Named organisations and institutions must be real and currently operating. Never emit "
    "placeholder names such as \"University A\" or \"Company B\".\n"
    "6. Write for a 15-year-old and their parent: plain, calm, specific. No marketing language, "
    "no guarantees about salary or admission.\n"
    "7. Where a career is regulated, say what stands between graduation and that role.\n"
    "8. Never describe your own process. The reader is a family looking at a course page, not "
    "someone watching you work. Never write \"the search results\", \"the source snippets\", "
    "\"this conversation\", \"where the source gave\", \"not consistently published\", or any "
    "explanation of what you could or could not find. Note fields explain the subject to the "
    "reader; they are not a log of your retrieval.\n"
    "9. If a figure is unavailable, give the mainstream published range for the region rather "
    "than narrating the gap."
)


def build_user_prompt(
    chunk: Chunk,
    *,
    course_name: str,
    region: str,
    currency: str,
    schema: dict[str, Any],
    context: dict[str, Any] | None = None,
    include_schema: bool = False,
) -> str:
    sections = [
        f"Course: {course_name}",
        f"Region all figures must describe: {region}",
        f"Currency for every money field: {currency}",
        "",
        f"Section to produce: {chunk.title}",
        chunk.focus,
        "",
        "Populate exactly these top-level keys and no others: " + ", ".join(chunk.properties),
    ]
    if context:
        sections += [
            "",
            "Already established for this course; stay consistent with it and do not contradict it:",
            json.dumps(context, ensure_ascii=False, indent=2),
        ]
    if include_schema:
        sections += [
            "",
            "JSON Schema the response must satisfy:",
            json.dumps(schema, ensure_ascii=False),
        ]
    return "\n".join(sections)


def build_repair_prompt(
    chunk: Chunk,
    *,
    course_name: str,
    region: str,
    currency: str,
    schema: dict[str, Any],
    previous_output: dict[str, Any],
    error_lines: list[str],
    context: dict[str, Any] | None = None,
    include_schema: bool = False,
) -> str:
    base = build_user_prompt(
        chunk,
        course_name=course_name,
        region=region,
        currency=currency,
        schema=schema,
        context=context,
        include_schema=include_schema,
    )
    return "\n".join(
        [
            base,
            "",
            "Your previous attempt was rejected by automated validation.",
            "",
            "Previous output:",
            json.dumps(previous_output, ensure_ascii=False),
            "",
            "Validation failures to fix:",
            *error_lines,
            "",
            "Return the corrected object in full. Fix only what the failures name; keep every "
            "other value that was already correct.",
        ]
    )
