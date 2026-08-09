import threading

from src.extract.run_chunking import chunk_all_documents
from src.retrieve import store
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


class _FakeCountTokensResponse:
    def __init__(self, input_tokens: int):
        self.input_tokens = input_tokens


class _FakeMessages:
    def count_tokens(self, model, messages):
        text = messages[0]["content"]
        return _FakeCountTokensResponse(input_tokens=max(1, int(len(text.split()) * 1.3)))


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _make_manifest_db(db_path, rows):
    """Seed the intent-first store: an intent, its document and the resolution
    linking them. Chunking reads resolved documents now, not a flat manifest."""
    for n, (course_name, tier, source_type, matched_url, local_path) in enumerate(rows, start=1):
        intent_id = f"RI-{n:03d}"
        document_id = f"DOC-{n:03d}"
        store.insert_intent(
            RetrievalIntent(
                intent_id=intent_id,
                course_id=course_name,
                segment=Segment.CURRICULUM,
                field_ids=["F042"],
                source_id=source_type,
                priority=1,
                role=IntentRole.PRIMARY,
                query_terms=[course_name],
                required_document_type=[DocumentType.OFFICIAL_WEBPAGE],
                qualification_level="Undergraduate",
            ),
            db_path=db_path,
        )
        store.insert_document(
            DocumentRecord(
                document_id=document_id,
                source_id=source_type,
                source_tier=SourceTier.A,
                document_url=matched_url,
                document_title=course_name,
                local_path=str(local_path),
                retrieved_at="2026-07-17T12:00:00+00:00",
            ),
            db_path=db_path,
        )
        store.insert_resolution(
            IntentResolution(
                intent_id=intent_id,
                document_id=document_id,
                match_confidence=0.9,
                match_type=MatchType.EXACT,
                validated=True,
            ),
            db_path=db_path,
        )


def _write_html(path, body_text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><body><h1>Title</h1><p>{body_text}</p></body></html>", encoding="utf-8")


def test_chunk_all_documents_chunks_every_row_and_writes_output(tmp_path):
    db_path = tmp_path / "manifest.db"
    raw_dir = tmp_path / "raw"
    chunks_dir = tmp_path / "chunks"

    doc_one = raw_dir / "course_one.html"
    doc_two = raw_dir / "course_two.html"
    _write_html(doc_one, "Course one content.")
    _write_html(doc_two, "Course two content.")

    _make_manifest_db(
        db_path,
        [
            ("Course One", "engineering", "aggregator_webpage", "https://example.com/one", str(doc_one)),
            ("Course Two", "engineering", "aggregator_webpage", "https://example.com/two", str(doc_two)),
        ],
    )

    report = chunk_all_documents(
        db_path=db_path, client=_FakeClient(), chunks_dir=chunks_dir, max_workers=2
    )

    assert len(report.results) == 2
    assert {r.course_name for r in report.results} == {"Course One", "Course Two"}
    assert all(r.outcome == "chunked" for r in report.results)
    assert (chunks_dir / "Course One__DOC-001.json").exists()
    assert (chunks_dir / "Course Two__DOC-002.json").exists()


def test_chunk_all_documents_isolates_failure_and_continues(tmp_path):
    db_path = tmp_path / "manifest.db"
    raw_dir = tmp_path / "raw"
    chunks_dir = tmp_path / "chunks"

    doc_ok = raw_dir / "course_ok.html"
    _write_html(doc_ok, "Real content.")
    missing_path = str(raw_dir / "does_not_exist.html")

    _make_manifest_db(
        db_path,
        [
            ("Course Missing", "engineering", "aggregator_webpage", "https://example.com/missing", missing_path),
            ("Course Ok", "engineering", "aggregator_webpage", "https://example.com/ok", str(doc_ok)),
        ],
    )

    report = chunk_all_documents(db_path=db_path, client=_FakeClient(), chunks_dir=chunks_dir, max_workers=2)

    by_name = {r.course_name: r for r in report.results}
    assert by_name["Course Missing"].outcome == "failed"
    assert by_name["Course Missing"].error is not None
    assert by_name["Course Ok"].outcome == "chunked"
    assert (chunks_dir / "Course OK__DOC-002.json").exists()


def test_chunk_all_documents_runs_concurrently_not_sequentially(tmp_path):
    db_path = tmp_path / "manifest.db"
    raw_dir = tmp_path / "raw"
    chunks_dir = tmp_path / "chunks"

    docs = []
    rows = []
    for i in range(4):
        doc = raw_dir / f"course_{i}.html"
        _write_html(doc, f"Content {i}.")
        docs.append(doc)
        rows.append((f"Course {i}", "engineering", "aggregator_webpage", f"https://example.com/{i}", str(doc)))
    _make_manifest_db(db_path, rows)

    seen_threads = set()
    lock = threading.Lock()

    class _TrackingMessages(_FakeMessages):
        def count_tokens(self, model, messages):
            with lock:
                seen_threads.add(threading.get_ident())
            return super().count_tokens(model, messages)

    class _TrackingClient:
        def __init__(self):
            self.messages = _TrackingMessages()

    chunk_all_documents(db_path=db_path, client=_TrackingClient(), chunks_dir=chunks_dir, max_workers=4)

    # With 4 independent documents and max_workers=4, more than one worker
    # thread should have handled the count_tokens() calls -- proves the work
    # is actually distributed across threads, not silently run one-at-a-time.
    assert len(seen_threads) > 1
