import os
from typing import Literal, Optional

import anthropic

Provider = Literal["anthropic", "deepseek"]

# DeepSeek exposes an Anthropic-compatible endpoint, so it needs no second SDK
# and no second retry vocabulary -- the same anthropic client, the same
# anthropic.APIConnectionError / RateLimitError that call_with_retry already
# knows about, just a different base_url and key.
DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"

# DeepSeek maps Claude model names onto its own: claude-haiku*/claude-sonnet*
# resolve to deepseek-v4-flash and claude-opus* to deepseek-v4-pro, and an
# unrecognised name silently falls back to flash. Naming the intended tier
# explicitly here keeps that mapping visible rather than accidental.
DEEPSEEK_FLASH = "claude-sonnet-5"
DEEPSEEK_PRO = "claude-opus-5"

# DeepSeek's compatibility layer does NOT support structured outputs, and
# ignores image/document content blocks. Both extraction and chunking therefore
# have to stay schema-in-prompt with client-side Pydantic validation, which is
# what src/extract/facts_extraction.py already does.
SUPPORTS_STRUCTURED_OUTPUT = {"anthropic": True, "deepseek": False}


class MissingCredential(Exception):
    """Raised when a provider is requested without its key configured.

    Named rather than a bare KeyError so the failure says which provider and
    which variable, instead of surfacing as an authentication error several
    calls later.
    """


def client_for(provider: Provider = "anthropic") -> anthropic.Anthropic:
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingCredential("ANTHROPIC_API_KEY is not set; add it to .env")
        return anthropic.Anthropic()

    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise MissingCredential("DEEPSEEK_API_KEY is not set; add it to .env")
        return anthropic.Anthropic(api_key=key, base_url=DEEPSEEK_BASE_URL)

    raise MissingCredential(f"unknown provider {provider!r}")


def model_for(provider: Provider, tier: Literal["fast", "strong"] = "fast") -> str:
    if provider == "deepseek":
        return DEEPSEEK_FLASH if tier == "fast" else DEEPSEEK_PRO
    return "claude-haiku-4-5-20251001" if tier == "fast" else "claude-sonnet-5"


def available_providers() -> list[Provider]:
    found: list[Provider] = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        found.append("anthropic")
    if os.environ.get("DEEPSEEK_API_KEY"):
        found.append("deepseek")
    return found


def resolve(provider: Optional[Provider] = None) -> Provider:
    """Pick a provider, preferring an explicit choice over what happens to be
    configured. Falls back to whatever key exists so a pilot can run before
    both are set up."""
    if provider is not None:
        return provider
    found = available_providers()
    if not found:
        raise MissingCredential(
            "no LLM credentials found; set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY in .env"
        )
    return found[0]
