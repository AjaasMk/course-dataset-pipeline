from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    )
    try:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)
    return path


def read_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


class ArtifactStore:
    def __init__(self, root: Path, course_id: str) -> None:
        self.root = Path(root) / course_id
        self.course_id = course_id

    @property
    def course_path(self) -> Path:
        return self.root / "course.json"

    @property
    def run_path(self) -> Path:
        return self.root / "run.json"

    @property
    def validation_path(self) -> Path:
        return self.root / "validation.json"

    def chunk_path(self, chunk_key: str) -> Path:
        return self.root / "chunks" / f"{chunk_key}.json"

    def attempt_path(self, chunk_key: str, attempt: int) -> Path:
        return self.root / "chunks" / f"{chunk_key}.attempt-{attempt}.json"

    def save_chunk(self, chunk_key: str, payload: dict[str, Any]) -> Path:
        return write_json(self.chunk_path(chunk_key), payload)

    def save_attempt(self, chunk_key: str, attempt: int, payload: dict[str, Any]) -> Path:
        return write_json(self.attempt_path(chunk_key, attempt), payload)

    def load_chunk(self, chunk_key: str) -> dict[str, Any] | None:
        path = self.chunk_path(chunk_key)
        if not path.exists():
            return None
        payload = read_json(path)
        return payload if isinstance(payload, dict) else None

    def save_course(self, document: dict[str, Any]) -> Path:
        return write_json(self.course_path, document)

    def load_course(self) -> dict[str, Any] | None:
        if not self.course_path.exists():
            return None
        payload = read_json(self.course_path)
        return payload if isinstance(payload, dict) else None

    def save_run(self, payload: dict[str, Any]) -> Path:
        return write_json(self.run_path, payload)

    def save_validation(self, payload: dict[str, Any]) -> Path:
        return write_json(self.validation_path, payload)
