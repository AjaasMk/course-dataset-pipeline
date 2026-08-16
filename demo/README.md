# Course dataset — sample of 26 courses

26 generated course records, one JSON file per course, covering 10 of the 16 categories
in the course list. Every file has passed automated validation.

## Viewing a course

Open **`preview.html`** in a browser and drop any `.json` file onto it (or use the file
picker, or paste the JSON). The page renders the record using the demo template's own
stylesheet, so it shows roughly how a live course page would look.

The sidebar runs sanity checks against whatever you load and lists anything questionable.
Blocks marked **Audit only** are for checking the data and are not part of the public page.

## What is in each file

27 top-level sections matching the course detail template:

| | |
|---|---|
| `seo`, `hero`, `quick_facts` | page header, at-a-glance facts |
| `snapshot`, `overview`, `suitability` | salary picture, plain-language explanation, fit |
| `eligibility`, `curriculum`, `skills` | entry route, year-by-year subjects |
| `careers`, `recruiters`, `further_study_pathway` | where the degree leads |
| `fees`, `colleges`, `comparison` | cost, ranked institutions, similar courses |
| `action_roadmap`, `parent_corner`, `faqs` | guidance for students and parents |
| `verification` | the sources behind the figures |

## Conventions worth knowing

**Money is stored as plain integers** in rupees — `250000`, never `"2.5 lakh"`. Formatting
belongs to the template, which keeps the data checkable and reusable. `preview.html`
contains a reference implementation of the lakh / LPA formatter.

**Duration and curriculum agree.** A course listed as 3–4 years carries four year-tabs,
with the fourth holding the Honours or research year. A two-year course carries two.

**Fees are split by institution type** where government and private differ sharply.
Government medical tuition near ₹1,600 a year alongside private at several lakh is real,
not an error.

**`verification.sources`** lists the pages behind the figures. It is intended for audit
rather than display.

## Please check

The structure is verified automatically; the facts are not. Worth a look:

- fee figures, especially the government/private split
- whether the listed colleges genuinely offer the course
- recruiter names
- salary ranges, which are the least firmly sourced part of the page

Anything wrong here is worth flagging now, before the full set is generated.
