import pytest

from src.extract.llm_clients import (
    DEEPSEEK_BASE_URL,
    SUPPORTS_STRUCTURED_OUTPUT,
    MissingCredential,
    available_providers,
    client_for,
    model_for,
    resolve,
)


def test_deepseek_client_points_at_the_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    client = client_for("deepseek")

    assert str(client.base_url).rstrip("/") == DEEPSEEK_BASE_URL


def test_anthropic_client_keeps_the_default_endpoint(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    client = client_for("anthropic")

    assert "deepseek" not in str(client.base_url)


@pytest.mark.parametrize("provider,var", [("deepseek", "DEEPSEEK_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")])
def test_a_missing_key_names_the_provider_and_the_variable(provider, var, monkeypatch):
    # A bare authentication failure several calls later is much harder to act
    # on than a named error at construction time.
    monkeypatch.delenv(var, raising=False)

    with pytest.raises(MissingCredential) as raised:
        client_for(provider)

    assert var in str(raised.value)


def test_deepseek_model_names_are_the_claude_aliases_it_maps_from():
    # DeepSeek's compatibility layer resolves claude-sonnet*/claude-haiku* to
    # deepseek-v4-flash and claude-opus* to deepseek-v4-pro, and silently falls
    # back to flash for anything unrecognised. Sending a name it maps knowingly
    # keeps the tier deliberate rather than accidental.
    assert "claude" in model_for("deepseek", "fast")
    assert "claude" in model_for("deepseek", "strong")
    assert model_for("deepseek", "fast") != model_for("deepseek", "strong")


def test_anthropic_fast_tier_is_haiku_not_sonnet():
    assert "haiku" in model_for("anthropic", "fast")
    assert "sonnet" in model_for("anthropic", "strong")


def test_deepseek_is_recorded_as_not_supporting_structured_output():
    # Both chunking and extraction must stay schema-in-prompt with client-side
    # validation, because the compatibility layer does not implement structured
    # outputs. Recording it here keeps the constraint checkable in code.
    assert SUPPORTS_STRUCTURED_OUTPUT["deepseek"] is False
    assert SUPPORTS_STRUCTURED_OUTPUT["anthropic"] is True


def test_resolve_prefers_an_explicit_provider_over_what_is_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")

    assert resolve("deepseek") == "deepseek"


def test_resolve_falls_back_to_whichever_key_exists(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")

    assert resolve() == "deepseek"
    assert available_providers() == ["deepseek"]


def test_resolve_raises_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(MissingCredential):
        resolve()
