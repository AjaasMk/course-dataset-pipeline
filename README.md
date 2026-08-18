# coursegen

Takes a list of course names and produces a structured record for each one, grounded in
web search and validated before anything ships.

Built for a careers portal that needed pages for a catalogue of 1,000+ Indian
undergraduate courses. Writing those by hand is not realistic; letting a model write them
unchecked is worse. This sits in between.

Input is a course name. Output is a `course.json` matching the client's page template —
27 sections, 97 fields, covering fees, eligibility, curriculum, careers, colleges and
guidance for parents.

## How it works

```
course name
    ↓
6 Perplexity Agent calls        one per section group, each a grounded web search
    ↓                           restricted to sources chosen for that subject
validation                      JSON Schema + 24 rules
    ↓
pass → course.json              ready to publish
fail → review queue             with the full failure history
```

### Why six calls and not one

One call for 97 fields gives a long, shallow answer and no way to retry just the part that
went wrong. Splitting by section means a bad fees section costs one call to redo, not the
whole course. It also lets each section search different sources: a fees lookup for
engineering hits AICTE and JoSAA, while careers hits the National Career Service.

The sub-schemas are derived from the root schema at runtime. There is one schema file, not
seven that drift apart.

### What the model is not allowed to decide

Anything that can be known for certain is injected rather than asked for. `course_id`,
`slug`, `category` and `currency` come from the course list. Course length comes from
`config/durations.json`.

Duration is the interesting one. It carries two separate numbers:

| field | meaning |
|---|---|
| `min_years` / `max_years` | the whole programme a family experiences, internship included |
| `academic_years` | how many taught years the curriculum tabs show |

MBBS is 5.5 years but 4 taught years — the last year is a rotating internship, not a year
of subjects. Before those were split, the year count was derived as `ceil(max_years)`, so
the generator asked for a fifth year that does not exist and the model filled it: B.Ed
repeated year one verbatim, MBBS invented subjects like "Internship Logbook and Viva".

Fixing it in the prompt first took it from 13 occurrences to 12. The instruction was
arguing with the pressure to fill a tab rather than removing the tab. Now
`curriculum.years` is pinned to `minItems == maxItems == academic_years` in the schema sent
to the provider, so the year cannot be emitted at all.

156 of the client's 166 courses resolve to a fixed length. The remaining 10 genuinely vary
between institutions, so they fall back to model generation rather than getting a
confidently wrong number.

### Retries

Two separate layers, because they fail for different reasons:

- **Transport** — 429s, 5xx, timeouts. Exponential backoff with jitter, honours
  `Retry-After`.
- **Generation** — the output was valid JSON but failed a rule. Retried with the previous
  output and the exact findings attached, so the model fixes what broke instead of
  rewriting from scratch.

A section that still fails after its attempts is flagged, never silently shipped.

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
coursegen durations docs/courses.xlsx              # which courses have a fixed length
coursegen domains --discipline engineering         # which sources a subject will search
coursegen pilot docs/courses.xlsx --count 10       # generate a sample and report on it
coursegen generate "B.Tech Civil Engineering"      # one course
coursegen validate artifacts/crs_x/course.json     # re-check a saved document
coursegen retry --revalidate-only                  # re-check the review queue, no API calls
coursegen publish --dry-run                        # what would be sent to Laravel
coursegen publish                                  # POST validated courses
```

`--dry-run` on `pilot` or `retry` shows the plan and the cost before spending anything.

Every step runs on saved inputs. Re-validating or re-publishing does not regenerate, and
`retry --revalidate-only` re-checks the whole review queue without a single API call —
which is what makes changing a rule cheap.

Runs resume. A course already validated is skipped, so an interrupted run continues where
it stopped instead of paying for those courses twice. Flagged courses *are* retried, since
a rule or prompt fix deserves another attempt. `--force` overrides both.

## Docker

```bash
cp .env.example .env
docker compose build
docker compose run --rm coursegen pilot docs/indian_ug_courses_171.xlsx --count 10
```

Generated files land in `./artifacts` on the host. The image runs as a non-root user and
carries no credentials — `.env` is excluded from the build context and mounted at runtime.

See [docs/deployment.md](docs/deployment.md) for Laravel endpoint configuration.

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

Rejected attempts are kept. When a rule fires, the point is to see what the model actually
returned rather than guess at it.

`artifacts/` is gitignored.

## Reviewing output

Open `docs/preview.html` in a browser and drop a `course.json` onto it. It renders the
record using the page template's own stylesheet and runs sanity checks in the sidebar, so
what you review is the page a student would see rather than raw JSON.

## What this does not do

Validation checks structure, ranges and internal consistency. It cannot tell you whether a
fee or a college is **true**. That distinction matters more than anything else here, so it
is stated rather than left for the green tick to imply.

Sections that come back with no citations are recorded in `run.json` under
`unsourced_chunks` — the model answered from memory, and those are the ones worth reading.
`demo/` holds 26 completed courses for exactly that check.

Money is stored as integers in the base currency unit — `250000`, never `"2.5 lakh"`.
Formatting belongs to the template; `preview.html` has a reference implementation.

## Rules that turned out to be wrong

Five of the original rules were wrong, and real data is what proved it:

- A numeric range was required wherever a fee was marked "Varies". 22 courses failed. A
  range alongside "Varies" is more useful than either alone, so the rule was the problem.
- Colleges whose fees looked implausibly low were flagged. AIIMS charges ₹1,628 for MBBS.
  That is real. The floor now scales with institution type, and 18 false flags went to 0.
- College scores were required to descend. It forced the model to fabricate
  `60, 50, 40, 30` for BA English. Scores came out of the schema entirely.
- At least 3 curriculum years were required. B.Ed is 2 and could not be represented.
- A course with no postgraduate route was treated as an error. Plenty of vocational courses
  are legitimately all direct-entry. Downgraded to a warning.

A validation rule is a claim about the world. When real data disagrees with it often
enough, the rule is wrong, not the data.

## Tests

```bash
pytest
```

291 tests, no network required. The ones that earned their place are not unit tests:

- The duration table is regex-matched, and `\b` silently became byte `0x08` twice because
  JSON unescapes it before the regex ever sees it. A test now fails the build on control
  characters or doubled backslashes in that file.
- `preview.html` had two elements sharing an id, so `getElementById` returned the wrong one
  and dropped cards without their grid CSS. The first test harness keyed elements by id in
  a dict, which collapsed the duplicate and passed 41 assertions against a DOM that could
  not reproduce the bug. It now parses the real file.
- A resumed run asserts zero API calls, and a flagged course asserts it is retried rather
  than skipped.

Structured JSON in, structured JSON out, pass/fail contracts throughout — so a run can be
checked by a script instead of read by a person.
