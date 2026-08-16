# Generation and validation pipeline (steps 2 and 3)

Six grounded Perplexity calls per course, each validated on its own, each retried on its
own, each flagged on its own. Nothing reaches the Laravel POST unless the merged document
passes the full schema and every business rule.

```
taxonomy row ──► injected identity fields
                        │
      ┌─────────────────┴─────────────────┐
      │  per chunk (6x), in order         │
      │  ┌─────────────────────────────┐  │
      │  │ prompt + chunk sub-schema   │  │
      │  │        ▼                    │  │
      │  │ Perplexity Agent API        │◄─┼── transport retry (429/5xx/timeouts)
      │  │        ▼                    │  │
      │  │ chunk validation            │  │
      │  │   pass ──► accept           │  │
      │  │   fail ──► repair prompt ───┼──┼── generation retry (max 3 attempts)
      │  │   fail x3 ─► FLAG           │  │
      │  └─────────────────────────────┘  │
      └─────────────────┬─────────────────┘
                        ▼
             merge + derive + full-document validation
                 pass ──► validated  ──► ready to POST
                 fail ──► retry only the owning chunk (max 2 rounds)
                 fail ──► FLAG for manual review
```

## The six chunks

| Chunk | Top-level properties | Why these travel together |
|---|---|---|
| `profile` | `course_level`, `category`, `subcategory`, `seo`, `hero`, `quick_facts` | Classification and headline facts; everything downstream stays consistent with it |
| `snapshot` | `snapshot`, `overview`, `suitability` | Earnings picture plus the plain-language "what is this and is it for me" |
| `academics` | `eligibility`, `curriculum`, `skills` | Getting in, and what you then study |
| `outcomes` | `careers`, `recruiters`, `further_study_pathway` | Where the degree leads |
| `market` | `fees`, `colleges`, `comparison` | The money and institution picture; the heaviest search load |
| `guidance` | `action_roadmap`, `parent_corner`, `faqs`, `verification` | Closing advice plus the sources backing the rest of the page |

Five properties are **never generated** — `course_id`, `slug`, `course_name`, `currency`,
`region` come from the taxonomy row and config, and are injected. That removes the most
obvious hallucination surface (the model restating the course name differently in each chunk)
and guarantees the currency scope every money rule depends on.

Chunk sub-schemas are **derived from `schema/course.schema.json` at runtime**, never
duplicated. `tests/test_schema_and_chunks.py` asserts the six chunks plus the injected set
cover every required root property exactly once, so adding a section to the root schema
without assigning it to a chunk fails the build rather than silently dropping from output.

Inspect any chunk's schema:

```bash
PYTHONPATH=src python -m coursegen.cli schema --chunk market --provider
```

## Search domains resolve by discipline and chunk

Domains are declared in **`config/domains.json`**, keyed by taxonomy discipline, then by
chunk. `_all` applies to every chunk in that discipline.

```json
{
  "default":   { "_all": ["ugc.gov.in"], "market": ["nirfindia.org"] },
  "engineering": { "_all": ["aicte-india.org"], "market": ["josaa.nic.in"] },
  "medicine-pharmacy": { "_all": ["nmc.org.in", "pci.nic.in"], "market": ["mcc.nic.in"] }
}
```

Pass the discipline per course:

```bash
PYTHONPATH=src python -m coursegen.cli generate "B.Tech Computer Science" --discipline engineering
```

**Resolution is additive, most specific first**, deduped:

| Order | Layer |
|---|---|
| 1 | `<discipline>.<chunk>` |
| 2 | `<discipline>._all` |
| 3 | `default.<chunk>` |
| 4 | `default._all` |
| 5 | `domains=()` on the chunk in `chunks.py` |
| 6 | `SEARCH_DOMAINS` in `.env` |

So engineering's `market` call searches JoSAA first, then AICTE, then NIRF, then UGC — the
discipline-specific regulator outranks the generic one but does not discard it. If the merged
list exceeds Perplexity's 10-domain cap, the **least** specific entries are dropped and a
`chunk.domains_truncated` warning names exactly what was cut. Nothing silently disappears.

Discipline keys are normalised, so `"Medicine & Pharmacy"` from a taxonomy spreadsheet
resolves to `medicine-pharmacy`. An unknown discipline is rejected by `generate` rather than
silently falling back to `default` — a typo in the taxonomy would otherwise cost a whole run
of ungrounded courses.

```bash
PYTHONPATH=src python -m coursegen.cli domains --discipline engineering
```

That prints the resolved list per chunk, which layers contributed, anything dropped over the
cap, and any chunk left with no domains at all.

**Source validation uses the union across every discipline**, not the resolving course's
list — a B.Tech page citing UGC alongside AICTE is correct, and scoping the allowlist to one
discipline would reject it.

## Per-chunk defaults in code

Perplexity's `search_domain_filter` caps at **20 domains per request**. A single global list
would cap the whole course at 20; per-chunk lists give each call its own 20, so the `market`
call can spend all of them on fee and ranking sources while `outcomes` spends its on
labour-market sources.

Each chunk in `src/coursegen/chunks.py` also carries a `domains=()` tuple. It sits below
`config/domains.json` in the cascade and is the right place only for domains that apply to a
chunk across every discipline. For anything taxonomy-specific, use the JSON file.

Entries are **domains, not URLs** — `"nirfindia.org"`, not
`"https://www.nirfindia.org/Rankings/2026/"`. Anything pasted is normalised anyway: scheme,
`www.`, port, path and query are stripped and the result lower-cased and de-duplicated, so a
copied browser URL works. Subdomains are covered automatically (`ugc.gov.in` matches
`info.ugc.gov.in`). A `-` prefix excludes a domain (`"-quora.com"`); excluded domains are
filtered out of the source allowlist rather than being treated as approved publishers.

```bash
PYTHONPATH=src python -m coursegen.cli domains
```

That prints the effective list per chunk, whether it came from the chunk or the fallback, and
flags any chunk over the cap. `generate` refuses to run while a chunk is oversized rather than
letting the provider reject the request mid-course.

**Source validation uses the union, not the per-chunk list.** `verification.sources` is
written by the `guidance` chunk but backs figures from every section, so `source_off_domain`
checks each URL against every domain configured anywhere. Restricting it to the guidance
chunk's own list would reject a perfectly good ranking source cited from `market`.

## Two retry layers, deliberately separate

**Transport retry** (`src/coursegen/retry.py`) wraps the HTTP call only. It retries
connection errors, timeouts, 429 and 5xx with `base * 2^attempt` backoff plus jitter,
honours `Retry-After` as a floor, caps the delay, and logs every attempt as a single JSON
line (`retry.scheduled` / `retry.giving_up`) with operation, attempt, error type, status and
computed delay. Retry count and backoff are configurable via env, not baked in. Auth
errors, 400s and other 4xx are **not** retried — they fail identically every time.

**Generation retry** (`src/coursegen/generate.py`) wraps the whole attempt. A response that
parses but fails validation is not a transport problem, so it never touches the backoff
path. Instead the next attempt gets a repair prompt containing the previous output verbatim
plus the exact validation failures, and is told to fix only what the failures name. Default
3 attempts, `GENERATION_MAX_ATTEMPTS`.

Mixing these two would be the easy mistake: exponential backoff on a model that produced
bad JSON just wastes wall-clock, and feeding a 401 into a repair prompt burns paid attempts
on something no prompt can fix.

**Billed-call risk.** Perplexity charges per request. A connection drop after the request
was already processed server-side means the transport retry pays for the same work twice.
That is an accepted trade-off for unattended batch reliability — the alternative is a run
that dies on one flaky socket halfway through a 500-course taxonomy. It is stated here
rather than in a code comment because this codebase carries no comments. If the client wants
exactly-once billing, the fix is an idempotency key on the provider side, which Perplexity
does not currently offer.

## Validation (step 3)

Two tiers, one report.

**Tier 1 — structural.** JSON Schema draft 2020-12, `additionalProperties: false` at every
level. Catches missing required fields, wrong types, out-of-range numbers, wrong array
lengths, and anything the model invented.

**Tier 2 — business rules** (`src/coursegen/validate/rules.py`), 17 rules covering what a
schema cannot express:

| Area | What it catches |
|---|---|
| Emptiness | whitespace-only strings anywhere in the tree |
| Placeholders | `TODO`, `lorem ipsum`, `example.com`, `[insert` as errors; `demo`, `fictional`, `as an AI` as warnings |
| Ordering | duration min > max, fee min > max, salary lower/typical/higher out of order, degenerate salary range |
| Value ranges | per-currency ceilings on annual fees and salaries |
| Derived consistency | salary marker position matches the salary values |
| Length targets | overview 140-260 words, parent intro 110-220 words |
| Sequences | admission steps 1-5 in order, curriculum years numbered in order, college ranks 1-6 in order with strictly descending scores |
| Course shape | curriculum year count sits inside the course's own stated duration (3-year degree gets 3 tabs, B.Tech 4, B.Arch 5) |
| Rendering preconditions | both `government` and `private` colleges present, or a filter button renders an empty list |
| Cross-field | `comparison[0]` is this course, overview heading names the course |
| Editorial | careers mix direct-entry and regulated routes, no duplicate colleges/careers/recruiters/subjects |
| Grounding | every source is https and inside the configured target domains; warns if all sources share one host |

Each rule declares the paths it needs, so the same rule set runs unchanged against a single
chunk and against the merged document — a rule whose inputs are absent is recorded in
`skipped_rules` rather than firing a false failure. That is what makes chunk-level and
document-level validation the same code path.

Chunk-level validation also sees the context carried forward from earlier chunks, so a
cross-chunk rule fires as soon as both its inputs exist rather than waiting for the merge.
The curriculum-length rule is the clearest case: `quick_facts` comes from `profile` and
`curriculum` from `academics`, and the mismatch is caught on the `academics` retry — one
call — instead of costing a full document round-trip.

The report is machine-readable with a hard pass/fail contract:

```json
{
  "status": "pass",
  "scope": "document",
  "course_id": "crs_bsc_psychology",
  "checked_at": "2026-08-14T10:35:10+00:00",
  "counts": { "errors": 0, "warnings": 5, "skipped_rules": 0 },
  "findings": [{ "code": "...", "path": "colleges.items[2].score", "message": "...", "severity": "error", "source": "schema|rule" }],
  "skipped_rules": []
}
```

**Warnings never block.** Only `errors` gate acceptance.

## Failure policy

Per your call: retry the chunk, then flag.

1. Chunk fails validation → repair prompt with the exact findings → up to `GENERATION_MAX_ATTEMPTS`.
2. Still failing → that chunk is `flagged`, the course is `flagged`, and the run report is
   written to `artifacts/_review/<course_id>.json` with every attempt's findings.
3. Transport failure that survives backoff → chunk flagged immediately without burning
   generation attempts, `transport_error` recorded.
4. Merged document fails a cross-chunk rule → only the chunk owning the failing path is
   regenerated, up to 2 rounds, then flagged.
5. A flagged course is never POSTed. `coursegen generate` exits `2`.

**One deliberate exception to "no auto-correct":** `snapshot.salary.marker_percent` is the
pixel position of a dot on the salary bar, fully determined by the three salary values. It
is stripped from the chunk schema so the model is never asked for it, and computed after
the chunk is accepted. Asking a search model for a value that is pure arithmetic invites a
retry loop over nothing. Every other field follows retry-then-flag. Say the word if you want
it generated and merely checked instead.

## Re-running any step in isolation

Every step writes its inputs and outputs under `artifacts/<course_id>/`:

```
artifacts/crs_bsc_psychology/
  chunks/market.json                 accepted chunk output
  chunks/market.attempt-1.json       raw provider output + citations + usage, per attempt
  course.json                        merged document
  validation.json                    document-level report
  run.json                           per-chunk status, attempts, every finding
```

```bash
PYTHONPATH=src python -m coursegen.cli generate "BSc Psychology" --chunk market
```

```bash
PYTHONPATH=src python -m coursegen.cli merge "BSc Psychology"
```

```bash
PYTHONPATH=src python -m coursegen.cli validate artifacts/crs_bsc_psychology/course.json
```

`pip install -e .` registers a `coursegen` command so the `PYTHONPATH=src` prefix can be
dropped. Exit codes: `0` validated, `1` validation failed, `2` flagged or incomplete,
`3` config error.

`--chunk` regenerates only what you name and reloads the rest from disk, so a single failing
section costs one call, not six. `validate` runs against any saved document with no API key
and no network.

## Tests

```bash
python -m pytest tests/ -q
```

72 tests, no network. The fixture `schema/examples/bsc-psychology.json` is the reference
instance; generation tests drive the pipeline with a fake client that returns slices of it,
so retry counts, repair-prompt contents, flagging, chunk attribution and derived fields are
all asserted without spending a request.

## Open items

- No domains are configured yet — neither the per-chunk `domains` tuples in
  `src/coursegen/chunks.py` nor the `SEARCH_DOMAINS` fallback. Until at least one is set,
  search runs against the open web and the grounding rule downgrades to a
  `grounding_unverified` warning.
- `PERPLEXITY_PRESET` is `fast`. The Agent API also accepts `low`, `medium`, `high` and
  `xhigh`; setting `PERPLEXITY_MODEL` instead overrides the preset entirely. Worth measuring
  per chunk once the pilot establishes a baseline.
- Step 4 (Laravel POST) is not built; it needs the endpoint contract.
