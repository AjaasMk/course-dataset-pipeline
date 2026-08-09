import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.facts.models import (
    PUBLISHABLE_STATUSES,
    CitationRequired,
    Ranking,
    SourceRef,
    VerificationStatus,
)

DEFAULT_DB_PATH = Path("data/facts.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS rankings (
    record_id TEXT PRIMARY KEY,
    institution_id TEXT NOT NULL,
    ranking_body TEXT NOT NULL,
    ranking_year TEXT NOT NULL,
    ranking_category TEXT NOT NULL,
    rank INTEGER,
    rank_band TEXT,
    ranking_score REAL,
    naac_status TEXT,
    nba_programme_status TEXT,
    recorded_at TEXT NOT NULL,
    superseded_at TEXT
);

CREATE INDEX IF NOT EXISTS rankings_current
    ON rankings (institution_id, ranking_body, ranking_category, ranking_year, superseded_at);

CREATE TABLE IF NOT EXISTS source_refs (
    record_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    quoted_evidence TEXT NOT NULL,
    page_number TEXT,
    verification_status TEXT NOT NULL,
    reviewed_by TEXT,
    PRIMARY KEY (record_id, field_id, document_id)
);
"""

_RANKING_COLUMNS = (
    "record_id, institution_id, ranking_body, ranking_year, ranking_category, "
    "rank, rank_band, ranking_score, naac_status, nba_programme_status, "
    "recorded_at, superseded_at"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Optional[Path]) -> sqlite3.Connection:
    resolved = db_path if db_path is not None else DEFAULT_DB_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.executescript(_CREATE)
    conn.commit()
    return conn


def _record_id(identity: tuple, recorded_at: str) -> str:
    seed = "|".join(str(part) for part in identity) + "|" + recorded_at
    return f"REC-{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def _row_to_ranking(row: tuple) -> Ranking:
    return Ranking(
        record_id=row[0],
        institution_id=row[1],
        ranking_body=row[2],
        ranking_year=row[3],
        ranking_category=row[4],
        rank=row[5],
        rank_band=row[6],
        ranking_score=row[7],
        naac_status=row[8],
        nba_programme_status=row[9],
        recorded_at=row[10],
        superseded_at=row[11],
    )


def record_ranking(
    ranking: Ranking, refs: list[SourceRef], db_path: Optional[Path] = None
) -> Optional[str]:
    """Record a ranking, superseding any differing current row rather than
    updating it in place.

    The client's workflow requires previous history to be preserved with no
    silent overwrite, so a changed value becomes a new row and the old one is
    closed off, keeping its own citations. An unchanged value is a no-op, so
    re-running retrieval does not manufacture history.
    """
    if not refs:
        raise CitationRequired(
            f"ranking for {ranking.institution_id} in {ranking.ranking_category} "
            f"{ranking.ranking_year} has no source_refs; an uncited fact cannot be stored"
        )

    conn = _connect(db_path)
    try:
        existing = conn.execute(
            f"SELECT {_RANKING_COLUMNS} FROM rankings WHERE institution_id = ? AND "
            "ranking_body = ? AND ranking_category = ? AND ranking_year = ? AND "
            "superseded_at IS NULL",
            ranking.identity(),
        ).fetchone()

        if existing is not None:
            if _row_to_ranking(existing).values() == ranking.values():
                return existing[0]
            conn.execute(
                "UPDATE rankings SET superseded_at = ? WHERE record_id = ?",
                (_now(), existing[0]),
            )

        recorded_at = _now()
        record_id = _record_id(ranking.identity(), recorded_at)
        conn.execute(
            f"INSERT INTO rankings ({_RANKING_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record_id,
                ranking.institution_id,
                ranking.ranking_body,
                ranking.ranking_year,
                ranking.ranking_category,
                ranking.rank,
                ranking.rank_band,
                ranking.ranking_score,
                ranking.naac_status,
                ranking.nba_programme_status,
                recorded_at,
                None,
            ),
        )
        for ref in refs:
            conn.execute(
                "INSERT OR REPLACE INTO source_refs "
                "(record_id, field_id, document_id, quoted_evidence, page_number, "
                "verification_status, reviewed_by) VALUES (?,?,?,?,?,?,?)",
                (
                    record_id,
                    ref.field_id,
                    ref.document_id,
                    ref.quoted_evidence,
                    ref.page_number,
                    ref.verification_status.value,
                    ref.reviewed_by,
                ),
            )
        conn.commit()
        return record_id
    finally:
        conn.close()


def current_rankings(institution_id: str, db_path: Optional[Path] = None) -> list[Ranking]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_RANKING_COLUMNS} FROM rankings WHERE institution_id = ? AND "
            "superseded_at IS NULL ORDER BY ranking_category, ranking_year",
            (institution_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_ranking(row) for row in rows]


def ranking_history(
    institution_id: str,
    ranking_body: str,
    ranking_category: str,
    ranking_year: str,
    db_path: Optional[Path] = None,
) -> list[Ranking]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_RANKING_COLUMNS} FROM rankings WHERE institution_id = ? AND "
            "ranking_body = ? AND ranking_category = ? AND ranking_year = ? "
            "ORDER BY recorded_at",
            (institution_id, ranking_body, ranking_category, ranking_year),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_ranking(row) for row in rows]


def refs_for(record_id: str, db_path: Optional[Path] = None) -> list[SourceRef]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT field_id, document_id, quoted_evidence, page_number, "
            "verification_status, reviewed_by FROM source_refs WHERE record_id = ? "
            "ORDER BY field_id",
            (record_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        SourceRef(
            field_id=r[0],
            document_id=r[1],
            quoted_evidence=r[2],
            page_number=r[3],
            verification_status=VerificationStatus(r[4]),
            reviewed_by=r[5],
        )
        for r in rows
    ]


def is_publishable(record_id: str, db_path: Optional[Path] = None) -> bool:
    """A record is publishable only when every citation is human verified.

    Ranking claims sit on the Mandatory Human Review Matrix, so an AI-checked
    value is not sufficient no matter how confident the match was.
    """
    refs = refs_for(record_id, db_path=db_path)
    return bool(refs) and all(ref.verification_status in PUBLISHABLE_STATUSES for ref in refs)
