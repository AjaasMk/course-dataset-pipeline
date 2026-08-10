import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel

from src.extract.readers import read_pdf
from src.institutions import store
from src.institutions.models import RankedProfile
from src.retrieve.base import fetch_and_store
from src.retrieve.models import DiscoveredDocument, MatchType, SourceTier

PROFILE_URL = "https://www.nirfindia.org/nirfpdfcdn/{year}/pdf/{category}/{nirf_id}.pdf"
DEFAULT_RANKING_YEAR = "2025"

ProgrammeLevel = Literal["UG", "PG"]


class PlacementRecord(BaseModel):
    programme_level: ProgrammeLevel
    academic_year: str
    students_graduating: Optional[int] = None
    students_placed: Optional[int] = None
    median_salary_rupees: Optional[int] = None
    students_higher_studies: Optional[int] = None


class IntakeRecord(BaseModel):
    programme_level: ProgrammeLevel
    academic_year: str
    sanctioned_intake: int


def profile_url(nirf_id: str, category: str, year: str) -> str:
    return PROFILE_URL.format(year=year, category=category, nirf_id=nirf_id)


def profile_targets(profiles: Iterable[RankedProfile]) -> list[DiscoveredDocument]:
    """One downloadable profile per (institution, ranking category).

    NIRF publishes a separate profile PDF per category an institution is
    ranked in, and the category directory genuinely selects between them --
    verified live that /University/IR-O-U-0222.pdf and /Overall/IR-O-U-0222.pdf
    return different documents for the same institution, while a nonsense
    category 404s. So two rows sharing an institution are two real documents,
    not a duplicate to collapse.

    Takes RankedProfile (from institution_rankings) rather than Institution:
    the institutions table is merged down to one ranking_category per
    institution, so building URLs from it pairs a nirf_id with whichever
    category survived the merge and loses every other profile that
    institution has.
    """
    targets: list[DiscoveredDocument] = []
    for profile in profiles:
        if not profile.nirf_id or not profile.ranking_category:
            continue
        year = profile.ranking_year or DEFAULT_RANKING_YEAR
        targets.append(
            DiscoveredDocument(
                document_url=profile_url(profile.nirf_id, profile.ranking_category, year),
                document_title=(
                    f"NIRF {year} {profile.ranking_category} profile — "
                    f"{profile.canonical_name}"
                ),
                match_confidence=1.0,
                match_type=MatchType.EXACT,
                academic_year=year,
            )
        )
    return targets


_LEVEL_HEADER = re.compile(r"^(UG|PG)\s*\[", re.I)
_ACADEMIC_YEAR = re.compile(r"\b(\d{4}-\d{2})\b")
_ROW_START = re.compile(r"^\d{4}-\d{2}\s")

# The salary cell is the one unambiguous landmark in a placement row: an
# integer immediately followed by that same number spelled out in brackets
# ("696000(Six Lakh Ninety Six Thousand)", "0(Zero)"). Anchoring on it lets one
# parser read both real table shapes -- UG carries an extra academic-year and
# lateral-entry pair that PG does not, so fixed column offsets would read the
# wrong values for one of them.
_SALARY_ANCHOR = re.compile(r"(\d+)\s+(\d+)\([^)]*\)\s+(\d+)\s*$")

# A row can legitimately span several lines (see _accumulate below) but not
# many. Without a cap, one malformed row would swallow the rest of the
# document looking for an anchor that never arrives.
_MAX_ROW_LINES = 8


def _level_of(line: str) -> Optional[ProgrammeLevel]:
    found = _LEVEL_HEADER.match(line.strip())
    return found.group(1).upper() if found else None  # type: ignore[return-value]


def _record_from(level: ProgrammeLevel, row: str) -> Optional[PlacementRecord]:
    anchored = _SALARY_ANCHOR.search(row)
    if anchored is None:
        return None
    years = _ACADEMIC_YEAR.findall(row)
    if not years:
        return None

    placed, salary, higher = (int(g) for g in anchored.groups())
    leading = row[: anchored.start()].split()
    return PlacementRecord(
        programme_level=level,
        # The cohort year is the last academic year on the row: the earlier
        # ones label the intake and lateral-entry columns, which describe
        # different cohorts entirely.
        academic_year=years[-1],
        students_graduating=int(leading[-1]) if leading and leading[-1].isdigit() else None,
        students_placed=placed,
        median_salary_rupees=salary,
        students_higher_studies=higher,
    )


def parse_placements(text: str) -> list[PlacementRecord]:
    """Read the placement/higher-studies tables out of a NIRF profile PDF.

    A data row does NOT occupy one line. The salary cell spells its own value
    out in brackets and pypdf breaks that over as many lines as it needs,
    leaving the trailing higher-studies count on a line of its own -- verified
    against the live IR-G-U-0101 profile, where 996336 wraps over four lines.

    A row is emitted the moment it satisfies the salary anchor, rather than
    when the next row begins. That matters for the last row of a table: the
    next section heading ("Ph.D Student Details") follows it with no blank
    line, so accumulating until the next row-start swallows the heading and
    loses the row -- which is exactly how the real 696000 salary went missing.
    """
    records: list[PlacementRecord] = []
    level: Optional[ProgrammeLevel] = None
    buffer: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        header_level = _level_of(stripped)
        if header_level is not None:
            level, buffer = header_level, []
            continue
        if level is None:
            continue

        if _ROW_START.match(stripped):
            buffer = [stripped]
        elif buffer:
            buffer.append(stripped)
        else:
            continue

        if len(buffer) > _MAX_ROW_LINES:
            buffer = []
            continue

        found = _record_from(level, " ".join(buffer))
        if found is not None:
            records.append(found)
            buffer = []

    return records


_INTAKE_YEARS = re.compile(r"^Academic Year\s+((?:\d{4}-\d{2}\s*)+)$", re.I)


def parse_intake(text: str) -> list[IntakeRecord]:
    records: list[IntakeRecord] = []
    years: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        header = _INTAKE_YEARS.match(stripped)
        if header is not None:
            years = header.group(1).split()
            continue

        level = _level_of(stripped)
        if level is None or not years:
            continue

        cells = stripped[stripped.find("]") + 1 :].split()
        for year, cell in zip(years, cells):
            # "-" means the institution reported nothing for that year.
            # Reading it as 0 would assert they sanctioned zero seats, a
            # different and false claim -- so it is omitted, while a real
            # reported 0 is kept.
            if cell.isdigit():
                records.append(
                    IntakeRecord(
                        programme_level=level, academic_year=year, sanctioned_intake=int(cell)
                    )
                )
    return records


RAW_DIR = Path("data/raw")
SOURCE_ID = "NIRF"
DEFAULT_MAX_WORKERS = 6


class ProfileFetchResult(BaseModel):
    nirf_id: str
    ranking_category: str
    outcome: Literal["fetched", "failed"]
    document_id: Optional[str] = None
    placements: int = 0
    intakes: int = 0
    error: Optional[str] = None


def _fetch_one(
    profile: RankedProfile, target: DiscoveredDocument, raw_dir: Path
) -> ProfileFetchResult:
    try:
        record = fetch_and_store(
            target,
            source_id=SOURCE_ID,
            source_tier=SourceTier.A,
            raw_dir=raw_dir,
            extension="pdf",
        )
        text = "\n".join(page.text for page in read_pdf(Path(record.local_path)))
        return ProfileFetchResult(
            nirf_id=profile.nirf_id,
            ranking_category=profile.ranking_category,
            outcome="fetched",
            document_id=record.document_id,
            placements=len(parse_placements(text)),
            intakes=len(parse_intake(text)),
        )
    except Exception as exc:
        return ProfileFetchResult(
            nirf_id=profile.nirf_id,
            ranking_category=profile.ranking_category,
            outcome="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


def fetch_all_profiles(
    profiles: Optional[list[RankedProfile]] = None,
    raw_dir: Path = RAW_DIR,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[ProfileFetchResult]:
    """Download every NIRF profile PDF and report what parsed out of each.

    Each download is independent, so one institution's failure is isolated the
    same way retrieve/batch.py and extract/run_chunking.py isolate theirs --
    a single 404 must not abort 870 other fetches. fetch_and_store() already
    skips a URL it has seen, so re-running this is cheap and idempotent.
    """
    profiles = profiles if profiles is not None else store.all_ranked_profiles()
    targets = profile_targets(profiles)

    results: list[ProfileFetchResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_fetch_one, profile, target, raw_dir)
            for profile, target in zip(profiles, targets)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results
