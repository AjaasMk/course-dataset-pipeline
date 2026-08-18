from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MAX_SEARCH_DOMAINS = 20
SUPPORTED_CURRENCIES = frozenset({"INR", "USD", "GBP", "EUR", "AED"})


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in _env(name).split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    perplexity_api_key: str
    perplexity_preset: str
    perplexity_model: str
    perplexity_base_url: str
    max_output_tokens: int
    request_interval_seconds: float
    search_domains: tuple[str, ...]
    search_recency: str
    allow_unknown_discipline: bool
    include_schema_in_prompt: bool
    region: str
    currency: str
    request_timeout_seconds: float
    transport_max_retries: int
    transport_backoff_base_seconds: float
    transport_backoff_max_seconds: float
    generation_max_attempts: int
    schema_path: Path
    domains_path: Path
    artifacts_dir: Path
    review_dir: Path
    laravel_endpoint: str
    laravel_token: str
    laravel_method: str
    laravel_payload_key: str
    laravel_auth_header: str
    laravel_auth_scheme: str

    def require_publish_target(self) -> tuple[str, str]:
        if not self.laravel_endpoint:
            raise ConfigError("LARAVEL_ENDPOINT is not set")
        if not self.laravel_token:
            raise ConfigError("LARAVEL_API_TOKEN is not set")
        return self.laravel_endpoint, self.laravel_token

    def require_api_key(self) -> str:
        if not self.perplexity_api_key:
            raise ConfigError("PERPLEXITY_API_KEY is not set")
        return self.perplexity_api_key


def load_settings() -> Settings:
    domains = _env_csv("SEARCH_DOMAINS")
    if len(domains) > MAX_SEARCH_DOMAINS:
        raise ConfigError(
            f"SEARCH_DOMAINS holds {len(domains)} entries; the Perplexity search filter accepts "
            f"at most {MAX_SEARCH_DOMAINS}"
        )

    currency = _env("CURRENCY", "INR").upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ConfigError(f"CURRENCY must be one of {sorted(SUPPORTED_CURRENCIES)}, got {currency!r}")

    generation_max_attempts = _env_int("GENERATION_MAX_ATTEMPTS", 3)
    if generation_max_attempts < 1:
        raise ConfigError("GENERATION_MAX_ATTEMPTS must be at least 1")

    transport_max_retries = _env_int("TRANSPORT_MAX_RETRIES", 4)
    if transport_max_retries < 0:
        raise ConfigError("TRANSPORT_MAX_RETRIES must not be negative")

    return Settings(
        perplexity_api_key=_env("PERPLEXITY_API_KEY"),
        perplexity_preset=_env("PERPLEXITY_PRESET", "fast"),
        perplexity_model=_env("PERPLEXITY_MODEL"),
        perplexity_base_url=_env("PERPLEXITY_BASE_URL", "https://api.perplexity.ai"),
        max_output_tokens=_env_int("MAX_OUTPUT_TOKENS", 8000),
        request_interval_seconds=_env_float("REQUEST_INTERVAL_SECONDS", 1.5),
        search_domains=domains,
        search_recency=_env("SEARCH_RECENCY", "year"),
        allow_unknown_discipline=_env("ALLOW_UNKNOWN_DISCIPLINE", "false").lower()
        in {"1", "true", "yes"},
        include_schema_in_prompt=_env("INCLUDE_SCHEMA_IN_PROMPT", "false").lower()
        in {"1", "true", "yes"},
        region=_env("REGION", "India"),
        currency=currency,
        request_timeout_seconds=_env_float("REQUEST_TIMEOUT_SECONDS", 120.0),
        transport_max_retries=transport_max_retries,
        transport_backoff_base_seconds=_env_float("TRANSPORT_BACKOFF_BASE_SECONDS", 2.0),
        transport_backoff_max_seconds=_env_float("TRANSPORT_BACKOFF_MAX_SECONDS", 60.0),
        generation_max_attempts=generation_max_attempts,
        schema_path=Path(_env("SCHEMA_PATH", str(PROJECT_ROOT / "schema" / "course.schema.json"))),
        domains_path=Path(_env("DOMAINS_PATH", str(PROJECT_ROOT / "config" / "domains.json"))),
        artifacts_dir=Path(_env("ARTIFACTS_DIR", str(PROJECT_ROOT / "artifacts"))),
        review_dir=Path(_env("REVIEW_DIR", str(PROJECT_ROOT / "artifacts" / "_review"))),
        laravel_endpoint=_env("LARAVEL_ENDPOINT"),
        laravel_token=_env("LARAVEL_API_TOKEN"),
        laravel_method=_env("LARAVEL_METHOD", "POST").upper(),
        laravel_payload_key=_env("LARAVEL_PAYLOAD_KEY"),
        laravel_auth_header=_env("LARAVEL_AUTH_HEADER", "Authorization"),
        laravel_auth_scheme=_env("LARAVEL_AUTH_SCHEME", "Bearer"),
    )
