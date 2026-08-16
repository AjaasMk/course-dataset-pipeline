from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

from .report import Finding

RuleFn = Callable[[dict[str, Any], "RuleContext"], Iterator[Finding]]

PROCESS_LEAK_PATTERNS: tuple[str, ...] = (
    r"\bthis conversation\b",
    r"\bsearch results?\b",
    r"\bsource snippets?\b",
    r"\bthe snippets?\b",
    r"\bprovided sources?\b",
    r"\bretrieved for\b",
    r"\bavailable in the results\b",
    r"\bin the results\b",
    r"\bnot consistently (?:published|listed|available)\b",
    r"\bwhere (?:the )?sources? (?:gave|quoted|showed?|listed)\b",
    r"\bcould not be (?:found|determined|verified)\b",
    r"\bbased on (?:the )?(?:search|retrieved|available)\b",
    r"\bpublished sources show\b",
    r"\bfrom the sources?\b",
    r"\baccording to the (?:search|results|snippets)\b",
    r"\bdata (?:was|were) not (?:available|found)\b",
)

CITATION_MARKER_PATTERN = r"\[\d+(?:\s*[,;]\s*\d+)*\]"
CITATION_MARKER_RE = re.compile(CITATION_MARKER_PATTERN)

HARD_PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    r"lorem ipsum",
    r"\btodo\b",
    r"\btbd\b",
    r"\bplaceholder\b",
    r"\bxxx+\b",
    r"\{\{",
    r"example\.com",
    r"\[insert",
    r"\byour (course|text) here\b",
)

SOFT_PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    r"\bdemo\b",
    r"\bfictional\b",
    r"\bsample data\b",
    r"\bas an ai\b",
)

HARD_PLACEHOLDER_RE = re.compile("|".join(HARD_PLACEHOLDER_PATTERNS), re.IGNORECASE)
PROCESS_LEAK_RE = re.compile("|".join(PROCESS_LEAK_PATTERNS), re.IGNORECASE)
SOFT_PLACEHOLDER_RE = re.compile("|".join(SOFT_PLACEHOLDER_PATTERNS), re.IGNORECASE)

CURRENCY_ANNUAL_FEE_CEILING: dict[str, int] = {
    "INR": 5_000_000,
    "USD": 120_000,
    "GBP": 90_000,
    "EUR": 100_000,
    "AED": 400_000,
}

CURRENCY_ANNUAL_SALARY_CEILING: dict[str, int] = {
    "INR": 20_000_000,
    "USD": 500_000,
    "GBP": 400_000,
    "EUR": 450_000,
    "AED": 1_500_000,
}


@dataclass(frozen=True)
class RuleContext:
    currency: str
    allowed_domains: tuple[str, ...]
    search_filtered: bool = True


@dataclass(frozen=True)
class Rule:
    code: str
    requires: tuple[str, ...]
    fn: RuleFn


def get_path(doc: Any, dotted: str) -> Any:
    node = doc
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def has_path(doc: Any, dotted: str) -> bool:
    node = doc
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def _iter_strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def rule_no_blank_strings(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    for path, value in _iter_strings(doc):
        if not value.strip():
            yield Finding("blank_string", path, "value is empty or whitespace only")


def rule_no_placeholder_text(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    for path, value in _iter_strings(doc):
        hard = HARD_PLACEHOLDER_RE.search(value)
        if hard:
            yield Finding(
                "placeholder_text",
                path,
                f"contains placeholder text {hard.group(0)!r}",
            )
            continue
        soft = SOFT_PLACEHOLDER_RE.search(value)
        if soft:
            yield Finding(
                "possible_placeholder_text",
                path,
                f"contains {soft.group(0)!r}, which reads as template filler rather than researched content",
                severity="warning",
            )


def rule_no_process_commentary(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    for path, value in _iter_strings(doc):
        match = PROCESS_LEAK_RE.search(value)
        if match:
            yield Finding(
                "process_commentary",
                path,
                f"reads as commentary on how the page was produced ({match.group(0)!r}); "
                "a student or parent must never see the retrieval process described",
            )


def rule_no_citation_markers(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    for path, value in _iter_strings(doc):
        found = CITATION_MARKER_RE.findall(value)
        if found:
            yield Finding(
                "citation_markers",
                path,
                f"contains {len(found)} bracketed citation marker(s) such as {found[0]!r}; "
                "these are search-tool artefacts and must not appear in page copy",
            )


def rule_college_fee_looks_annual(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    items = get_path(doc, "colleges.items")
    quick = get_path(doc, "quick_facts.indicative_annual_fees")
    duration = get_path(doc, "quick_facts.typical_duration")
    if not isinstance(items, list) or not isinstance(quick, dict):
        return
    annual_max = quick.get("max")
    if not isinstance(annual_max, int) or annual_max <= 0:
        return
    years = (duration or {}).get("max_years") if isinstance(duration, dict) else None
    for index, item in enumerate(items):
        fee = item.get("annual_fee") if isinstance(item, dict) else None
        if not isinstance(fee, int) or fee <= 0:
            continue
        if fee > annual_max * COLLEGE_FEE_UPPER_MULTIPLE:
            hint = ""
            if isinstance(years, (int, float)) and years >= 2:
                divided = round(fee / years)
                if divided <= annual_max * COLLEGE_FEE_UPPER_MULTIPLE:
                    hint = (
                        f"; divided by the {years}-year duration it becomes {divided}, which suggests "
                        "this is the whole-programme fee rather than one year"
                    )
            yield Finding(
                "college_fee_not_annual",
                f"colleges.items[{index}].annual_fee",
                f"{fee} is more than {COLLEGE_FEE_UPPER_MULTIPLE}x the {annual_max} annual ceiling "
                f"stated for this course{hint}",
            )
            continue
        government = (item or {}).get("institution_type") == "government"
        floor = GOVERNMENT_FEE_FLOOR if government else PRIVATE_FEE_FLOOR
        if fee < floor:
            where = "a government institution" if government else "a private institution"
            yield Finding(
                "college_fee_implausibly_low",
                f"colleges.items[{index}].annual_fee",
                f"{fee} per year at {where} is below the {floor} floor and looks like a "
                "registration or application charge rather than tuition",
            )


def rule_duration_ordering(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    duration = get_path(doc, "quick_facts.typical_duration")
    if not isinstance(duration, dict):
        return
    low, high = duration.get("min_years"), duration.get("max_years")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low > high:
        yield Finding(
            "duration_inverted",
            "quick_facts.typical_duration",
            f"min_years {low} is greater than max_years {high}",
        )


def rule_quick_fee_ordering(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    fees = get_path(doc, "quick_facts.indicative_annual_fees")
    if not isinstance(fees, dict):
        return
    low, high = fees.get("min"), fees.get("max")
    if isinstance(low, int) and isinstance(high, int):
        if low > high:
            yield Finding(
                "fee_range_inverted",
                "quick_facts.indicative_annual_fees",
                f"min {low} is greater than max {high}",
            )
        ceiling = CURRENCY_ANNUAL_FEE_CEILING.get(ctx.currency)
        if ceiling and high > ceiling:
            yield Finding(
                "fee_out_of_range",
                "quick_facts.indicative_annual_fees.max",
                f"{high} {ctx.currency} per year exceeds the plausible ceiling of {ceiling}",
            )


def rule_salary_ordering(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    salary = get_path(doc, "snapshot.salary")
    if not isinstance(salary, dict):
        return
    low = salary.get("lower_annual")
    typical = salary.get("typical_annual")
    high = salary.get("higher_annual")
    if not all(isinstance(v, int) for v in (low, typical, high)):
        return
    if not low <= typical <= high:
        yield Finding(
            "salary_not_ordered",
            "snapshot.salary",
            f"expected lower <= typical <= higher, got {low} / {typical} / {high}",
        )
    if low == high:
        yield Finding(
            "salary_range_degenerate",
            "snapshot.salary",
            "lower and higher annual salary are identical, which gives the page no range to show",
        )
    ceiling = CURRENCY_ANNUAL_SALARY_CEILING.get(ctx.currency)
    if ceiling and high > ceiling:
        yield Finding(
            "salary_out_of_range",
            "snapshot.salary.higher_annual",
            f"{high} {ctx.currency} per year exceeds the plausible ceiling of {ceiling}",
        )


def rule_salary_marker_consistent(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    salary = get_path(doc, "snapshot.salary")
    if not isinstance(salary, dict):
        return
    low, typical, high = salary.get("lower_annual"), salary.get("typical_annual"), salary.get("higher_annual")
    marker = salary.get("marker_percent")
    if not all(isinstance(v, int) for v in (low, typical, high, marker)) or high == low:
        return
    expected = round((typical - low) / (high - low) * 100)
    if abs(expected - marker) > 2:
        yield Finding(
            "salary_marker_mismatch",
            "snapshot.salary.marker_percent",
            f"marker {marker} does not match the position implied by the salary values ({expected})",
        )


def rule_overview_length(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    paragraphs = get_path(doc, "overview.paragraphs")
    if not isinstance(paragraphs, list):
        return
    total = sum(word_count(p) for p in paragraphs if isinstance(p, str))
    if not 140 <= total <= 260:
        yield Finding(
            "overview_length",
            "overview.paragraphs",
            f"combined length is {total} words; the template targets about 180 (accepted 140-260)",
        )


def rule_parent_intro_length(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    intro = get_path(doc, "parent_corner.intro")
    if not isinstance(intro, str):
        return
    total = word_count(intro)
    if not 110 <= total <= 220:
        yield Finding(
            "parent_intro_length",
            "parent_corner.intro",
            f"length is {total} words; the template targets about 150 (accepted 110-220)",
        )


def rule_timeline_steps(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    timeline = get_path(doc, "eligibility.admission_timeline")
    if not isinstance(timeline, list):
        return
    steps = [item.get("step") for item in timeline if isinstance(item, dict)]
    if steps != list(range(1, len(timeline) + 1)):
        yield Finding(
            "timeline_steps_not_sequential",
            "eligibility.admission_timeline",
            f"step numbers must run 1..{len(timeline)} in order, got {steps}",
        )


def rule_curriculum_years(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    years = get_path(doc, "curriculum.years")
    if not isinstance(years, list):
        return
    numbers = [item.get("year") for item in years if isinstance(item, dict)]
    if numbers != list(range(1, len(years) + 1)):
        yield Finding(
            "curriculum_years_not_sequential",
            "curriculum.years",
            f"year numbers must run 1..{len(years)} in order, got {numbers}",
        )
    seen: set[str] = set()
    for year_index, year in enumerate(years):
        for subject_index, subject in enumerate(year.get("subjects", []) if isinstance(year, dict) else []):
            name = (subject or {}).get("name", "") if isinstance(subject, dict) else ""
            key = name.strip().casefold()
            if not key:
                continue
            if key in seen:
                yield Finding(
                    "duplicate_subject",
                    f"curriculum.years[{year_index}].subjects[{subject_index}].name",
                    f"subject {name!r} already appears earlier in the curriculum",
                )
            seen.add(key)


def rule_curriculum_length_matches_duration(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    years = get_path(doc, "curriculum.years")
    duration = get_path(doc, "quick_facts.typical_duration")
    if not isinstance(years, list) or not isinstance(duration, dict):
        return
    low, high = duration.get("min_years"), duration.get("max_years")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return
    expected = max(math.floor(low), min(math.ceil(high), MAX_CURRICULUM_YEARS))
    if len(years) != expected:
        detail = (
            f"the course runs up to {high} years, so the page must show all {expected} of them"
            if high > low
            else f"a {high}-year course needs {expected} year tabs"
        )
        yield Finding(
            "curriculum_length_mismatch",
            "curriculum.years",
            f"{len(years)} year(s) of subjects for a course stated as {low}-{high} years; {detail}",
        )


def rule_fee_rows(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    rows = get_path(doc, "fees.rows")
    if not isinstance(rows, list):
        return
    ceiling = CURRENCY_ANNUAL_FEE_CEILING.get(ctx.currency)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        base = f"fees.rows[{index}]"
        low, high, variable = row.get("min"), row.get("max"), row.get("is_variable")
        if variable and low is None and high is None:
            continue
        if variable and (low is None) != (high is None):
            yield Finding(
                "variable_fee_half_range",
                base,
                "a variable row may omit both min and max or give both, never one of the two",
            )
            continue
        if not variable and (low is None or high is None):
            yield Finding(
                "fee_range_missing",
                base,
                "is_variable is false so both min and max must be set",
            )
            continue
        if low > high:
            yield Finding("fee_range_inverted", base, f"min {low} is greater than max {high}")
        if ceiling and high > ceiling:
            yield Finding(
                "fee_out_of_range",
                f"{base}.max",
                f"{high} {ctx.currency} exceeds the plausible ceiling of {ceiling}",
            )


MAX_CURRICULUM_YEARS = 5
COLLEGE_FEE_UPPER_MULTIPLE = 2.0
GOVERNMENT_FEE_FLOOR = 500
PRIVATE_FEE_FLOOR = 5000
MAX_UNSEGMENTED_FEE_SPREAD = 20.0
MAX_QUICK_FEE_SPREAD = 25.0
TUITION_HINT = ("tuition", "course fee", "programme fee", "program fee")


def rule_fee_spread_forces_segmentation(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    rows = get_path(doc, "fees.rows")
    if not isinstance(rows, list):
        return
    typed = {
        row.get("institution_type")
        for row in rows
        if isinstance(row, dict) and row.get("institution_type")
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("is_variable"):
            continue
        if row.get("institution_type"):
            continue
        low, high = row.get("min"), row.get("max")
        if not isinstance(low, int) or not isinstance(high, int) or low < 0 or high <= 0:
            continue
        spread = high / low if low > 0 else float("inf")
        if spread > MAX_UNSEGMENTED_FEE_SPREAD:
            category = str(row.get("category", "")).lower()
            hint = (
                "split this into one row per institution_type (government / private / premier_national)"
                if any(token in category for token in TUITION_HINT)
                else "narrow the range or split it by institution_type"
            )
            magnitude = "an unbounded" if low == 0 else f"a {spread:.0f}x"
            yield Finding(
                "fee_spread_too_wide",
                f"fees.rows[{index}]",
                f"{low}-{high} is {magnitude} spread with no institution_type, which tells a "
                f"family nothing; {hint}",
            )
    if typed and len(typed) < 2:
        yield Finding(
            "fee_segmentation_incomplete",
            "fees.rows",
            f"only {sorted(typed)} is broken out; segmenting tuition is only useful if at least "
            "government and private are both shown",
        )


def rule_quick_fee_spread(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    fees = get_path(doc, "quick_facts.indicative_annual_fees")
    if not isinstance(fees, dict):
        return
    low, high = fees.get("min"), fees.get("max")
    if not isinstance(low, int) or not isinstance(high, int) or low < 0 or high <= 0:
        return
    spread = high / low if low > 0 else float("inf")
    if spread > MAX_QUICK_FEE_SPREAD:
        magnitude = "an unbounded" if low == 0 else f"a {spread:.0f}x"
        yield Finding(
            "quick_fee_spread_too_wide",
            "quick_facts.indicative_annual_fees",
            f"{low}-{high} is {magnitude} spread on the at-a-glance card; quote the mainstream "
            "middle band and leave the extremes to the fees table",
        )


def rule_total_programme_fee_sanity(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    rows = get_path(doc, "fees.rows")
    duration = get_path(doc, "quick_facts.typical_duration")
    if not isinstance(rows, list) or not isinstance(duration, dict):
        return
    years = duration.get("max_years")
    quick = get_path(doc, "quick_facts.indicative_annual_fees")
    if not isinstance(years, (int, float)) or not isinstance(quick, dict):
        return
    annual_max = quick.get("max")
    if not isinstance(annual_max, int) or annual_max <= 0:
        return
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("frequency") != "Total programme":
            continue
        if row.get("institution_type"):
            continue
        high = row.get("max")
        if isinstance(high, int) and high < annual_max:
            yield Finding(
                "total_below_annual",
                f"fees.rows[{index}].max",
                f"{high} is billed as the total for the whole programme yet is below the "
                f"{annual_max} per-year figure on the quick-facts card; one of the two is "
                "reading a per-year source as a total or vice versa",
            )


def rule_college_ranking(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    items = get_path(doc, "colleges.items")
    if not isinstance(items, list) or not items:
        return
    ranks = [item.get("rank") for item in items if isinstance(item, dict)]
    if ranks != list(range(1, len(items) + 1)):
        yield Finding(
            "college_ranks_not_sequential",
            "colleges.items",
            f"ranks must run 1..{len(items)} in order, got {ranks}",
        )
    types = {item.get("institution_type") for item in items if isinstance(item, dict)}
    for missing in ("government", "private"):
        if missing not in types:
            yield Finding(
                "college_type_missing",
                "colleges.items",
                f"no {missing} institution present; the {missing} filter would render an empty list",
            )
    names = [str(item.get("name", "")).strip().casefold() for item in items if isinstance(item, dict)]
    duplicates = {name for name in names if name and names.count(name) > 1}
    for name in sorted(duplicates):
        yield Finding("duplicate_college", "colleges.items", f"institution {name!r} is listed more than once")

    ceiling = CURRENCY_ANNUAL_FEE_CEILING.get(ctx.currency)
    for index, item in enumerate(items):
        fee = item.get("annual_fee") if isinstance(item, dict) else None
        if isinstance(fee, int) and ceiling and fee > ceiling:
            yield Finding(
                "college_fee_out_of_range",
                f"colleges.items[{index}].annual_fee",
                f"{fee} {ctx.currency} per year exceeds the plausible ceiling of {ceiling}",
            )


def rule_comparison_anchor(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    comparison = get_path(doc, "comparison")
    course_name = get_path(doc, "course_name")
    if not isinstance(comparison, list) or not comparison or not isinstance(course_name, str):
        return
    first = comparison[0].get("course_name") if isinstance(comparison[0], dict) else None
    if isinstance(first, str) and first.strip().casefold() != course_name.strip().casefold():
        yield Finding(
            "comparison_anchor_mismatch",
            "comparison[0].course_name",
            f"first comparison column must be this course ({course_name!r}), got {first!r}",
        )
    names = [item.get("course_name", "").strip().casefold() for item in comparison if isinstance(item, dict)]
    if len(set(names)) != len(names):
        yield Finding("comparison_duplicate_course", "comparison", "the same course appears in more than one column")


def rule_career_route_mix(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    careers = get_path(doc, "careers")
    if not isinstance(careers, list) or not careers:
        return
    badges = {item.get("route_badge") for item in careers if isinstance(item, dict)}
    if "Possible after bachelor's" not in badges:
        yield Finding(
            "careers_no_direct_entry",
            "careers",
            "no role is reachable directly after the bachelor's degree; verify that is true for "
            "this course rather than an omission",
            severity="warning",
        )
    if badges <= {"Possible after bachelor's"}:
        yield Finding(
            "careers_no_advanced_route",
            "careers",
            "every role is direct entry; that is plausible for vocational and business courses but "
            "worth a check on regulated subjects",
            severity="warning",
        )
    titles = [str(item.get("title", "")).strip().casefold() for item in careers if isinstance(item, dict)]
    if len(set(titles)) != len(titles):
        yield Finding("duplicate_career", "careers", "the same career title appears more than once")


def rule_recruiter_initials(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    recruiters = get_path(doc, "recruiters")
    if not isinstance(recruiters, list):
        return
    names = [str(item.get("name", "")).strip().casefold() for item in recruiters if isinstance(item, dict)]
    if len(set(names)) != len(names):
        yield Finding("duplicate_recruiter", "recruiters", "the same organisation appears more than once")


def rule_sources_grounded(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    sources = get_path(doc, "verification.sources")
    if not isinstance(sources, list):
        return
    enforce_allowlist = bool(ctx.allowed_domains) and ctx.search_filtered
    if not ctx.allowed_domains:
        yield Finding(
            "grounding_unverified",
            "verification.sources",
            "no search domains configured anywhere, so source domains could not be checked",
            severity="warning",
        )
    elif not ctx.search_filtered:
        yield Finding(
            "sources_unfiltered",
            "verification.sources",
            "this course resolved to no search domains, so it was generated against the open web; "
            "sources cannot be held to the allowlist and were not checked against it",
            severity="warning",
        )
    hosts: list[str] = []
    for index, source in enumerate(sources):
        url = source.get("url") if isinstance(source, dict) else None
        if not isinstance(url, str):
            continue
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        hosts.append(host)
        if parsed.scheme != "https":
            yield Finding("source_not_https", f"verification.sources[{index}].url", f"{url} is not https")
        if enforce_allowlist and not any(
            host == domain or host.endswith(f".{domain}") for domain in ctx.allowed_domains
        ):
            yield Finding(
                "source_off_domain",
                f"verification.sources[{index}].url",
                f"host {host!r} is outside the configured target domains {list(ctx.allowed_domains)}",
            )
    if hosts and len(set(hosts)) == 1 and len(hosts) > 2:
        yield Finding(
            "sources_single_host",
            "verification.sources",
            f"every source points at {hosts[0]!r}; the page's figures rest on one publisher",
            severity="warning",
        )


def rule_course_name_echo(doc: dict[str, Any], ctx: RuleContext) -> Iterator[Finding]:
    course_name = get_path(doc, "course_name")
    heading = get_path(doc, "overview.heading")
    if not isinstance(course_name, str) or not isinstance(heading, str):
        return
    if course_name.strip().casefold() not in heading.strip().casefold():
        yield Finding(
            "overview_heading_missing_course",
            "overview.heading",
            f"heading {heading!r} does not name the course ({course_name!r})",
        )


ALL_RULES: tuple[Rule, ...] = (
    Rule("no_blank_strings", (), rule_no_blank_strings),
    Rule("no_placeholder_text", (), rule_no_placeholder_text),
    Rule("no_process_commentary", (), rule_no_process_commentary),
    Rule("no_citation_markers", (), rule_no_citation_markers),
    Rule(
        "college_fee_looks_annual",
        ("colleges", "quick_facts"),
        rule_college_fee_looks_annual,
    ),
    Rule("duration_ordering", ("quick_facts",), rule_duration_ordering),
    Rule("quick_fee_ordering", ("quick_facts",), rule_quick_fee_ordering),
    Rule("salary_ordering", ("snapshot",), rule_salary_ordering),
    Rule("salary_marker_consistent", ("snapshot",), rule_salary_marker_consistent),
    Rule("overview_length", ("overview",), rule_overview_length),
    Rule("parent_intro_length", ("parent_corner",), rule_parent_intro_length),
    Rule("timeline_steps", ("eligibility",), rule_timeline_steps),
    Rule("curriculum_years", ("curriculum",), rule_curriculum_years),
    Rule(
        "curriculum_length_matches_duration",
        ("curriculum", "quick_facts"),
        rule_curriculum_length_matches_duration,
    ),
    Rule("fee_rows", ("fees",), rule_fee_rows),
    Rule("fee_spread_forces_segmentation", ("fees",), rule_fee_spread_forces_segmentation),
    Rule("quick_fee_spread", ("quick_facts",), rule_quick_fee_spread),
    Rule("total_programme_fee_sanity", ("fees", "quick_facts"), rule_total_programme_fee_sanity),
    Rule("college_ranking", ("colleges",), rule_college_ranking),
    Rule("comparison_anchor", ("comparison", "course_name"), rule_comparison_anchor),
    Rule("career_route_mix", ("careers",), rule_career_route_mix),
    Rule("recruiter_initials", ("recruiters",), rule_recruiter_initials),
    Rule("sources_grounded", ("verification",), rule_sources_grounded),
    Rule("course_name_echo", ("overview", "course_name"), rule_course_name_echo),
)
