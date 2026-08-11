import json

import pytest

from src.extract.llm_chunker import (
    ChunkerResponseInvalid,
    document_text,
    is_readable,
    json_object,
    parse_response,
    slice_chunks,
)
from src.retrieve.models import Segment

_DOC = (
    "PREAMBLE\n"
    "Mechanical engineering involves scientific analysis.\n"
    "PROFESSIONAL CORE COURSES\n"
    "Thermodynamics, Fluid Mechanics, Machine Design.\n"
)


def _payload(**overrides):
    base = {
        "document_id": "DOC-1",
        "segments": [
            {
                "segment": "Curriculum",
                "section_id": "PROFESSIONAL CORE COURSES",
                "subsegments": [
                    {
                        "subsegment": "core_subjects",
                        "field_ids": ["F042"],
                        "chunks": [
                            {
                                "chunk_index": 0,
                                "char_start": _DOC.index("Thermodynamics"),
                                "char_end": _DOC.index("Thermodynamics") + len("Thermodynamics, Fluid Mechanics, Machine Design."),
                                "heading_path": ["PROFESSIONAL CORE COURSES"],
                                "block_type": "paragraph",
                                "page_start": 1,
                                "page_end": 1,
                                "course_scope": "course_specific",
                                "segment_confidence": 0.95,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return json.dumps(base)


def test_chunk_text_is_sliced_from_the_source_not_taken_from_the_model():
    # The whole reason the contract returns offsets: quoted evidence must be
    # byte-identical to the document, or check_citations() ends up validating a
    # quote against a rewrite of the source.
    chunks = slice_chunks(parse_response(_payload()), _DOC, "DOC-1")

    assert chunks[0].text == "Thermodynamics, Fluid Mechanics, Machine Design."
    assert chunks[0].text in _DOC


def test_a_span_outside_the_document_is_dropped_not_sliced():
    # Never clamp a bad span to fit: that would hand extraction text the model
    # did not point at. Dropping costs one chunk; clamping would quietly
    # produce a wrong quote that still satisfies the citation gate.
    bad = json.loads(_payload())
    bad["segments"][0]["subsegments"][0]["chunks"][0]["char_end"] = len(_DOC) + 500

    assert slice_chunks(parse_response(json.dumps(bad)), _DOC, "DOC-1") == []


def test_inverted_offsets_are_dropped():
    bad = json.loads(_payload())
    chunk = bad["segments"][0]["subsegments"][0]["chunks"][0]
    chunk["char_start"], chunk["char_end"] = chunk["char_end"], chunk["char_start"]

    assert slice_chunks(parse_response(json.dumps(bad)), _DOC, "DOC-1") == []


def test_one_bad_span_does_not_cost_the_good_ones_beside_it():
    # The real failure this fixes: in the first pilot a single hallucinated
    # offset failed the whole document, discarding every genuine chunk found
    # alongside it. 41 of 81 documents were lost that way.
    payload = json.loads(_payload())
    chunks = payload["segments"][0]["subsegments"][0]["chunks"]
    chunks.append({**chunks[0], "chunk_index": 1, "char_start": 0, "char_end": len(_DOC) + 900})

    kept = slice_chunks(parse_response(json.dumps(payload)), _DOC, "DOC-1")

    assert len(kept) == 1
    assert kept[0].text == "Thermodynamics, Fluid Mechanics, Machine Design."


def test_an_unknown_segment_is_demoted_rather_than_failing_the_document():
    # Real labels the model produced: "Course Outcomes", "Evaluation Scheme",
    # "Examination Pattern". Plausible document headings, but not routing
    # labels -- and the boundaries around them are still sound.
    payload = json.loads(_payload())
    payload["segments"][0]["segment"] = "Evaluation Scheme"

    parsed = parse_response(json.dumps(payload), strict=False)

    assert parsed.segments[0].segment == "unclassified"
    # Recorded in its own field: section_id often already holds a real source
    # anchor, and the rejected label is evidence about the document.
    assert parsed.segments[0].raw_segment == "Evaluation Scheme"


def test_an_unknown_segment_still_raises_in_strict_mode():
    payload = json.loads(_payload())
    payload["segments"][0]["segment"] = "Evaluation Scheme"

    with pytest.raises(ChunkerResponseInvalid):
        parse_response(json.dumps(payload), strict=True)


def test_a_table_header_returned_as_cells_is_joined():
    payload = json.loads(_payload())
    payload["segments"][0]["subsegments"][0]["chunks"][0]["table_header"] = ["Code", "Title", "Credits"]

    chunks = slice_chunks(parse_response(json.dumps(payload)), _DOC, "DOC-1")

    assert chunks[0].table_header == "Code | Title | Credits"


def test_json_wrapped_in_prose_is_still_recovered():
    # Measured live: some responses opened with "I need to see..." before the
    # object. Losing a document over a preamble is a cosmetic failure.
    noisy = "I need to see the document text first.\n" + _payload() + "\nHope that helps."

    assert parse_response(noisy).segments[0].segment == "Curriculum"


def test_a_segment_outside_the_canonical_vocabulary_is_rejected():
    # The model must not invent segment names: a chunk labelled with anything
    # the pipeline does not know cannot route to extraction.
    bad = json.loads(_payload())
    bad["segments"][0]["segment"] = "Course Snapshot"

    with pytest.raises(ChunkerResponseInvalid):
        parse_response(json.dumps(bad))


def test_unclassified_is_accepted_as_an_honest_gap():
    payload = json.loads(_payload())
    payload["segments"][0]["segment"] = "unclassified"

    parsed = parse_response(json.dumps(payload))

    assert parsed.segments[0].segment == "unclassified"


def test_every_canonical_retrieval_segment_is_accepted():
    for segment in Segment:
        payload = json.loads(_payload())
        payload["segments"][0]["segment"] = segment.value
        # Only the 14 retrieval segments are valid chunker output; the four
        # explanatory ones have no F-fields and no retrieval intent.
        from src.retrieve.models import RETRIEVAL_SEGMENTS

        if segment in RETRIEVAL_SEGMENTS:
            assert parse_response(json.dumps(payload)).segments[0].segment == segment.value


def test_a_markdown_fenced_response_is_still_parsed():
    fenced = "```json\n" + _payload() + "\n```"

    assert parse_response(fenced).segments[0].segment == "Curriculum"


def test_malformed_json_raises_a_named_error_not_a_decode_error():
    with pytest.raises(ChunkerResponseInvalid):
        parse_response("not json at all")


def test_chunks_carry_the_segment_subsegment_and_heading_path():
    chunks = slice_chunks(parse_response(_payload()), _DOC, "DOC-1")

    only = chunks[0]
    assert only.segment_id == Segment.CURRICULUM
    assert only.subsegment == "core_subjects"
    assert only.field_ids == ["F042"]
    assert only.heading_path == ["PROFESSIONAL CORE COURSES"]
    assert only.course_scope == "course_specific"


def test_chunk_content_hash_is_deterministic_for_the_same_text():
    first = slice_chunks(parse_response(_payload()), _DOC, "DOC-1")
    second = slice_chunks(parse_response(_payload()), _DOC, "DOC-1")

    assert first[0].content_hash == second[0].content_hash
    assert first[0].content_hash


def test_an_empty_slice_is_dropped_rather_than_stored():
    # A zero-width span carries no evidence; storing it would create a chunk
    # that can never support a citation.
    payload = json.loads(_payload())
    chunk = payload["segments"][0]["subsegments"][0]["chunks"][0]
    chunk["char_end"] = chunk["char_start"]

    assert slice_chunks(parse_response(json.dumps(payload)), _DOC, "DOC-1") == []


def test_document_text_joins_pdf_pages_and_reports_page_offsets():
    from src.extract.models import PageText

    text, pages = document_text([PageText(page_number=1, text="alpha"), PageText(page_number=2, text="beta")])

    assert "alpha" in text and "beta" in text
    assert pages[0][0] == 1 and text[pages[0][1]: pages[0][2]].strip() == "alpha"
    assert pages[1][0] == 2 and text[pages[1][1]: pages[1][2]].strip() == "beta"


def test_a_boundary_landing_mid_word_is_snapped_outward():
    # Measured on the real pilot: 66% of chunks began mid-word and 46% ended
    # mid-word, because character offsets are the one thing a language model
    # counts badly. "Concept of Minor Degree" arrived as "ept of Minor Degree".
    # Snapping is deterministic and done on our side, so the model's weakness
    # never reaches a citation.
    from src.extract.llm_chunker import snap_to_word_boundaries

    text = "Concept of Minor Degree shall apply to all branches."
    start, end = snap_to_word_boundaries(text, text.index("cept"), text.index("branch") + 3)

    assert text[start:end].startswith("Concept")
    assert text[start:end].endswith("branches.") or text[start:end].endswith("branches")


def test_snapping_leaves_a_clean_boundary_untouched():
    from src.extract.llm_chunker import snap_to_word_boundaries

    text = "Alpha beta gamma delta."
    start, end = snap_to_word_boundaries(text, 6, 10)

    assert (start, end) == (6, 10)


def test_snapping_will_not_run_away_from_the_requested_span():
    # A boundary inside a very long unbroken run must not drag the chunk far
    # from where the model actually pointed.
    from src.extract.llm_chunker import snap_to_word_boundaries

    text = "x" * 400 + " end"
    start, end = snap_to_word_boundaries(text, 200, 260)

    assert start >= 200 - 64 and end <= 260 + 64


def test_sliced_chunks_are_snapped_and_stay_verbatim():
    payload = json.loads(_payload())
    chunk = payload["segments"][0]["subsegments"][0]["chunks"][0]
    chunk["char_start"] = _DOC.index("Thermodynamics") + 4  # mid-word
    chunks = slice_chunks(parse_response(json.dumps(payload)), _DOC, "DOC-1")

    assert chunks[0].text.startswith("Thermodynamics")
    assert chunks[0].text in _DOC


def test_json_object_ignores_a_brace_inside_echoed_prose():
    # The real failure this replaced: the model echoed part of the source
    # document, that echo contained a brace, and first-brace-to-last-brace
    # sliced a fragment that was not JSON.
    raw = (
        "Model Curriculum for Undergraduate Degree\n"
        'the notation {x} appears in the source text\n'
        "Given the very limited grounded info, I'll produce output.\n\n"
        '{"standard_course_name": "Mechanical Engineering", "citations": []}'
    )
    assert json.loads(json_object(raw))["standard_course_name"] == "Mechanical Engineering"


def test_json_object_keeps_braces_inside_string_values():
    raw = 'preface\n{"quoted_evidence": "a } brace inside a string", "n": 1}'
    parsed = json.loads(json_object(raw))
    assert parsed["quoted_evidence"] == "a } brace inside a string"
    assert parsed["n"] == 1


def test_json_object_returns_input_unchanged_when_no_object_parses():
    assert json_object("no json here at all") == "no json here at all"


@pytest.mark.parametrize(
    "body",
    [
        "............................................................... 33",
        "  42  ",
        "| 12 | 4 | 3.5 | 88 |",
    ],
)
def test_is_readable_rejects_page_furniture(body):
    assert not is_readable(body)


@pytest.mark.parametrize(
    "body",
    [
        "Thermodynamics and Fluid Mechanics",
        "Course Code: ME201 | Credits: 4",
        "Minimum qualification is a pass in Class 12.",
    ],
)
def test_is_readable_keeps_short_real_content(body):
    assert is_readable(body)
