import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from src.facts.models import CitationRequired, SourceRef, VerificationStatus

REFS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS course_fact_refs (
    fact_table TEXT NOT NULL,
    record_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    quoted_evidence TEXT NOT NULL,
    page_number TEXT,
    verification_status TEXT NOT NULL,
    reviewed_by TEXT,
    PRIMARY KEY (fact_table, record_id, field_id, document_id)
)
"""


def field_ref(
    field_id: str,
    document_id: str,
    quoted_evidence: str,
    verification_status: VerificationStatus = VerificationStatus.PENDING,
) -> SourceRef:
    return SourceRef(
        field_id=field_id,
        document_id=document_id,
        quoted_evidence=quoted_evidence,
        verification_status=verification_status,
    )


def _is_populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    return True


def check_citations(model, field_id_map: dict[str, str], refs: list[SourceRef]) -> None:
    """Hard Constraint 2, enforced per field rather than per record: every
    POPULATED field must be covered by at least one ref citing its Field ID.
    A null field (Hard Constraint 4: null over fabrication) needs none."""
    cited = {ref.field_id for ref in refs}
    missing = [
        f"{name} ({field_id})"
        for name, field_id in field_id_map.items()
        if _is_populated(getattr(model, name, None)) and field_id not in cited
    ]
    if missing:
        raise CitationRequired(
            f"{model.__class__.__name__} has populated fields with no citation: {', '.join(missing)}"
        )


def serialize(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        # A list may now hold Pydantic models, not only strings -- Curriculum
        # carries Subject objects so the page can render a subject's name and
        # description together. json.dumps cannot encode those directly.
        return json.dumps([
            item.model_dump() if hasattr(item, "model_dump") else item for item in value
        ])
    if isinstance(value, bool):
        return int(value)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_id(table: str, id_values: tuple, recorded_at: str) -> str:
    seed = table + "|" + "|".join(str(v) for v in id_values) + "|" + recorded_at
    return f"REC-{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def supersede_and_insert(
    conn: sqlite3.Connection,
    table: str,
    id_columns: tuple[str, ...],
    value_columns: tuple[str, ...],
    id_values: tuple,
    current_values: dict[str, Any],
    existing_row: Optional[tuple],
) -> tuple[str, bool]:
    """Insert a new current row, superseding any differing current row for the
    same identity. Returns (record_id, changed). An unchanged value is a
    no-op -- re-running retrieval must not manufacture history."""
    serialized = {k: serialize(v) for k, v in current_values.items()}

    if existing_row is not None:
        existing_record_id = existing_row[0]
        existing_values = dict(zip(value_columns, existing_row[1 : 1 + len(value_columns)]))
        if existing_values == serialized:
            return existing_record_id, False
        conn.execute(
            f"UPDATE {table} SET superseded_at = ? WHERE record_id = ?", (_now(), existing_record_id)
        )

    recorded_at = _now()
    record_id = _record_id(table, id_values, recorded_at)
    columns = ["record_id", *id_columns, *value_columns, "recorded_at", "superseded_at"]
    values = [record_id, *id_values, *[serialized[c] for c in value_columns], recorded_at, None]
    placeholders = ",".join("?" * len(columns))
    conn.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", values)
    return record_id, True


def insert_refs(conn: sqlite3.Connection, table: str, record_id: str, refs: list[SourceRef]) -> None:
    for ref in refs:
        conn.execute(
            "INSERT OR REPLACE INTO course_fact_refs "
            "(fact_table, record_id, field_id, document_id, quoted_evidence, page_number, "
            "verification_status, reviewed_by) VALUES (?,?,?,?,?,?,?,?)",
            (
                table,
                record_id,
                ref.field_id,
                ref.document_id,
                ref.quoted_evidence,
                ref.page_number,
                ref.verification_status.value,
                ref.reviewed_by,
            ),
        )


def fetch_refs(conn: sqlite3.Connection, table: str, record_id: str) -> list[SourceRef]:
    rows = conn.execute(
        "SELECT field_id, document_id, quoted_evidence, page_number, verification_status, reviewed_by "
        "FROM course_fact_refs WHERE fact_table = ? AND record_id = ? ORDER BY field_id",
        (table, record_id),
    ).fetchall()
    return [
        SourceRef(
            field_id=r[0], document_id=r[1], quoted_evidence=r[2], page_number=r[3],
            verification_status=VerificationStatus(r[4]), reviewed_by=r[5],
        )
        for r in rows
    ]
