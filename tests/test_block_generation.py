import json

import pytest

from src.extract.block_schemas import (
    ADVISORY_BLOCK_SCHEMAS,
    DERIVED_BLOCKS,
    schema_for_block,
)
from src.extract.fallback_generation import generate_block
from src.facts.generated import GenerationReason, Provenance


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [_Block(text)]


class _Client:
    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        self.last = kwargs
        return _Response(self._text)


def test_every_advisory_block_in_the_page_map_has_a_schema():
    block_map = json.loads(
        open("docs/specs/page-block-map.json", encoding="utf-8").read()
    )
    advisory = {b["block"] for b in block_map["blocks"] if b["producer"] == "advisory"}
    assert advisory == set(ADVISORY_BLOCK_SCHEMAS)


def test_derived_blocks_refuse_to_be_generated():
    # A derived block is computed from facts already held. Generating it would
    # invent data that exists, which is worse than leaving it empty.
    for block in DERIVED_BLOCKS:
        with pytest.raises(KeyError):
            schema_for_block(block)


def test_a_generated_block_records_that_no_source_could_exist():
    client = _Client('{"faqs": [{"question": "q", "answer": "a"}]}')

    record = generate_block(
        "bsc_psychology", "BSc Psychology", "faq", client=client
    )

    assert record.provenance is Provenance.GENERATED
    assert record.reason is GenerationReason.NO_ATOMIC_SOURCE_EXISTS
    assert record.sources_attempted == []
    assert record.citations == []
    assert record.fields["faqs"][0]["question"] == "q"


def test_a_generated_block_survives_a_prose_preamble():
    client = _Client('Here is the section.\n{"fit_statements": ["a", "b", "c"]}')

    record = generate_block(
        "bsc_psychology", "BSc Psychology", "hero.fit_panel", client=client
    )

    assert record.fields["fit_statements"] == ["a", "b", "c"]


def test_a_generated_block_drops_any_citations_the_model_invents():
    client = _Client('{"questions": ["q"], "citations": [{"field_id": "F1"}]}')

    record = generate_block(
        "bsc_psychology", "BSc Psychology", "parent_corner", client=client
    )

    assert record.citations == []
    assert "citations" not in record.fields


def test_every_segment_a_block_needs_has_a_generation_schema():
    # The page cannot have gaps if a block's segment has no shape to generate
    # into. This fails the moment a new block or segment is added without one.
    from src.extract.segment_schemas import SEGMENT_SCHEMAS

    block_map = json.loads(
        open("docs/specs/page-block-map.json", encoding="utf-8").read()
    )
    needed = {
        segment
        for block in block_map["blocks"]
        if block["producer"] in ("retrieval", "explanatory")
        for segment in block["segments"]
    }
    assert needed <= set(SEGMENT_SCHEMAS), sorted(needed - set(SEGMENT_SCHEMAS))
