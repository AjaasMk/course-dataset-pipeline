# coursegen

Generates a structured course-detail record for every course in a list, grounded in web
search, validated before anything ships.

Input is a course name. Output is a `course.json` matching the client's page template —
27 sections covering fees, eligibility, curriculum, careers, colleges and guidance.

## How it works

```
course name
    ↓
6 Perplexity Agent calls          one per section group, each a grounded web search
    ↓                             restricted to domains chosen per subject
validation                        JSON Schema + 25 business rules
    ↓
pass → course.json                ready to publish
fail → review queue               with the full failure history
```

Search domains resolve per discipline and per section, so a fees lookup for engineering
searches AICTE and JoSAA while careers searches the National Career Service.

## Setup

```bash
pip install -e .
cp .env.example .env
```

Put your Perplexity key in `.env`. Nothing else needs changing to start.

## Commands

```bash
coursegen smoke                                    # one cheap call, checks the wiring
coursegen courses docs/courses.xlsx                # what is in the course list
coursegen pilot docs/courses.xlsx --count 10       # generate a sample and report on it
coursegen generate "B.Tech Civil Engineering"      # one course
coursegen validate artifacts/crs_x/course.json     # re-check a saved document
coursegen retry --revalidate-only                  # re-check the review queue, no API calls
coursegen domains --discipline engineering         # which sources a subject will search
```

Add `--dry-run` to `pilot` or `retry` to see the plan and cost before spending anything.

## Output

```
artifacts/
  crs_mbbs/
    course.json        the deliverable
    run.json           per-section status, citations, cost, every finding
    chunks/            each section, including rejected attempts
  _review/             courses that failed validation
  pilot-report.json    flag rate, cost, most common failures
```

`artifacts/` is gitignored.

## Reviewing output

Open `docs/preview.html` in a browser and drop a `course.json` onto it. It renders the
record using the page template's own stylesheet and runs sanity checks in the sidebar.

## Notes

Money is stored as integers in the base currency unit — `250000`, not `"2.5 lakh"`.
Formatting belongs to the template; `preview.html` has a reference implementation.

Validation catches structure, ranges and internal consistency. It cannot tell you whether
a fee or a college is *true*. Sections that come back with no citations are recorded in
`run.json` under `unsourced_chunks` — those are the ones worth reading.

## Tests

```bash
pytest
```

No network required.
