# WikipediaAdapter — Design

Date: 2026-07-18
Status: Approved

## Context

The 50-course pilot batch run (prior session) confirmed 17 real `no_source_found`
courses. Five of them — Marketing, Accounting, Cybersecurity, Software
Engineering, Marine Engineering — were spot-checked and confirmed as genuine
Careers360 catalog gaps, not matching bugs (best Careers360 candidates scored
0.50–0.79, well below the 0.80 threshold, and were semantically wrong —
"Banking" for "Marketing," generic "...Engineering" token overlap for
"Software Engineering"). `general_background` (Wikipedia) is already wired
into `retrieval_order` for `medium_tier`/`weak_tier` as a no-op fallback (no
adapter registered). This spec builds that adapter.

**Explicitly rejected as an alternative** (discussed and ruled out this
session): using an LLM's own knowledge (Claude/ChatGPT/Perplexity-as-oracle)
to fill these gaps. This would violate Hard Constraint 2 (`source_refs` must
point to a real retrieved document) and Hard Constraint 4 (no fabrication) —
an LLM's answer with no retrieved document behind it is a plausible-sounding
guess by definition, regardless of accuracy. A `WikipediaAdapter` is
different: it retrieves and stores a real, citable, attributable (CC BY-SA)
document, same as every other adapter.

## Architectural deviation: no pre-crawlable listing page

Unlike AICTE/Careers360, Wikipedia has no single page listing "all courses."
`build_indices()`'s "build once per run, reuse across courses" model doesn't
apply here — there's nothing to build. Confirmed via testing:

```
GET https://en.wikipedia.org/w/rest.php/v1/search/page?q={course_name}&limit=5
```

is a free, no-auth-required, real-time search API returning
`{"pages": [{"key": ..., "title": ..., "excerpt": ...}, ...]}` — empty
`pages` list when nothing matches (verified with a nonsense query). This
adapter does live search per course instead of matching against a pre-built
index.

- `build_index() -> dict[str, str]` returns `{}` — always empty, nothing to
  crawl. Conforms to `SourceAdapter`'s type signature but not its documented
  behavior ("returns candidates from a crawled listing page") — this is a
  legitimate per-adapter deviation, documented in the adapter's own
  docstring, not a `SourceAdapter` Protocol change.
- `match(course_name, index)` ignores `index` entirely (always `{}`) and
  makes a live HTTP call instead. Returns `None` only when the search API
  itself returns zero `pages` — not when "index is empty" in the sense
  `SourceAdapter`'s docstring describes for other adapters.
- `build_indices()` (existing, `orchestrator.py`) still works unmodified —
  calling `WikipediaAdapter().build_index()` once per run just returns `{}`
  cheaply; the real work happens inside `match()`, one live call per course
  that reaches this source in `retrieval_order`.

## Confidence scoring: title + excerpt, not title alone

Scoring only the returned title against the query (the technique every
other adapter uses) fails a real case: Wikipedia's search correctly ranks
**"Computer security"** as the top result for the query `"Cybersecurity"` —
but `token_set_ratio("Cybersecurity", "Computer security")` = 73.3, below
the 0.80 threshold, because the *title* uses different wording than the
query even though the *content* is exactly right.

Verified fix: Wikipedia's search API returns an `excerpt` field with
`<span class="searchmatch">` highlighting the terms that actually matched
in the full-text search. For the Cybersecurity query, the excerpt literally
contains `<span class="searchmatch">Cybersecurity</span>` three times —
`token_set_ratio("Cybersecurity", excerpt_stripped_of_html)` = 100. This is
genuine evidence from Wikipedia's own full-text search, not a scoring hack —
the article's body demonstrably discusses "Cybersecurity" even though its
canonical title is "Computer security."

**Scoring approach**: for each of up to 5 candidates returned by the search
API, compute `max(token_set_ratio(query, title), token_set_ratio(query,
excerpt_with_html_stripped))`, keep the highest-scoring candidate as the
match. This makes the adapter's own scoring — not Wikipedia's external rank
— the authoritative selector, consistent with how `AICTEAdapter`/
`Careers360Adapter` already select the best candidate from their own index
rather than trusting an external order.

**Explicit, considered rejection**: a per-source-category threshold
(`retrieve_course()`'s `threshold` becoming `dict[SourceCategory, float]`)
was considered and rejected — it would touch the already-reviewed, shipped
core function and its existing test suite from the orchestration feature.
The excerpt-based scoring achieves the practical goal (Wikipedia can clear
the *same* global 0.80 threshold more often on genuinely relevant matches)
without changing `retrieve_course()`, its signature, or the meaning of
`matching.threshold` anywhere else.

**Accepted, undecided-either-way limitation**: this scoring change does not
guarantee every semantic-but-not-lexical case resolves — it's evidence-based
improvement, not a guarantee. If a course's Wikipedia article doesn't
happen to mention the query term in its top-5-search excerpt either, it
still won't clear threshold, which is the correct, honest outcome (no
fabricated match), not a bug.

## `download()`: raw article HTML

Consistent with `Careers360Adapter`: `requests.get()` the article's normal
URL (`https://en.wikipedia.org/wiki/{key}`, where `key` is the search
result's `key` field — already a valid URL path segment, e.g.
`"Computer_security"`), save the full rendered HTML as-is. Stage 1 fetches
and stores; Stage 2 parses — this keeps the same boundary every other
adapter already respects, rather than introducing a differently-shaped
artifact (a clean-text extract via Wikipedia's separate extract API) that
only this one adapter would produce.

## Schema change: `SourceType.GENERAL_BACKGROUND_WEBPAGE`

None of the existing `SourceType` values (`REGULATOR_PDF`, `REGULATOR_WEBPAGE`,
`AGGREGATOR_WEBPAGE`, `UNIVERSITY_WEBPAGE`, `NONE`) describe a Wikipedia
article — same gap that required adding `AGGREGATOR_WEBPAGE` for Careers360.
Add `GENERAL_BACKGROUND_WEBPAGE` to `src/schema.py`'s `SourceType` enum.

`src/retrieve/batch.py`'s `infer_source_category()` (built in the prior
session, with a documented "1:1 mapping holds for today's adapters, revisit
if it stops holding" limitation) gains:
```python
SourceType.GENERAL_BACKGROUND_WEBPAGE: "general_background",
```
in its `_SOURCE_TYPE_TO_CATEGORY` mapping — without this, every Wikipedia
match would report as `"unknown"` in the tier-stratified report, silently
breaking Hard Constraint 6's stratification for exactly the source this
adapter exists to add visibility into.

## Registry

`SourceCategory.GENERAL_BACKGROUND: {"*": WikipediaAdapter()}` — wildcard
key, same pattern as `Careers360Adapter`, since Wikipedia applies uniformly
across every category, not one specific regulator-style category.

## Config fix required: `strong_tier` is missing `general_background`

Discovered checking the actual config while writing this spec:
`retrieval_order.strong_tier` (engineering + medicine) is currently
`[fact_supplement_independent_writing_required, regulatory_primary,
syllabus_supplement]` — **no `general_background` entry at all**. Only
`medium_tier` and `weak_tier` have it. Three of the five confirmed target
gaps (Marine Engineering, Cybersecurity, Software Engineering) are
`category="engineering"`, `tier_group="strong_tier"` — without this fix,
`WikipediaAdapter` would never even be *attempted* for them, silently
defeating the reason this adapter is being built.

`config/sources.yaml`'s `strong_tier` entry gains `general_background` as
its final fallback, same position as it already occupies in `medium_tier`:
```yaml
strong_tier: # Engineering, Medicine
  - fact_supplement_independent_writing_required
  - regulatory_primary
  - syllabus_supplement
  - general_background
```

## Error handling

Same as every other adapter: an HTTP failure (search API or article
download) propagates, no manifest row written for a failed attempt — no new
handling introduced. `run_batch()`'s existing per-course try/except (prior
session) already catches this at the batch level.

## Testing

- `tests/test_wikipedia.py` — mock `requests.get` for both the search API
  call (inside `match()`) and the article download call (inside
  `download()`) — this adapter's `match()` makes an HTTP call, unlike
  AICTE/Careers360 whose `match()` is pure local computation against a
  pre-built index, so tests need to mock both call sites, not just one.
  - `match()` returns the highest-scoring candidate among multiple mocked
    search results (verifies the "score all 5, pick best" logic, not just
    "accept whatever's first").
  - A candidate whose title scores low but excerpt scores high is selected
    over a candidate with a higher title-only score but lower excerpt score
    (the concrete regression test for the Cybersecurity-shaped case).
  - Empty `pages` list from the search API → `match()` returns `None`.
  - `download()` — same idempotency/hash/manifest pattern already proven
    for the other two adapters (existing `manifest.py`, unchanged).
- Live smoke test (`__main__` block, not part of the automated suite):
  build_index (trivial), then `match()`+`download()` against the real
  Wikipedia API for the specific confirmed gap courses (Marketing,
  Accounting, Cybersecurity, Software Engineering, Marine Engineering) —
  chosen deliberately because these are the courses this adapter is meant
  to close, not the generic 5-engineering-course smoke test used for AICTE/
  Careers360.
- Final validation: re-run the full 50-course pilot batch
  (`python -m src.retrieve.batch`) with `WikipediaAdapter` registered, and
  compare the new tier-stratified counts against the prior run's 33
  matched / 17 no_source_found baseline.
