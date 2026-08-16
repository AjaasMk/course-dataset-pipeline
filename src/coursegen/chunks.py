from __future__ import annotations

from dataclasses import dataclass


MAX_SEARCH_DOMAINS_PER_REQUEST = 20


@dataclass(frozen=True)
class Chunk:
    key: str
    title: str
    properties: tuple[str, ...]
    focus: str
    derived_paths: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()


INJECTED_PROPERTIES: tuple[str, ...] = (
    "course_id",
    "slug",
    "course_name",
    "category",
    "currency",
    "region",
)


CHUNKS: tuple[Chunk, ...] = (
    Chunk(
        key="profile",
        title="Course profile, hero and quick facts",
        properties=("course_level", "subcategory", "seo", "hero", "quick_facts"),
        focus=(
            "Classify the course and write the page header. Establish the academic level, the "
            "specific subject the breadcrumb ends on, the search-engine title and description, "
            "the hero "
            "summary aimed jointly at a student and a parent, and the six at-a-glance facts. "
            "Duration and fee figures here must be the mainstream range for this course in the "
            "stated region, not the range for a single institution. "
            "In India the National Education Policy lets most general undergraduate degrees run "
            "either three years or four years (Honours, or Honours with Research), with multiple "
            "entry and exit points and the fourth year usually optional on credit or GPA "
            "conditions. Where both lengths are commonly offered -- BA, B.Sc, B.Com, BBA, BCA and "
            "similar -- you must set min_years 3 and max_years 4, never 3 and 3. Degrees with a "
            "statutory fixed length keep it: B.Arch five years, B.Tech four, LLB three after a "
            "degree or five when integrated, MBBS five and a half including internship."
        ),
        domains=(),
    ),
    Chunk(
        key="snapshot",
        title="Salary snapshot, plain-language overview and suitability",
        properties=("snapshot", "overview", "suitability"),
        focus=(
            "Give the earnings picture, explain what the course actually is in plain language, "
            "and help a student judge whether it suits them. The overview must total roughly 180 "
            "words across its three paragraphs. The suitability section must be honest: the "
            "caution points exist to correct common misconceptions about this course, not to "
            "restate the positives in negative form. "
            "The salary note and data_note tell a family how to read the figures: what moves pay "
            "up or down for this course, and why one number cannot describe every graduate. They "
            "are about the subject, never about how the figures were gathered."
        ),
        derived_paths=("snapshot.salary.marker_percent",),
        domains=(),
    ),
    Chunk(
        key="academics",
        title="Eligibility, admission route, curriculum and skills",
        properties=("eligibility", "curriculum", "skills"),
        focus=(
            "Cover how a student gets in and what they then study. Eligibility must reflect the "
            "stated region's mainstream entry rules. Give one curriculum entry per academic year "
            "the course actually runs, with four subjects in each: three entries for a three-year "
            "degree, four for a four-year degree, five for a five-year integrated or professional "
            "programme. The number of entries must agree with the typical duration already "
            "established for this course. Put specialisation, elective and final project work in "
            "the last year. Where a degree runs three or four years under the National Education "
            "Policy, give the years the mainstream student actually studies and make the count "
            "agree with the duration already set; a four-year Honours route means a fourth year "
            "of advanced or research subjects, not a repeat of year three. "
            "Give one entry for every year the course can run, using the upper end of its stated "
            "duration: a course listed as three to four years gets four entries, and the fourth "
            "holds the Honours, specialisation or research work that year adds. A family reading "
            "three to four years must be able to see what the fourth year contains. "
            "Every subject name across the whole curriculum must be distinct. Do not repeat a "
            "subject in a later year, and do not pad a year by restating an earlier one. Where a "
            "subject genuinely continues, number the stages -- Research Methods I then Research "
            "Methods II -- so each entry names a different unit of study. Before finishing, read "
            "back the full list and replace any repeat."
        ),
        domains=(),
    ),
    Chunk(
        key="outcomes",
        title="Careers, recruiters and further study",
        properties=("careers", "recruiters", "further_study_pathway"),
        focus=(
            "Separate roles reachable directly after the bachelor's degree from roles that are "
            "regulated or need postgraduate study, and set route_badge accordingly. Recruiters "
            "must be real, currently operating organisations that plausibly hire these graduates "
            "in the stated region, named exactly as the organisation names itself."
        ),
        domains=(),
    ),
    Chunk(
        key="market",
        title="Fees, ranked colleges and course comparison",
        properties=("fees", "colleges", "comparison"),
        focus=(
            "Give the money and institution picture. Colleges must be real institutions that "
            "currently offer this course or its close equivalent in the stated region, ranked "
            "in a sensible order, and the six must include at least one government "
            "and at least one private institution. The comparison's first entry is this course "
            "itself; the other two are the courses a family most often weighs against it. "
            "Government and private tuition for the same course often differ by more than twenty "
            "times, so give one fees row per institution_type (government, private, and "
            "premier_national where national institutes apply) rather than one range spanning "
            "both; a range that wide is useless to a family. The at-a-glance annual fee should "
            "describe the mainstream middle of the market, not the extremes. "
            "Every colleges[].annual_fee is tuition for ONE academic year. Sources often quote a "
            "whole-programme total; divide it by the course duration before writing it, and never "
            "put a registration or application charge in that field. A college fee more than twice "
            "the course's stated annual ceiling is almost certainly a programme total. "
            "data_note and footnote explain the subject to a parent: what a ranking does and does "
            "not tell them, what changes year to year, what to verify before applying. They never "
            "mention searching, sources, snippets, or anything you could not find. "
            "A fees row whose cost genuinely varies may set is_variable true and still give a "
            "typical min and max; that is more useful to a family than Varies alone. Give both "
            "figures or neither. "
        ),
        domains=(),
    ),
    Chunk(
        key="guidance",
        title="Action roadmap, parent corner, FAQs and sources",
        properties=("action_roadmap", "parent_corner", "faqs", "verification"),
        focus=(
            "Close the page with what to do next, a parent-facing discussion aid of roughly 150 "
            "words, the questions families actually ask about this course, and the sources that "
            "back the figures used elsewhere on the page. Every source must be a live official "
            "or authoritative URL, not a search results page. Give one source per distinct "
            "publisher page; do not list the same page or the same publisher repeatedly."
        ),
        derived_paths=("verification.last_reviewed",),
        domains=(),
    ),
)


CHUNKS_BY_KEY: dict[str, Chunk] = {chunk.key: chunk for chunk in CHUNKS}


def normalize_domain(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        return ""
    negated = cleaned.startswith("-")
    if negated:
        cleaned = cleaned[1:]
    cleaned = cleaned.split("://", 1)[-1]
    cleaned = cleaned.split("/", 1)[0]
    cleaned = cleaned.split("?", 1)[0]
    cleaned = cleaned.split("@", 1)[-1]
    cleaned = cleaned.split(":", 1)[0]
    cleaned = cleaned.removeprefix("www.")
    return f"-{cleaned}" if negated and cleaned else cleaned


def normalize_domains(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        normalized = normalize_domain(value)
        if normalized and normalized not in seen:
            seen.append(normalized)
    return tuple(seen)


def chunk_owning(property_name: str) -> Chunk | None:
    for chunk in CHUNKS:
        if property_name in chunk.properties:
            return chunk
    return None
