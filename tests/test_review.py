from __future__ import annotations

import json
from pathlib import Path

from coursegen.review import load_review_queue


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_payload(course_id: str, name: str, flagged: str | None) -> dict:
    chunks = []
    for key in ("profile", "snapshot", "academics", "outcomes", "market", "guidance"):
        failed = key == flagged
        chunks.append(
            {
                "chunk": key,
                "status": "flagged" if failed else "accepted",
                "attempts": 3 if failed else 1,
                "reports": [
                    {
                        "status": "fail",
                        "findings": [
                            {"code": "duplicate_subject", "severity": "error", "path": "x", "message": "m"}
                        ],
                    }
                ]
                if failed
                else [],
            }
        )
    return {
        "course_id": course_id,
        "course_name": name,
        "status": "flagged" if flagged else "validated",
        "flagged_chunks": [flagged] if flagged else [],
        "chunks": chunks,
    }


def test_queue_reads_the_review_directory(tmp_path: Path) -> None:
    write(tmp_path / "_review" / "crs_a.json", run_payload("crs_a", "B.Ed", "academics"))
    write(tmp_path / "crs_a" / "course.json", {"category": "Education"})
    queue = load_review_queue(tmp_path / "_review", tmp_path)
    assert len(queue) == 1
    item = queue[0]
    assert item.course_id == "crs_a"
    assert item.flagged_chunks == ["academics"]
    assert item.attempts["academics"] == 3
    assert item.discipline == "Education"
    assert "duplicate_subject" in item.failure_codes


def test_queue_also_finds_flagged_runs_without_a_review_file(tmp_path: Path) -> None:
    write(tmp_path / "crs_b" / "run.json", run_payload("crs_b", "MBBS", "market"))
    queue = load_review_queue(tmp_path / "_review", tmp_path)
    assert [i.course_id for i in queue] == ["crs_b"]
    assert queue[0].flagged_chunks == ["market"]


def test_validated_runs_are_not_queued(tmp_path: Path) -> None:
    write(tmp_path / "crs_c" / "run.json", run_payload("crs_c", "BBA", None))
    assert load_review_queue(tmp_path / "_review", tmp_path) == []


def test_a_course_is_queued_once(tmp_path: Path) -> None:
    write(tmp_path / "_review" / "crs_d.json", run_payload("crs_d", "BCA", "market"))
    write(tmp_path / "crs_d" / "run.json", run_payload("crs_d", "BCA", "market"))
    assert len(load_review_queue(tmp_path / "_review", tmp_path)) == 1


def test_malformed_review_file_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "_review").mkdir(parents=True)
    (tmp_path / "_review" / "bad.json").write_text("{not json", encoding="utf-8")
    write(tmp_path / "_review" / "crs_e.json", run_payload("crs_e", "B.Com", "market"))
    assert [i.course_id for i in load_review_queue(tmp_path / "_review", tmp_path)] == ["crs_e"]


def test_missing_directories_are_safe(tmp_path: Path) -> None:
    assert load_review_queue(tmp_path / "nope", tmp_path / "also-nope") == []
