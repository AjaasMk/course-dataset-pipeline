import sqlite3
from pathlib import Path
from typing import Optional

from src.schema import ManifestEntry, SourceType

DEFAULT_DB_PATH = Path("data/manifest.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS manifest (
    course_name TEXT NOT NULL,
    tier TEXT NOT NULL,
    source_type TEXT NOT NULL,
    matched_url TEXT,
    local_path TEXT,
    file_hash TEXT,
    match_confidence REAL NOT NULL,
    retrieved_at TEXT NOT NULL,
    content_type TEXT,
    content_length INTEGER,
    http_status INTEGER,
    PRIMARY KEY (course_name, matched_url)
)
"""

_SELECT = """
SELECT course_name, tier, source_type, matched_url, local_path, file_hash,
       match_confidence, retrieved_at, content_type, content_length, http_status
FROM manifest WHERE course_name = ? AND matched_url = ?
"""

_INSERT = """
INSERT INTO manifest (
    course_name, tier, source_type, matched_url, local_path, file_hash,
    match_confidence, retrieved_at, content_type, content_length, http_status
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _connect(db_path: Optional[Path]) -> sqlite3.Connection:
    resolved = db_path if db_path is not None else DEFAULT_DB_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def get_entry(
    course_name: str, matched_url: str, db_path: Optional[Path] = None
) -> Optional[ManifestEntry]:
    conn = _connect(db_path)
    try:
        row = conn.execute(_SELECT, (course_name, matched_url)).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return ManifestEntry(
        course_name=row[0],
        tier=row[1],
        source_type=SourceType(row[2]),
        matched_url=row[3],
        local_path=row[4],
        file_hash=row[5],
        match_confidence=row[6],
        retrieved_at=row[7],
        content_type=row[8],
        content_length=row[9],
        http_status=row[10],
    )


def insert_entry(entry: ManifestEntry, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            _INSERT,
            (
                entry.course_name,
                entry.tier,
                entry.source_type.value,
                entry.matched_url,
                entry.local_path,
                entry.file_hash,
                entry.match_confidence,
                entry.retrieved_at,
                entry.content_type,
                entry.content_length,
                entry.http_status,
            ),
        )
        conn.commit()
    finally:
        conn.close()
