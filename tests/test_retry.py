import logging

import pytest

from src.extract.retry import call_with_retry


class _RetryableError(Exception):
    pass


class _OtherError(Exception):
    pass


def test_call_with_retry_returns_result_on_first_success():
    assert call_with_retry(lambda: 42, retryable_errors=(_RetryableError,), description="op") == 42


def test_call_with_retry_retries_retryable_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise _RetryableError("transient")
        return "ok"

    result = call_with_retry(flaky, retryable_errors=(_RetryableError,), description="op")

    assert result == "ok"
    assert calls["count"] == 3


def test_call_with_retry_raises_after_exhausting_max_retries(monkeypatch):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    calls = {"count": 0}

    def always_fails():
        calls["count"] += 1
        raise _RetryableError("still failing")

    with pytest.raises(_RetryableError):
        call_with_retry(always_fails, retryable_errors=(_RetryableError,), description="op", max_retries=3)

    assert calls["count"] == 3


def test_call_with_retry_does_not_retry_non_retryable_error(monkeypatch):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    calls = {"count": 0}

    def raises_other():
        calls["count"] += 1
        raise _OtherError("permanent")

    with pytest.raises(_OtherError):
        call_with_retry(raises_other, retryable_errors=(_RetryableError,), description="op")

    assert calls["count"] == 1  # no retry attempted


def test_call_with_retry_backoff_grows_exponentially_with_jitter(monkeypatch):
    delays = []
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: delays.append(seconds))
    monkeypatch.setattr("src.extract.retry.random.uniform", lambda a, b: 0.0)  # isolate the exponential part
    calls = {"count": 0}

    def always_fails():
        calls["count"] += 1
        raise _RetryableError("failing")

    with pytest.raises(_RetryableError):
        call_with_retry(always_fails, retryable_errors=(_RetryableError,), description="op", max_retries=3)

    assert delays == [2.0, 4.0]  # base * 2^attempt for attempts 0, 1 (no sleep after the final failed attempt)


def test_call_with_retry_respects_configurable_max_retries(monkeypatch):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    calls = {"count": 0}

    def always_fails():
        calls["count"] += 1
        raise _RetryableError("failing")

    with pytest.raises(_RetryableError):
        call_with_retry(always_fails, retryable_errors=(_RetryableError,), description="op", max_retries=5)

    assert calls["count"] == 5


def test_call_with_retry_logs_each_retry_attempt(monkeypatch, caplog):
    monkeypatch.setattr("src.extract.retry.time.sleep", lambda seconds: None)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 2:
            raise _RetryableError("transient")
        return "ok"

    with caplog.at_level(logging.WARNING):
        call_with_retry(flaky, retryable_errors=(_RetryableError,), description="my_operation")

    assert any("my_operation" in r.message and "attempt 1/3" in r.message for r in caplog.records)
