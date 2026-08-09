import json
import sqlite3
from pathlib import Path
from typing import Optional

from src.facts import engine
from src.facts.course_facts import (
    COURSE_FIELD_IDS,
    CURRICULUM_FIELD_IDS,
    ELIGIBILITY_FIELD_IDS,
    SPECIALISATION_FIELD_IDS,
    Course,
    Curriculum,
    EligibilityRule,
    Specialisation,
)
from src.facts.models import SourceRef

DEFAULT_DB_PATH = Path("data/course_facts.db")

field_ref = engine.field_ref

_COURSE_ID_COLS = ("course_id",)
_COURSE_VALUE_COLS = tuple(COURSE_FIELD_IDS)
_COURSE_LIST_FIELDS = {"course_aliases", "exit_options"}
_COURSE_BOOL_FIELDS = {"full_time_available", "part_time_available", "online_available", "distance_available"}

_ELIGIBILITY_ID_COLS = ("course_id", "eligibility_year")
_ELIGIBILITY_VALUE_COLS = tuple(ELIGIBILITY_FIELD_IDS)
_ELIGIBILITY_LIST_FIELDS = {"accepted_streams", "compulsory_subjects", "recommended_subjects"}
_ELIGIBILITY_BOOL_FIELDS = {"portfolio_required", "interview_required", "lateral_entry_available"}

_CURRICULUM_ID_COLS = ("course_id", "curriculum_year")
_CURRICULUM_VALUE_COLS = tuple(CURRICULUM_FIELD_IDS)
_CURRICULUM_LIST_FIELDS = {"foundation_subjects", "core_subjects", "electives"}

_SPECIALISATION_ID_COLS = ("course_id", "specialisation_name")
_SPECIALISATION_VALUE_COLS = tuple(SPECIALISATION_FIELD_IDS)
_SPECIALISATION_LIST_FIELDS = {"typical_subjects"}

_DDL = """
CREATE TABLE IF NOT EXISTS courses (
    record_id TEXT PRIMARY KEY, course_id TEXT NOT NULL,
    {course_cols},
    recorded_at TEXT NOT NULL, superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS courses_current ON courses (course_id, superseded_at);

CREATE TABLE IF NOT EXISTS eligibility_rules (
    record_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, eligibility_year TEXT NOT NULL,
    {eligibility_cols},
    recorded_at TEXT NOT NULL, superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS eligibility_current ON eligibility_rules (course_id, eligibility_year, superseded_at);

CREATE TABLE IF NOT EXISTS curricula (
    record_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, curriculum_year TEXT NOT NULL,
    {curriculum_cols},
    recorded_at TEXT NOT NULL, superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS curricula_current ON curricula (course_id, curriculum_year, superseded_at);

CREATE TABLE IF NOT EXISTS specialisations (
    record_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, specialisation_name TEXT NOT NULL,
    {specialisation_cols},
    recorded_at TEXT NOT NULL, superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS specialisations_current ON specialisations (course_id, superseded_at);
""".format(
    course_cols=", ".join(f"{c} TEXT" for c in _COURSE_VALUE_COLS),
    eligibility_cols=", ".join(f"{c} TEXT" for c in _ELIGIBILITY_VALUE_COLS),
    curriculum_cols=", ".join(f"{c} TEXT" for c in _CURRICULUM_VALUE_COLS),
    specialisation_cols=", ".join(f"{c} TEXT" for c in _SPECIALISATION_VALUE_COLS),
)


def _connect(db_path: Optional[Path]) -> sqlite3.Connection:
    resolved = db_path if db_path is not None else DEFAULT_DB_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.executescript(_DDL)
    conn.executescript(engine.REFS_TABLE_DDL)
    conn.commit()
    return conn


def _deserialize(value, field_name: str, list_fields: set, bool_fields: set):
    if value is None:
        return [] if field_name in list_fields else None
    if field_name in list_fields:
        return json.loads(value)
    if field_name in bool_fields:
        return bool(value)
    return value


def _row_to_model(row, id_cols, value_cols, model_cls, list_fields, bool_fields):
    fields = {"record_id": row[0]}
    offset = 1
    for col in id_cols:
        fields[col] = row[offset]
        offset += 1
    for col in value_cols:
        fields[col] = _deserialize(row[offset], col, list_fields, bool_fields)
        offset += 1
    fields["recorded_at"] = row[offset]
    fields["superseded_at"] = row[offset + 1]
    return model_cls(**fields)


def refs_for(table: str, record_id: str, db_path: Optional[Path] = None) -> list[SourceRef]:
    conn = _connect(db_path)
    try:
        return engine.fetch_refs(conn, table, record_id)
    finally:
        conn.close()


# --- Course -----------------------------------------------------------------


def record_course(course: Course, refs: list[SourceRef], db_path: Optional[Path] = None) -> str:
    engine.check_citations(course, COURSE_FIELD_IDS, refs)
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            f"SELECT record_id, {', '.join(_COURSE_VALUE_COLS)} FROM courses "
            "WHERE course_id = ? AND superseded_at IS NULL",
            (course.course_id,),
        ).fetchone()
        record_id, changed = engine.supersede_and_insert(
            conn, "courses", _COURSE_ID_COLS, _COURSE_VALUE_COLS,
            (course.course_id,), {c: getattr(course, c) for c in _COURSE_VALUE_COLS}, existing,
        )
        if changed:
            engine.insert_refs(conn, "courses", record_id, refs)
        conn.commit()
        return record_id
    finally:
        conn.close()


def current_course(course_id: str, db_path: Optional[Path] = None) -> Optional[Course]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT record_id, course_id, {', '.join(_COURSE_VALUE_COLS)}, recorded_at, superseded_at "
            "FROM courses WHERE course_id = ? AND superseded_at IS NULL",
            (course_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_model(row, _COURSE_ID_COLS, _COURSE_VALUE_COLS, Course, _COURSE_LIST_FIELDS, _COURSE_BOOL_FIELDS)


def course_history(course_id: str, db_path: Optional[Path] = None) -> list[Course]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT record_id, course_id, {', '.join(_COURSE_VALUE_COLS)}, recorded_at, superseded_at "
            "FROM courses WHERE course_id = ? ORDER BY recorded_at",
            (course_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        _row_to_model(r, _COURSE_ID_COLS, _COURSE_VALUE_COLS, Course, _COURSE_LIST_FIELDS, _COURSE_BOOL_FIELDS)
        for r in rows
    ]


# --- Eligibility --------------------------------------------------------------


def record_eligibility(rule: EligibilityRule, refs: list[SourceRef], db_path: Optional[Path] = None) -> str:
    engine.check_citations(rule, ELIGIBILITY_FIELD_IDS, refs)
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            f"SELECT record_id, {', '.join(_ELIGIBILITY_VALUE_COLS)} FROM eligibility_rules "
            "WHERE course_id = ? AND eligibility_year = ? AND superseded_at IS NULL",
            (rule.course_id, rule.eligibility_year),
        ).fetchone()
        record_id, changed = engine.supersede_and_insert(
            conn, "eligibility_rules", _ELIGIBILITY_ID_COLS, _ELIGIBILITY_VALUE_COLS,
            (rule.course_id, rule.eligibility_year),
            {c: getattr(rule, c) for c in _ELIGIBILITY_VALUE_COLS}, existing,
        )
        if changed:
            engine.insert_refs(conn, "eligibility_rules", record_id, refs)
        conn.commit()
        return record_id
    finally:
        conn.close()


def eligibility_for_years(
    course_id: str, years: list[str], db_path: Optional[Path] = None
) -> list[EligibilityRule]:
    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" * len(years))
        rows = conn.execute(
            f"SELECT record_id, course_id, eligibility_year, {', '.join(_ELIGIBILITY_VALUE_COLS)}, "
            f"recorded_at, superseded_at FROM eligibility_rules "
            f"WHERE course_id = ? AND eligibility_year IN ({placeholders}) AND superseded_at IS NULL",
            (course_id, *years),
        ).fetchall()
    finally:
        conn.close()
    return [
        _row_to_model(
            r, _ELIGIBILITY_ID_COLS, _ELIGIBILITY_VALUE_COLS, EligibilityRule,
            _ELIGIBILITY_LIST_FIELDS, _ELIGIBILITY_BOOL_FIELDS,
        )
        for r in rows
    ]


# --- Curriculum -----------------------------------------------------------


def record_curriculum(curriculum: Curriculum, refs: list[SourceRef], db_path: Optional[Path] = None) -> str:
    engine.check_citations(curriculum, CURRICULUM_FIELD_IDS, refs)
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            f"SELECT record_id, {', '.join(_CURRICULUM_VALUE_COLS)} FROM curricula "
            "WHERE course_id = ? AND curriculum_year = ? AND superseded_at IS NULL",
            (curriculum.course_id, curriculum.curriculum_year),
        ).fetchone()
        record_id, changed = engine.supersede_and_insert(
            conn, "curricula", _CURRICULUM_ID_COLS, _CURRICULUM_VALUE_COLS,
            (curriculum.course_id, curriculum.curriculum_year),
            {c: getattr(curriculum, c) for c in _CURRICULUM_VALUE_COLS}, existing,
        )
        if changed:
            engine.insert_refs(conn, "curricula", record_id, refs)
        conn.commit()
        return record_id
    finally:
        conn.close()


def current_curriculum(
    course_id: str, curriculum_year: str, db_path: Optional[Path] = None
) -> Optional[Curriculum]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT record_id, course_id, curriculum_year, {', '.join(_CURRICULUM_VALUE_COLS)}, "
            "recorded_at, superseded_at FROM curricula "
            "WHERE course_id = ? AND curriculum_year = ? AND superseded_at IS NULL",
            (course_id, curriculum_year),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_model(
        row, _CURRICULUM_ID_COLS, _CURRICULUM_VALUE_COLS, Curriculum, _CURRICULUM_LIST_FIELDS, set()
    )


# --- Specialisation ---------------------------------------------------------


def record_specialisation(
    spec: Specialisation, refs: list[SourceRef], db_path: Optional[Path] = None
) -> str:
    engine.check_citations(spec, SPECIALISATION_FIELD_IDS, refs)
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            f"SELECT record_id, {', '.join(_SPECIALISATION_VALUE_COLS)} FROM specialisations "
            "WHERE course_id = ? AND specialisation_name = ? AND superseded_at IS NULL",
            (spec.course_id, spec.specialisation_name),
        ).fetchone()
        record_id, changed = engine.supersede_and_insert(
            conn, "specialisations", _SPECIALISATION_ID_COLS, _SPECIALISATION_VALUE_COLS,
            (spec.course_id, spec.specialisation_name),
            {c: getattr(spec, c) for c in _SPECIALISATION_VALUE_COLS}, existing,
        )
        if changed:
            engine.insert_refs(conn, "specialisations", record_id, refs)
        conn.commit()
        return record_id
    finally:
        conn.close()


def specialisations_for(course_id: str, db_path: Optional[Path] = None) -> list[Specialisation]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT record_id, course_id, specialisation_name, {', '.join(_SPECIALISATION_VALUE_COLS)}, "
            "recorded_at, superseded_at FROM specialisations "
            "WHERE course_id = ? AND superseded_at IS NULL ORDER BY specialisation_name",
            (course_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        _row_to_model(
            r, _SPECIALISATION_ID_COLS, _SPECIALISATION_VALUE_COLS, Specialisation,
            _SPECIALISATION_LIST_FIELDS, set(),
        )
        for r in rows
    ]
