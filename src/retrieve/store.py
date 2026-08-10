import json
import sqlite3
from pathlib import Path
from typing import Optional

from src.retrieve.models import (
    DocumentRecord,
    DocumentType,
    IntentResolution,
    IntentRole,
    MatchType,
    RetrievalIntent,
    Segment,
    SourceTier,
)

DEFAULT_DB_PATH = Path("data/manifest.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    document_url TEXT NOT NULL UNIQUE,
    document_title TEXT NOT NULL,
    local_path TEXT,
    file_hash TEXT,
    content_type TEXT,
    content_length INTEGER,
    http_status INTEGER,
    publication_date TEXT,
    academic_year TEXT,
    valid_from TEXT,
    valid_until TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_intents (
    intent_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    segment TEXT NOT NULL,
    field_ids TEXT NOT NULL,
    source_id TEXT NOT NULL,
    priority INTEGER NOT NULL,
    role TEXT NOT NULL,
    query_terms TEXT NOT NULL,
    required_document_type TEXT NOT NULL,
    qualification_level TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intent_resolutions (
    intent_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    match_confidence REAL NOT NULL,
    match_type TEXT NOT NULL,
    validated INTEGER NOT NULL,
    validation_note TEXT,
    PRIMARY KEY (intent_id, document_id)
);
"""

_DOCUMENT_COLUMNS = (
    "document_id, source_id, source_tier, document_url, document_title, local_path, "
    "file_hash, content_type, content_length, http_status, publication_date, "
    "academic_year, valid_from, valid_until, retrieved_at"
)

_INTENT_COLUMNS = (
    "intent_id, course_id, segment, field_ids, source_id, priority, role, "
    "query_terms, required_document_type, qualification_level"
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


def _row_to_document(row: tuple) -> DocumentRecord:
    return DocumentRecord(
        document_id=row[0],
        source_id=row[1],
        source_tier=SourceTier(row[2]),
        document_url=row[3],
        document_title=row[4],
        local_path=row[5],
        file_hash=row[6],
        content_type=row[7],
        content_length=row[8],
        http_status=row[9],
        publication_date=row[10],
        academic_year=row[11],
        valid_from=row[12],
        valid_until=row[13],
        retrieved_at=row[14],
    )


def _row_to_intent(row: tuple) -> RetrievalIntent:
    return RetrievalIntent(
        intent_id=row[0],
        course_id=row[1],
        segment=Segment(row[2]),
        field_ids=json.loads(row[3]),
        source_id=row[4],
        priority=row[5],
        role=IntentRole(row[6]),
        query_terms=json.loads(row[7]),
        required_document_type=[DocumentType(d) for d in json.loads(row[8])],
        qualification_level=row[9],
    )


class CourseDocument(DocumentRecord):
    segments: list[Segment] = []


def documents_for_course(
    course_id: str, segment: Optional[Segment] = None, db_path: Optional[Path] = None
) -> list[CourseDocument]:
    """Documents resolved for a course, each carrying the segments it serves.

    This is the seam Stage 2 consumes. One document may serve several segments,
    so it is returned once with every segment it was resolved for -- which is
    what lets extraction target a segment's own evidence rather than a blob of
    everything retrieved for the course.
    """
    conn = _connect(db_path)
    try:
        sql = (
            f"SELECT {_prefixed(_DOCUMENT_COLUMNS, 'd')}, i.segment FROM documents d "
            "JOIN intent_resolutions r ON r.document_id = d.document_id "
            "JOIN retrieval_intents i ON i.intent_id = r.intent_id "
            "WHERE i.course_id = ?"
        )
        params: list = [course_id]
        if segment is not None:
            sql += " AND i.segment = ?"
            params.append(segment.value)
        rows = conn.execute(sql + " ORDER BY d.document_id", params).fetchall()
    finally:
        conn.close()

    merged: dict[str, CourseDocument] = {}
    for row in rows:
        document = _row_to_document(row)
        found = merged.get(document.document_id)
        if found is None:
            found = CourseDocument(**document.model_dump(), segments=[])
            merged[document.document_id] = found
        parsed = Segment(row[-1])
        if parsed not in found.segments:
            found.segments.append(parsed)
    return list(merged.values())


def courses_with_documents(db_path: Optional[Path] = None) -> list[str]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT i.course_id FROM retrieval_intents i "
            "JOIN intent_resolutions r ON r.intent_id = i.intent_id ORDER BY i.course_id"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def insert_document(document: DocumentRecord, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            f"INSERT OR IGNORE INTO documents ({_DOCUMENT_COLUMNS}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                document.document_id,
                document.source_id,
                document.source_tier.value,
                document.document_url,
                document.document_title,
                document.local_path,
                document.file_hash,
                document.content_type,
                document.content_length,
                document.http_status,
                document.publication_date,
                document.academic_year,
                document.valid_from,
                document.valid_until,
                document.retrieved_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_document_by_url(url: str, db_path: Optional[Path] = None) -> Optional[DocumentRecord]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE document_url = ?", (url,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _row_to_document(row)


def get_document_by_id(document_id: str, db_path: Optional[Path] = None) -> Optional[DocumentRecord]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _row_to_document(row)


def count_documents(db_path: Optional[Path] = None) -> int:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()


def insert_intent(intent: RetrievalIntent, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO retrieval_intents ({_INTENT_COLUMNS}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                intent.intent_id,
                intent.course_id,
                intent.segment.value,
                json.dumps(intent.field_ids),
                intent.source_id,
                intent.priority,
                intent.role.value,
                json.dumps(intent.query_terms),
                json.dumps([d.value for d in intent.required_document_type]),
                intent.qualification_level,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_resolution(resolution: IntentResolution, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO intent_resolutions "
            "(intent_id, document_id, match_confidence, match_type, validated, validation_note) "
            "VALUES (?,?,?,?,?,?)",
            (
                resolution.intent_id,
                resolution.document_id,
                resolution.match_confidence,
                resolution.match_type.value,
                int(resolution.validated),
                resolution.validation_note,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def intents_for_document(document_id: str, db_path: Optional[Path] = None) -> list[RetrievalIntent]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_INTENT_COLUMNS} FROM retrieval_intents WHERE intent_id IN "
            "(SELECT intent_id FROM intent_resolutions WHERE document_id = ?) "
            "ORDER BY intent_id",
            (document_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_intent(row) for row in rows]


def unresolved_intents(db_path: Optional[Path] = None) -> list[RetrievalIntent]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_INTENT_COLUMNS} FROM retrieval_intents WHERE intent_id NOT IN "
            "(SELECT intent_id FROM intent_resolutions) ORDER BY intent_id"
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_intent(row) for row in rows]
