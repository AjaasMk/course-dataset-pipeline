import hashlib
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.institutions.models import Institution

SOURCE_ID = "NIRF"

_NIRF_ID = re.compile(r"^IR-[A-Z0-9\-]+$", re.I)
_NIRF_ID_PARTS = re.compile(r"^IR-([A-Z]+)-([A-Z]+)-(\d+)$", re.I)
_TRAILING_COLUMNS = 4
# The name cell embeds a details/close widget whose text get_text() pulls in.
# Live rows read "Jamia Millia Islamia More Details Close | | TLR (100)", so the
# cut starts at the marker and discards everything after it.
_UI_AFFORDANCE = re.compile(r"\s*more\s+detail(s)?\b.*$", re.I | re.S)


def clean_institution_name(name: str) -> str:
    return _UI_AFFORDANCE.sub("", " ".join(name.split())).strip(" |-")


def institution_key(nirf_id: str) -> str:
    """NIRF ids read IR-<ranking category>-<institution type>-<number>. Only the
    category letter varies for a given institution: IR-A-U-0108, IR-E-U-0108 and
    IR-O-U-0108 are all Jamia Millia Islamia. Keying on the whole id counts one
    institution many times; keying on the number alone collides, because the
    number is scoped by type -- IR-M-S-6 is IIM Sambalpur and IR-C-N-6 is Queen
    Mary's College. Type plus number is the stable identity."""
    found = _NIRF_ID_PARTS.match(nirf_id.strip())
    if found is None:
        return nirf_id.upper()
    institution_type, number = found.group(2).upper(), found.group(3).lstrip("0") or "0"
    return f"{institution_type}-{number}"


def institution_id_for(nirf_id: str) -> str:
    return f"INST-{hashlib.sha256(institution_key(nirf_id).encode()).hexdigest()[:16]}"


def _as_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None


def _as_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except ValueError:
        return None


def extract_institutions(html: str, year: str, category: str) -> list[Institution]:
    soup = BeautifulSoup(html, "html.parser")

    institutions: list[Institution] = []
    seen: set[str] = set()
    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 6 or not _NIRF_ID.match(cells[0]):
            continue

        nirf_id = cells[0]
        if nirf_id in seen:
            continue
        seen.add(nirf_id)

        # Score-breakdown cells sit between the name and the city and vary in
        # number, so location, score and rank are read from the end of the row.
        city, state, score, rank = cells[-_TRAILING_COLUMNS:]
        institutions.append(
            Institution(
                institution_id=institution_id_for(nirf_id),
                canonical_name=clean_institution_name(cells[1]),
                nirf_id=nirf_id,
                city=city,
                state=state,
                nirf_rank=_as_int(rank),
                nirf_score=_as_float(score),
                ranking_year=year,
                ranking_category=category,
                discovered_from_source_id=SOURCE_ID,
            )
        )
    return institutions
