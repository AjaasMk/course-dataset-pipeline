# Course Library API — prototype contract

**Provisional**, alongside `laravel_schema.sql`. The client has not confirmed
schema ownership (recorded as blocked in CLAUDE.md), so this exists to make the
conversation concrete, not to pre-empt it.

## The rule that shapes every endpoint

**Provenance is admin-only.** Public endpoints return content and never say
whether it was sourced or generated. Admin endpoints return the full trail.
This follows the client's demo template, which carries no per-field source
markers, and plan Decision 1 (*"surfaced only in an admin interface — never in
the user-facing site"*).

Two audiences, two shapes, one database.

---

## Public

### `GET /api/courses`
Browse and filter. Returns only publishable segments.

```
?field=Engineering & Applied Technology
?level=Undergraduate
?q=mechanical
&page=1&per_page=20
```

```json
{ "data": [ { "course_key": "mechanical_engineering",
              "standard_course_name": "Mechanical Engineering",
              "field_of_study": "Engineering & Applied Technology",
              "qualification_level": "Undergraduate" } ],
  "meta": { "current_page": 1, "last_page": 38, "total": 750 } }
```

### `GET /api/courses/{course_key}`
One course, all 14 segments. **Always 14** — a segment with nothing behind it
returns `"content": null` rather than being absent, because "we have no data"
and "this segment does not exist" are different claims.

```json
{ "data": {
    "course_key": "mechanical_engineering",
    "standard_course_name": "Mechanical Engineering",
    "segments": {
      "Curriculum": {
        "content": { "core_subjects": ["Thermodynamics", "Fluid Mechanics"],
                     "electives": ["Robotics"] } },
      "Salary": { "content": null }
    } } }
```

No `provenance`, no `generator_model`, no `citations`. A consumer cannot tell
sourced from generated — by design.

### `GET /api/courses/{course_key}/segments/{segment}`
One segment, same shape.

### `GET /api/institutions?course={course_key}`
Ranked institutions offering a course.

```json
{ "data": [ { "canonical_name": "Indian Institute of Technology Madras",
              "city": "Chennai", "state": "Tamil Nadu",
              "ownership_type": "Government",
              "rankings": [ { "body": "NIRF", "category": "Engineering",
                              "year": "2025", "rank": 1, "score": 89.46 } ] } ] }
```

---

## Admin (authenticated)

### `GET /api/admin/courses/{course_key}`
Everything the public endpoint hides.

```json
{ "data": {
    "course_key": "mechanical_engineering",
    "segments": [
      { "segment": "Curriculum",
        "provenance": "sourced",
        "review_required": true, "publishable": true,
        "reviewed_by": null,
        "fields": [
          { "field_key": "core_subjects", "field_id": "F042",
            "value": ["Thermodynamics", "Fluid Mechanics"],
            "is_generated": false,
            "citations": [
              { "document_key": "DOC-4f42...",
                "document_title": "Revised Model Curriculum ... Mechanical Engineering",
                "source": "AICTE", "tier": "A",
                "quoted_evidence": "...exact text from the document...",
                "page_number": "34",
                "verification_status": "pending" } ] } ] },

      { "segment": "Fees",
        "provenance": "generated",
        "generator_model": "claude-sonnet-5",
        "generated_at": "2026-08-11T08:26:32Z",
        "attempted_sources": ["UGC", "AICTE", "COLLEGEDUNIA"],
        "review_required": true, "publishable": true,
        "fields": [
          { "field_key": "tuition_fee_range", "field_id": null,
            "value": "Approximately Rs 50,000 to Rs 2,00,000 per year",
            "is_generated": true,
            "citations": [] } ] } ] } }
```

`citations` is always `[]` where `is_generated` is true — enforced by the
schema, since `source_refs` hangs off `segment_fields` and a generated field
has no row there.

### `GET /api/admin/coverage`
The operational view — what is sourced, what is generated, what is empty.

```json
{ "data": { "courses": 750, "segments_per_course": 14, "cells": 10500,
            "sourced": 5235, "generated": 44, "no_source_found": 5221,
            "by_segment": [ { "segment": "Curriculum",
                              "sourced": 43, "generated": 3, "empty": 704 } ] } }
```

### `GET /api/admin/review-queue`
Segments awaiting sign-off, high-risk first.

```
?high_risk=true      # the client's Mandatory Human Review categories
?provenance=generated
```

### `POST /api/admin/segments/{id}/review`
```json
{ "reviewed_by": "content-team@example.org", "publishable": true }
```

---

## Notes for the client conversation

1. **Does an existing schema have to be matched?** If so this becomes a
   mapping exercise rather than a design one.
2. **Where should generated content sit?** It is currently `publishable` in
   every segment including the Mandatory Human Review categories, per
   instruction on 2026-08-11. That reverses the recorded "no LLM fallback"
   position and is worth confirming in writing.
3. **Ten of the fourteen segments have provisional field names** — only Course
   Identity, Duration & Mode, Curriculum and Specialisation are reconciled
   against the client's Data Fields sheet. The rest need mapping before
   `field_key` values are stable.
