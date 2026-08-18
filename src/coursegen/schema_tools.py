from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .chunks import Chunk

PROVIDER_UNSUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {"$schema", "$id", "format", "uniqueItems"}
)


class SchemaError(RuntimeError):
    pass


@lru_cache(maxsize=8)
def load_root_schema(path: Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        schema: dict[str, Any] = json.load(handle)
    if "properties" not in schema:
        raise SchemaError(f"{path} has no top-level properties")
    return schema


def chunk_schema(root: dict[str, Any], chunk: Chunk) -> dict[str, Any]:
    root_properties = root["properties"]
    root_required = set(root.get("required", ()))

    missing = [name for name in chunk.properties if name not in root_properties]
    if missing:
        raise SchemaError(f"chunk {chunk.key!r} names properties absent from the root schema: {missing}")

    schema: dict[str, Any] = {
        "$schema": root.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "title": f"{root.get('title', 'Course')}::{chunk.key}",
        "type": "object",
        "additionalProperties": False,
        "required": [name for name in chunk.properties if name in root_required],
        "properties": {name: copy.deepcopy(root_properties[name]) for name in chunk.properties},
    }
    for path in chunk.derived_paths:
        _remove_path(schema, path)
    return schema


def pin_curriculum_years(schema: dict[str, Any], count: int) -> dict[str, Any]:
    curriculum = schema.get("properties", {}).get("curriculum")
    if not isinstance(curriculum, dict):
        return schema
    years = curriculum.get("properties", {}).get("years")
    if not isinstance(years, dict):
        raise SchemaError("curriculum has no 'years' array to pin")
    floor, ceiling = years.get("minItems"), years.get("maxItems")
    if isinstance(floor, int) and count < floor:
        raise SchemaError(f"cannot pin curriculum.years to {count}; the schema allows at least {floor}")
    if isinstance(ceiling, int) and count > ceiling:
        raise SchemaError(f"cannot pin curriculum.years to {count}; the schema allows at most {ceiling}")
    years["minItems"] = count
    years["maxItems"] = count
    item = years.get("items")
    if isinstance(item, dict):
        year_number = item.get("properties", {}).get("year")
        if isinstance(year_number, dict):
            year_number["maximum"] = count
    return schema


def relax_for_provider(schema: dict[str, Any]) -> dict[str, Any]:
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: walk(value)
                for key, value in node.items()
                if key not in PROVIDER_UNSUPPORTED_KEYWORDS
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(copy.deepcopy(schema))


def _remove_path(schema: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    node = schema
    for part in parts[:-1]:
        properties = node.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            raise SchemaError(f"cannot remove {dotted!r}: {part!r} is not a schema property")
        node = properties[part]
    leaf = parts[-1]
    properties = node.get("properties")
    if not isinstance(properties, dict) or leaf not in properties:
        raise SchemaError(f"cannot remove {dotted!r}: {leaf!r} is not a schema property")
    del properties[leaf]
    required = node.get("required")
    if isinstance(required, list) and leaf in required:
        required.remove(leaf)


def covered_properties(chunks: tuple[Chunk, ...], injected: tuple[str, ...]) -> set[str]:
    covered: set[str] = set(injected)
    for chunk in chunks:
        covered.update(chunk.properties)
    return covered
