from pathlib import Path

import yaml

from src.retrieve.base import SourceAdapter

DEFAULT_CONFIG_PATH = Path("config/sources.yaml")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_indices(adapters: list[SourceAdapter]) -> dict[SourceAdapter, dict[str, str]]:
    return {adapter: adapter.build_index() for adapter in adapters}
