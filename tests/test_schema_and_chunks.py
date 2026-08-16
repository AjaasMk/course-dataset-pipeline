from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from coursegen.chunks import CHUNKS, CHUNKS_BY_KEY, INJECTED_PROPERTIES
from coursegen.schema_tools import chunk_schema, covered_properties, relax_for_provider


def test_root_schema_is_valid(root_schema: dict) -> None:
    Draft202012Validator.check_schema(root_schema)


def test_demo_document_validates(root_schema: dict, demo_document: dict) -> None:
    errors = list(Draft202012Validator(root_schema).iter_errors(demo_document))
    assert errors == [], [(list(e.absolute_path), e.message) for e in errors]


def test_chunks_cover_every_required_property_exactly_once(root_schema: dict) -> None:
    required = set(root_schema["required"])
    covered = covered_properties(CHUNKS, INJECTED_PROPERTIES)
    assert required - covered == set(), f"unassigned required properties: {sorted(required - covered)}"
    assert covered - set(root_schema["properties"]) == set()

    seen: list[str] = []
    for chunk in CHUNKS:
        seen.extend(chunk.properties)
    seen.extend(INJECTED_PROPERTIES)
    duplicates = {name for name in seen if seen.count(name) > 1}
    assert duplicates == set(), f"properties assigned to more than one chunk: {sorted(duplicates)}"


def test_chunk_count_is_six() -> None:
    assert len(CHUNKS) == 6


def test_each_chunk_schema_is_valid_and_strict(root_schema: dict) -> None:
    for chunk in CHUNKS:
        schema = chunk_schema(root_schema, chunk)
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(chunk.properties)


def test_chunk_schemas_accept_slices_of_the_demo_document(root_schema: dict, demo_document: dict) -> None:
    for chunk in CHUNKS:
        schema = chunk_schema(root_schema, chunk)
        slice_ = {key: copy.deepcopy(demo_document[key]) for key in chunk.properties}
        for derived in chunk.derived_paths:
            node = slice_
            parts = derived.split(".")
            for part in parts[:-1]:
                node = node[part]
            node.pop(parts[-1], None)
        errors = list(Draft202012Validator(schema).iter_errors(slice_))
        assert errors == [], (chunk.key, [(list(e.absolute_path), e.message) for e in errors])


def test_derived_field_removed_from_chunk_schema(root_schema: dict) -> None:
    snapshot = next(c for c in CHUNKS if c.key == "snapshot")
    schema = chunk_schema(root_schema, snapshot)
    salary = schema["properties"]["snapshot"]["properties"]["salary"]
    assert "marker_percent" not in salary["properties"]
    assert "marker_percent" not in salary["required"]


def test_relax_for_provider_strips_unsupported_keywords(root_schema: dict) -> None:
    relaxed = relax_for_provider(root_schema)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            assert "format" not in node
            assert "$schema" not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(relaxed)


def test_relax_for_provider_does_not_mutate_input(root_schema: dict) -> None:
    before = copy.deepcopy(root_schema)
    relax_for_provider(root_schema)
    assert root_schema == before


def test_unknown_chunk_property_raises(root_schema: dict) -> None:
    from coursegen.chunks import Chunk
    from coursegen.schema_tools import SchemaError

    with pytest.raises(SchemaError):
        chunk_schema(root_schema, Chunk(key="bad", title="", properties=("not_a_property",), focus=""))


def test_provider_schema_omits_keywords_the_agent_api_rejects(root_schema: dict) -> None:
    for chunk in CHUNKS:
        relaxed = relax_for_provider(chunk_schema(root_schema, chunk))

        def walk(node: object, path: str = "") -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    assert key not in {"uniqueItems", "format", "$schema", "$id"}, (
                        f"{chunk.key}{path}.{key} is rejected by the Agent API with HTTP 400"
                    )
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    walk(item, f"{path}[{i}]")

        walk(relaxed)


def test_strict_schema_keeps_uniqueitems_for_validation(root_schema: dict) -> None:
    snapshot = chunk_schema(root_schema, CHUNKS_BY_KEY["snapshot"])
    assert snapshot["properties"]["snapshot"]["properties"]["specialisations"]["uniqueItems"] is True


def test_duplicates_are_still_rejected_by_the_strict_schema(root_schema: dict, demo_document: dict) -> None:
    import copy

    from jsonschema import Draft202012Validator

    doc = copy.deepcopy(demo_document)
    doc["snapshot"]["specialisations"][1] = doc["snapshot"]["specialisations"][0]
    errors = [e.validator for e in Draft202012Validator(root_schema).iter_errors(doc)]
    assert "uniqueItems" in errors
