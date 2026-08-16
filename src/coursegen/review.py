from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunks import CHUNKS_BY_KEY


@dataclass(frozen=True)
class ReviewItem:
    course_id: str
    course_name: str
    flagged_chunks: list[str]
    attempts: dict[str, int]
    discipline: str | None
    failure_codes: list[str]
    source: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "course_name": self.course_name,
            "flagged_chunks": self.flagged_chunks,
            "attempts": self.attempts,
            "discipline": self.discipline,
            "failure_codes": self.failure_codes,
        }


def _item_from_run(payload: dict[str, Any], source: Path, discipline: str | None) -> ReviewItem | None:
    course_id = payload.get("course_id")
    course_name = payload.get("course_name")
    if not course_id or not course_name:
        return None

    chunks = payload.get("chunks") or []
    flagged = [
        c["chunk"]
        for c in chunks
        if isinstance(c, dict) and c.get("status") != "accepted" and c.get("chunk") in CHUNKS_BY_KEY
    ]
    if not flagged:
        flagged = [c for c in (payload.get("flagged_chunks") or []) if c in CHUNKS_BY_KEY]

    codes: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict) or chunk.get("status") == "accepted":
            continue
        for report in chunk.get("reports") or []:
            for finding in report.get("findings") or []:
                if finding.get("severity") == "error" and finding.get("code") not in codes:
                    codes.append(str(finding.get("code")))

    return ReviewItem(
        course_id=str(course_id),
        course_name=str(course_name),
        flagged_chunks=flagged,
        attempts={
            c["chunk"]: c.get("attempts", 0)
            for c in chunks
            if isinstance(c, dict) and c.get("chunk") in CHUNKS_BY_KEY
        },
        discipline=discipline,
        failure_codes=codes,
        source=source,
    )


def _discipline_for(artifacts_dir: Path, course_id: str) -> str | None:
    course_path = Path(artifacts_dir) / course_id / "course.json"
    if not course_path.exists():
        return None
    try:
        with course_path.open(encoding="utf-8") as handle:
            return json.load(handle).get("category")
    except (json.JSONDecodeError, OSError):
        return None


def load_review_queue(review_dir: Path, artifacts_dir: Path) -> list[ReviewItem]:
    review_path = Path(review_dir)
    items: list[ReviewItem] = []
    seen: set[str] = set()

    if review_path.exists():
        for path in sorted(review_path.glob("*.json")):
            try:
                with path.open(encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (json.JSONDecodeError, OSError):
                continue
            course_id = str(payload.get("course_id", ""))
            item = _item_from_run(payload, path, _discipline_for(artifacts_dir, course_id))
            if item and item.course_id not in seen:
                seen.add(item.course_id)
                items.append(item)

    for path in sorted(Path(artifacts_dir).glob("*/run.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            continue
        if payload.get("status") == "validated":
            continue
        course_id = str(payload.get("course_id", ""))
        if course_id in seen:
            continue
        item = _item_from_run(payload, path, _discipline_for(artifacts_dir, course_id))
        if item:
            seen.add(item.course_id)
            items.append(item)

    return items
