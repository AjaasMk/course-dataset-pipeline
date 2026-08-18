from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from coursegen.config import Settings  # noqa: E402
from coursegen.schema_tools import load_root_schema  # noqa: E402
from coursegen.store import read_json  # noqa: E402


@pytest.fixture(scope="session")
def schema_path() -> Path:
    return PROJECT_ROOT / "schema" / "course.schema.json"


@pytest.fixture(scope="session")
def root_schema(schema_path: Path) -> dict:
    return load_root_schema(schema_path)


@pytest.fixture()
def demo_document() -> dict:
    return read_json(PROJECT_ROOT / "schema" / "examples" / "bsc-psychology.json")


@pytest.fixture(scope="session")
def domains_path() -> Path:
    return PROJECT_ROOT / "config" / "domains.json"


@pytest.fixture()
def settings(tmp_path: Path, schema_path: Path) -> Settings:
    return Settings(
        perplexity_api_key="test-key",
        perplexity_preset="fast",
        perplexity_model="",
        max_output_tokens=8000,
        request_interval_seconds=0.0,
        perplexity_base_url="https://api.perplexity.ai",
        search_domains=("ugc.gov.in", "nirfindia.org", "nta.nic.in"),
        search_recency="year",
        allow_unknown_discipline=False,
        include_schema_in_prompt=False,
        region="India",
        currency="INR",
        request_timeout_seconds=5.0,
        transport_max_retries=2,
        transport_backoff_base_seconds=0.01,
        transport_backoff_max_seconds=0.05,
        generation_max_attempts=3,
        schema_path=schema_path,
        domains_path=tmp_path / "domains-absent.json",
        artifacts_dir=tmp_path / "artifacts",
        review_dir=tmp_path / "artifacts" / "_review",
        laravel_endpoint="",
        laravel_token="",
        laravel_method="POST",
        laravel_payload_key="",
        laravel_auth_header="Authorization",
        laravel_auth_scheme="Bearer",
    )
