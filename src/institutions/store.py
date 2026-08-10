import sqlite3
from pathlib import Path
from typing import Optional

from src.institutions.models import (
    Institution,
    InstitutionAlias,
    InstitutionCourseOffering,
    RankedProfile,
)

DEFAULT_DB_PATH = Path("data/institutions.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS institutions (
    institution_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    aishe_code TEXT,
    nirf_id TEXT,
    institution_type TEXT,
    ownership_type TEXT,
    city TEXT,
    state TEXT,
    nirf_rank INTEGER,
    nirf_score REAL,
    ranking_year TEXT,
    ranking_category TEXT,
    discovered_from_source_id TEXT NOT NULL,
    official_url TEXT
);

CREATE TABLE IF NOT EXISTS institution_rankings (
    institution_id TEXT NOT NULL,
    ranking_body TEXT NOT NULL,
    ranking_category TEXT NOT NULL,
    ranking_year TEXT NOT NULL,
    nirf_id TEXT,
    rank INTEGER,
    score REAL,
    PRIMARY KEY (institution_id, ranking_body, ranking_category, ranking_year)
);

CREATE TABLE IF NOT EXISTS institution_aliases (
    institution_id TEXT NOT NULL,
    observed_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (institution_id, observed_name, source_id)
);

CREATE TABLE IF NOT EXISTS institution_course_offerings (
    institution_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    official_course_url TEXT,
    discovered_from_source_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (institution_id, course_id)
);
"""

_COLUMNS = (
    "institution_id, canonical_name, aishe_code, nirf_id, institution_type, "
    "ownership_type, city, state, nirf_rank, nirf_score, ranking_year, "
    "ranking_category, discovered_from_source_id, official_url"
)

# Columns a later sighting may fill in, but must never blank: one source knowing
# an AISHE code and another not knowing it is not evidence the code is wrong.
_PRESERVED = (
    "aishe_code",
    "nirf_id",
    "institution_type",
    "ownership_type",
    "city",
    "state",
    "official_url",
)


def _prefixed(columns: str, alias: str) -> str:
    return ", ".join(f"{alias}.{c.strip()}" for c in columns.split(","))


def _connect(db_path: Optional[Path]) -> sqlite3.Connection:
    resolved = db_path if db_path is not None else DEFAULT_DB_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.executescript(_CREATE)
    conn.commit()
    return conn


def _row_to_institution(row: tuple) -> Institution:
    return Institution(
        institution_id=row[0],
        canonical_name=row[1],
        aishe_code=row[2],
        nirf_id=row[3],
        institution_type=row[4],
        ownership_type=row[5],
        city=row[6],
        state=row[7],
        nirf_rank=row[8],
        nirf_score=row[9],
        ranking_year=row[10],
        ranking_category=row[11],
        discovered_from_source_id=row[12],
        official_url=row[13],
    )


def get_institution(institution_id: str, db_path: Optional[Path] = None) -> Optional[Institution]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM institutions WHERE institution_id = ?", (institution_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _row_to_institution(row)


def upsert_institution(institution: Institution, db_path: Optional[Path] = None) -> None:
    existing = get_institution(institution.institution_id, db_path)
    merged = institution
    if existing is not None:
        fill = {
            field: getattr(existing, field)
            for field in _PRESERVED
            if getattr(institution, field) is None and getattr(existing, field) is not None
        }
        merged = institution.model_copy(update=fill) if fill else institution

    conn = _connect(db_path)
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO institutions ({_COLUMNS}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                merged.institution_id,
                merged.canonical_name,
                merged.aishe_code,
                merged.nirf_id,
                merged.institution_type,
                merged.ownership_type,
                merged.city,
                merged.state,
                merged.nirf_rank,
                merged.nirf_score,
                merged.ranking_year,
                merged.ranking_category,
                merged.discovered_from_source_id,
                merged.official_url,
            ),
        )
        # An institution ranked in several categories has several ranks; keeping
        # them on the institution row lets the last crawl overwrite the rest.
        if merged.ranking_category and merged.ranking_year:
            conn.execute(
                "INSERT OR REPLACE INTO institution_rankings "
                "(institution_id, ranking_body, ranking_category, ranking_year, nirf_id, rank, score) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    merged.institution_id,
                    merged.discovered_from_source_id,
                    merged.ranking_category,
                    merged.ranking_year,
                    merged.nirf_id,
                    merged.nirf_rank,
                    merged.nirf_score,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def count_institutions(db_path: Optional[Path] = None) -> int:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
    finally:
        conn.close()


def add_alias(alias: InstitutionAlias, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO institution_aliases "
            "(institution_id, observed_name, source_id, confidence) VALUES (?,?,?,?)",
            (alias.institution_id, alias.observed_name, alias.source_id, alias.confidence),
        )
        conn.commit()
    finally:
        conn.close()


def aliases_for(institution_id: str, db_path: Optional[Path] = None) -> list[InstitutionAlias]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT institution_id, observed_name, source_id, confidence "
            "FROM institution_aliases WHERE institution_id = ? ORDER BY observed_name",
            (institution_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        InstitutionAlias(
            institution_id=r[0], observed_name=r[1], source_id=r[2], confidence=r[3]
        )
        for r in rows
    ]


def add_offering(offering: InstitutionCourseOffering, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO institution_course_offerings "
            "(institution_id, course_id, official_course_url, discovered_from_source_id, confidence) "
            "VALUES (?,?,?,?,?)",
            (
                offering.institution_id,
                offering.course_id,
                offering.official_course_url,
                offering.discovered_from_source_id,
                offering.confidence,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def institutions_offering(course_id: str, db_path: Optional[Path] = None) -> list[Institution]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM institutions WHERE institution_id IN "
            "(SELECT institution_id FROM institution_course_offerings WHERE course_id = ?) "
            "ORDER BY institution_id",
            (course_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_institution(row) for row in rows]


def top_ranked(
    category: str, year: str, limit: int, db_path: Optional[Path] = None
) -> list[Institution]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_prefixed(_COLUMNS, 'i')}, r.rank, r.score, r.nirf_id FROM institutions i "
            "JOIN institution_rankings r ON r.institution_id = i.institution_id "
            "WHERE r.ranking_category = ? AND r.ranking_year = ? AND r.rank IS NOT NULL "
            "ORDER BY r.rank LIMIT ?",
            (category, year, limit),
        ).fetchall()
    finally:
        conn.close()

    ranked: list[Institution] = []
    for row in rows:
        institution = _row_to_institution(row)
        ranked.append(
            institution.model_copy(
                update={
                    "nirf_rank": row[-3],
                    "nirf_score": row[-2],
                    "nirf_id": row[-1] or institution.nirf_id,
                    "ranking_category": category,
                    "ranking_year": year,
                }
            )
        )
    return ranked


def rankings_for(institution_id: str, db_path: Optional[Path] = None) -> list[tuple]:
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT ranking_body, ranking_category, ranking_year, rank, score "
            "FROM institution_rankings WHERE institution_id = ? ORDER BY ranking_category",
            (institution_id,),
        ).fetchall()
    finally:
        conn.close()


def all_ranked_profiles(db_path: Optional[Path] = None) -> list[RankedProfile]:
    """Every (institution, ranking category) pair NIRF published.

    institution_rankings is the correct source for anything keyed on category:
    upsert_institution() merges an institution ranked in several disciplines
    into one row keeping a single ranking_category, so reading the
    institutions table instead silently loses every other category that
    institution appears in -- 871 real pairs collapse to 523.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT r.institution_id, i.canonical_name, r.nirf_id, r.ranking_category, "
            "r.ranking_year FROM institution_rankings r "
            "JOIN institutions i ON i.institution_id = r.institution_id "
            "WHERE r.nirf_id IS NOT NULL "
            "ORDER BY r.ranking_category, r.rank"
        ).fetchall()
    finally:
        conn.close()
    return [RankedProfile(**dict(zip(RankedProfile.model_fields, row))) for row in rows]
