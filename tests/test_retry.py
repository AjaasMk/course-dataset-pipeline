from __future__ import annotations

import httpx
import pytest

from coursegen.retry import (
    RETRYABLE_STATUS,
    TransportError,
    call_with_retry,
    is_retryable,
    transport_error_from_response,
)


class Recorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.perplexity.ai/chat/completions")
    return httpx.Response(status, request=request, headers=headers or {}, text="body")


def test_succeeds_without_sleeping() -> None:
    sleep = Recorder()
    assert call_with_retry("op", lambda: "ok", sleep=sleep) == "ok"
    assert sleep.delays == []


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS))
def test_retryable_statuses_are_retried(status: int) -> None:
    assert transport_error_from_response(_response(status)).retryable


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(status: int) -> None:
    sleep = Recorder()
    error = transport_error_from_response(_response(status))
    assert not error.retryable

    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        raise error

    with pytest.raises(TransportError):
        call_with_retry("op", fn, max_retries=4, sleep=sleep)
    assert calls["n"] == 1
    assert sleep.delays == []


def test_connection_errors_are_retryable() -> None:
    assert is_retryable(httpx.ConnectError("boom"))
    assert is_retryable(httpx.ReadTimeout("boom"))
    assert not is_retryable(ValueError("boom"))


def test_backoff_is_exponential_with_jitter() -> None:
    sleep = Recorder()
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] <= 3:
            raise httpx.ConnectError("boom")
        return "ok"

    assert call_with_retry(
        "op", fn, max_retries=4, base_delay_seconds=2.0, sleep=sleep, rand=lambda: 0.5
    ) == "ok"
    assert sleep.delays == [2.0 + 1.0, 4.0 + 1.0, 8.0 + 1.0]


def test_backoff_is_capped() -> None:
    sleep = Recorder()

    def fn() -> None:
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        call_with_retry(
            "op", fn, max_retries=6, base_delay_seconds=2.0, max_delay_seconds=10.0,
            sleep=sleep, rand=lambda: 0.0,
        )
    assert sleep.delays == [2.0, 4.0, 8.0, 10.0, 10.0, 10.0]


def test_retry_after_header_raises_the_floor() -> None:
    sleep = Recorder()
    error = transport_error_from_response(_response(429, {"retry-after": "30"}))
    assert error.retry_after_seconds == 30.0

    def fn() -> None:
        raise error

    with pytest.raises(TransportError):
        call_with_retry("op", fn, max_retries=1, base_delay_seconds=2.0, sleep=sleep, rand=lambda: 0.0)
    assert sleep.delays == [30.0]


def test_max_retries_is_honoured() -> None:
    sleep = Recorder()
    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        call_with_retry("op", fn, max_retries=2, sleep=sleep, rand=lambda: 0.0)
    assert calls["n"] == 3
    assert len(sleep.delays) == 2


def test_zero_retries_means_one_attempt() -> None:
    sleep = Recorder()
    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        call_with_retry("op", fn, max_retries=0, sleep=sleep)
    assert calls["n"] == 1
