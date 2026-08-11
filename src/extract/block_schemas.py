"""Output shapes for the client page's advisory blocks.

These five blocks are rendered on every course page and have no atomic fact
behind them anywhere in the source directory -- no regulator publishes a
parent's question list. Item counts and field names come from the client's own
template, measured, not chosen here; see docs/specs/page-block-map.json.
"""

ADVISORY_BLOCK_SCHEMAS: dict[str, dict] = {
    "hero.fit_panel": {
        "fit_statements": "list of exactly 3 short statements describing the kind of "
        "student this course suits, each under 8 words",
    },
    "fit": {
        "enjoy_if": "list of exactly 4 statements completing 'You may enjoy this course "
        "if you...'",
        "think_carefully_if": "list of exactly 4 statements completing 'Think carefully "
        "if you...', naming real misconceptions about this course",
        "tags": "list of exactly 7 one-or-two-word interest and aptitude tags",
    },
    "what_now": {
        "grades_8_10": "string, what a student in Grades 8-10 should do now, 1-2 sentences",
        "grade_11": "string, what a student in Grade 11 should do now, 1-2 sentences",
        "grade_12": "string, what a student in Grade 12 should do now, 1-2 sentences",
    },
    "parent_corner": {
        "intro": "string of about 150 words addressed to a parent, on how to support "
        "the decision without making it for the student",
        "questions": "list of exactly 6 questions a parent should discuss with the student",
    },
    "compare": {
        "comparison_courses": "list of exactly 2 course names to compare against "
        "this one -- the closest real alternatives a student would actually weigh, "
        "chosen from the sibling courses supplied in the prompt",
        "rows": "list of exactly 4 objects, each {feature, this_course, alternative_1, "
        "alternative_2}. feature is one of: Main focus, Statistics, Laboratory "
        "exposure, Common next steps. Each value is a short phrase, not a sentence",
    },
    "faq": {
        "faqs": "list of 6 to 10 objects, each {question, answer}. Answers 2-4 sentences. "
        "Cover stream eligibility, whether further study is needed for professional "
        "roles, how this course differs from its closest alternative, and what the "
        "course is commonly mistaken for",
    },
}

# Not advisory: computed from facts already held, so they are never generated.
#
# compare is deliberately NOT here. Its inputs are derived -- the sibling
# courses come from the taxonomy, not from a model -- but the comparison rows
# themselves ("Statistics: moderate vs low to moderate") are a judgement about
# three courses that no regulator publishes. Treating it as derived would mean
# inventing a rule to compute those cells; treating it as advisory says plainly
# that they are written, and marks them generated on the page.
DERIVED_BLOCKS = frozenset({"breadcrumbs", "page_verification"})


def schema_for_block(block: str) -> dict:
    if block in DERIVED_BLOCKS:
        raise KeyError(
            f"{block!r} is a derived block -- it is computed from facts already "
            f"held, not generated. Generating it would invent data that exists."
        )
    return ADVISORY_BLOCK_SCHEMAS[block]
