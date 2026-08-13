import json

import pytest

from src.extract.models import Chunk
from src.extract.unified_extraction import (
    MIN_QUOTE_CHARS,
    client_schema,
    count_leaves,
    course_evidence,
    resolve_path,
    verify_citations,
)
from src.retrieve.models import Segment

DOC = "DOC-1"
BODY = "Semester 3 core subjects include Heat Transfer and Fluid Mechanics with 4 credits each."
INDEX = {DOC: BODY.lower()}

PAGE = {"course": {"sections": {"subjects": {"tabs": [
    {"content": {"items": [{"title": "Heat Transfer"}]}}]}}}}


def _cite(path, quote, document_id=DOC):
    return {"path": path, "document_id": document_id, "quoted_evidence": quote}


REAL_PATH = "course.sections.subjects.tabs[0].content.items[0].title"


def test_the_target_schema_is_the_clients_own_file():
    # The client's schema is the contract; generating into our shape and
    # re-mapping afterwards is what this replaced.
    schema = client_schema()
    assert "course" in schema
    assert set(schema["course"]) >= {"metadata", "hero", "quickGrid", "sections"}
    assert len(schema["course"]["sections"]) == 15


def test_a_quote_present_in_the_evidence_is_verified():
    verified, audit = verify_citations(
        PAGE, [_cite(REAL_PATH, "core subjects include Heat Transfer")], INDEX)

    assert len(verified) == 1
    assert audit["verified"] == 1 and audit["rejected"] == 0


def test_a_quote_absent_from_the_evidence_is_rejected():
    # The guard the merged call exists under: without it, "sourced" would mean
    # only that the model claimed so.
    verified, audit = verify_citations(
        PAGE, [_cite(REAL_PATH, "tuition fee is Rs 45,000 per year")], INDEX)

    assert verified == []
    assert audit["reasons"][0]["reason"] == "quote not found in that document"


def test_a_citation_naming_an_unsupplied_document_is_rejected():
    verified, audit = verify_citations(
        PAGE, [_cite(REAL_PATH, "core subjects include Heat Transfer", "DOC-NEVER")], INDEX)

    assert verified == []
    assert audit["reasons"][0]["reason"] == "document was never supplied"


def test_a_citation_pointing_at_a_path_the_page_does_not_have_is_rejected():
    verified, audit = verify_citations(
        PAGE, [_cite("course.sections.fees.table.rows[0].range",
                     "core subjects include Heat Transfer")], INDEX)

    assert verified == []
    assert audit["reasons"][0]["reason"] == "path does not exist in the produced page"


def test_a_quote_too_short_to_verify_is_rejected():
    assert len("credits") < MIN_QUOTE_CHARS
    verified, audit = verify_citations(PAGE, [_cite(REAL_PATH, "credits")], INDEX)

    assert verified == []
    assert audit["reasons"][0]["reason"] == "quote too short to verify"


def test_whitespace_differences_do_not_reject_a_real_quote():
    verified, _ = verify_citations(
        PAGE, [_cite(REAL_PATH, "core   subjects\n include Heat Transfer")], INDEX)

    assert len(verified) == 1


def test_resolve_path_walks_nested_arrays():
    found, value = resolve_path(PAGE, REAL_PATH)
    assert found and value == "Heat Transfer"


def test_fields_without_a_citation_count_as_generated():
    # The fallback: anything the documents do not support is still filled, and
    # is reported as generated rather than left empty.
    populated = count_leaves(PAGE)
    verified, _ = verify_citations(PAGE, [], INDEX)

    assert populated == 1
    assert populated - len(verified) == 1


def test_count_leaves_ignores_null_and_empty_values():
    assert count_leaves({"a": None, "b": "", "c": "x", "d": [None, "y"]}) == 2


def test_evidence_is_grouped_by_document_and_indexed():
    chunks = [
        Chunk(chunk_id=0, text="core subjects and credits", source_document="d",
              source_url="https://x/a.pdf", token_count=4, segment_id=Segment.CURRICULUM),
        Chunk(chunk_id=1, text="eligibility minimum qualification", source_document="d",
              source_url="https://x/a.pdf", token_count=3, segment_id=Segment.ELIGIBILITY),
    ]

    text, index = course_evidence(chunks)

    assert "DOCUMENT_ID:" in text and len(index) == 1
