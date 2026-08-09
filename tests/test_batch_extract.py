import logging
import sqlite3

import httpx
from anthropic import APIConnectionError

from src.extract.extract_inputs import ExtractionInput
from src.extract.batch_extract import (
    compute_chunk_hash,
    extract_all_courses,
    load_chunks,
    load_hash_store,
    save_hash_store,
)
from src.extract.models import Chunk
from src.schema import CourseDetail


def _connection_error():
    return APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _chunk(chunk_id=0, text="text"):
    return Chunk(chunk_id=chunk_id, text=text, source_document="d", source_url="u", token_count=1)


def _write_chunks(path, chunks):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[" + ",".join(c.model_dump_json() for c in chunks) + "]", encoding="utf-8")


def test_load_chunks_reads_json_array(tmp_path):
    chunk = _chunk()
    path = tmp_path / "chunks.json"
    _write_chunks(path, [chunk])

    assert load_chunks(path) == [chunk]


def test_compute_chunk_hash_is_stable_regardless_of_chunk_order():
    a = compute_chunk_hash([_chunk(0, "first"), _chunk(1, "second")])
    b = compute_chunk_hash([_chunk(1, "second"), _chunk(0, "first")])
    assert a == b


def test_compute_chunk_hash_changes_when_text_changes():
    a = compute_chunk_hash([_chunk(0, "original text")])
    b = compute_chunk_hash([_chunk(0, "edited text")])
    assert a != b


def test_hash_store_round_trips_through_disk(tmp_path):
    path = tmp_path / "hashes.json"
    save_hash_store(path, {"course_a": "abc123"})

    assert load_hash_store(path) == {"course_a": "abc123"}


def test_load_hash_store_returns_empty_dict_when_no_file_exists(tmp_path):
    assert load_hash_store(tmp_path / "missing.json") == {}


def test_extract_all_courses_writes_output_and_records_extracted(tmp_path):
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    _write_chunks(chunks_dir / "chemical_engineering__DOC-1.json", [_chunk()])

    row = ExtractionInput(
            course_id="chemical_engineering",
            chunk_filenames=["chemical_engineering__DOC-1.json"],
            documents_by_segment={},
        )
    fake_detail = CourseDetail(course_name="Chemical Engineering", category="engineering")

    def fake_extract(chunks, course_name, category):
        return fake_detail

    report = extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=fake_extract,
        hash_store_path=tmp_path / "hashes.json",
    )

    assert report.results[0].outcome == "extracted"
    out_path = extracted_dir / "chemical_engineering.json"
    assert out_path.exists()
    assert CourseDetail.model_validate_json(out_path.read_text()) == fake_detail


def test_extract_all_courses_isolates_failure_and_continues(tmp_path):
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    _write_chunks(chunks_dir / "course_one__DOC-1.json", [_chunk()])
    _write_chunks(chunks_dir / "course_two__DOC-1.json", [_chunk()])

    rows = [
        ExtractionInput(
            course_id="course_one",
            chunk_filenames=["course_one__DOC-1.json"],
            documents_by_segment={},
        ),
        ExtractionInput(
            course_id="course_two",
            chunk_filenames=["course_two__DOC-1.json"],
            documents_by_segment={},
        ),
    ]

    calls = []

    def flaky_extract(chunks, course_name, category):
        calls.append(course_name)
        if course_name == "course_one":
            raise RuntimeError("simulated model refusal")
        return CourseDetail(course_name=course_name, category=category)

    report = extract_all_courses(
        rows, chunks_dir, extracted_dir, extract_fn=flaky_extract,
        hash_store_path=tmp_path / "hashes.json",
    )

    assert len(report.results) == 2
    assert report.results[0].outcome == "extraction_failed"
    assert "simulated model refusal" in report.results[0].error
    assert report.results[1].outcome == "extracted"
    assert calls == ["course_one", "course_two"]  # RuntimeError isn't retried -- one attempt each


def test_extract_all_courses_retries_transient_connection_error_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    _write_chunks(chunks_dir / "course__DOC-1.json", [_chunk()])

    row = ExtractionInput(
            course_id="course",
            chunk_filenames=["course__DOC-1.json"],
            documents_by_segment={},
        )

    attempts = {"count": 0}

    def flaky_then_succeeds(chunks, course_name, category):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _connection_error()
        return CourseDetail(course_name=course_name, category=category)

    report = extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=flaky_then_succeeds,
        hash_store_path=tmp_path / "hashes.json",
    )

    assert report.results[0].outcome == "extracted"
    assert attempts["count"] == 3  # two transient failures, then a retried success


def test_extract_all_courses_gives_up_after_exhausting_retries_on_connection_error(tmp_path, monkeypatch):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    _write_chunks(chunks_dir / "course__DOC-1.json", [_chunk()])

    row = ExtractionInput(
            course_id="course",
            chunk_filenames=["course__DOC-1.json"],
            documents_by_segment={},
        )

    attempts = {"count": 0}

    def always_disconnects(chunks, course_name, category):
        attempts["count"] += 1
        raise _connection_error()

    report = extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=always_disconnects,
        hash_store_path=tmp_path / "hashes.json",
    )

    assert report.results[0].outcome == "extraction_failed"
    assert attempts["count"] == 3  # default max_retries, then gives up and records the failure


def test_extract_all_courses_logs_failure(tmp_path, caplog):
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    _write_chunks(chunks_dir / "course__DOC-1.json", [_chunk()])

    row = ExtractionInput(
            course_id="course",
            chunk_filenames=["course__DOC-1.json"],
            documents_by_segment={},
        )

    def failing_extract(chunks, course_name, category):
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO):
        extract_all_courses(
            [row], chunks_dir, extracted_dir, extract_fn=failing_extract,
            hash_store_path=tmp_path / "hashes.json",
        )

    assert any("extraction failed" in r.message for r in caplog.records)


def test_extract_all_courses_skips_unchanged_course_on_second_run(tmp_path):
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    hash_store_path = tmp_path / "hashes.json"
    _write_chunks(chunks_dir / "course__DOC-1.json", [_chunk(0, "same content")])

    row = ExtractionInput(
            course_id="course",
            chunk_filenames=["course__DOC-1.json"],
            documents_by_segment={},
        )

    calls = []

    def counting_extract(chunks, course_name, category):
        calls.append(course_name)
        return CourseDetail(course_name=course_name, category=category)

    first = extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=counting_extract, hash_store_path=hash_store_path
    )
    second = extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=counting_extract, hash_store_path=hash_store_path
    )

    assert first.results[0].outcome == "extracted"
    assert second.results[0].outcome == "skipped_unchanged"
    assert calls == ["course"]  # the model was only ever called once


def test_extract_all_courses_re_extracts_when_chunk_content_changes(tmp_path):
    chunks_dir = tmp_path / "chunks"
    extracted_dir = tmp_path / "extracted"
    hash_store_path = tmp_path / "hashes.json"
    chunk_path = chunks_dir / "course__DOC-1.json"
    _write_chunks(chunk_path, [_chunk(0, "original content")])

    row = ExtractionInput(
            course_id="course",
            chunk_filenames=["course__DOC-1.json"],
            documents_by_segment={},
        )

    calls = []

    def counting_extract(chunks, course_name, category):
        calls.append(course_name)
        return CourseDetail(course_name=course_name, category=category)

    extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=counting_extract, hash_store_path=hash_store_path
    )

    _write_chunks(chunk_path, [_chunk(0, "edited content — reader fix changed this")])
    second = extract_all_courses(
        [row], chunks_dir, extracted_dir, extract_fn=counting_extract, hash_store_path=hash_store_path
    )

    assert second.results[0].outcome == "extracted"
    assert calls == ["course", "course"]  # re-extracted both times since content differed
