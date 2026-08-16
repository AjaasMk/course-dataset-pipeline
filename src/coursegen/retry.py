from __future__ import annotations

import json
import logging
import random
import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

logger = logging.getLogger("coursegen.retry")

RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)


class TransportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.body = body


def transport_error_from_response(response: httpx.Response) -> TransportError:
    status = response.status_code
    body = response.text[:800]
    retry_after: float | None = None
    header = response.headers.get("retry-after")
    if header:
        try:
            retry_after = float(header)
        except ValueError:
            retry_after = None
    return TransportError(
        f"HTTP {status} from {response.request.method} {response.request.url}",
        status_code=status,
        retryable=status in RETRYABLE_STATUS,
        retry_after_seconds=retry_after,
        body=body,
    )


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, TransportError):
        return exc.retryable
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def _log(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, default=str, sort_keys=True))


def call_with_retry(
    operation: str,
    fn: Callable[[], T],
    *,
    max_retries: int = 4,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except BaseException as exc:
            retryable = is_retryable(exc)
            exhausted = attempt >= max_retries
            if not retryable or exhausted:
                _log(
                    logging.ERROR,
                    "retry.giving_up",
                    operation=operation,
                    attempt=attempt + 1,
                    max_attempts=max_retries + 1,
                    reason="exhausted" if retryable else "not_retryable",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    status_code=getattr(exc, "status_code", None),
                )
                raise

            delay = min(max_delay_seconds, base_delay_seconds * (2**attempt))
            retry_after = getattr(exc, "retry_after_seconds", None)
            if isinstance(retry_after, (int, float)):
                delay = max(delay, float(retry_after))
            delay += rand() * base_delay_seconds

            _log(
                logging.WARNING,
                "retry.scheduled",
                operation=operation,
                attempt=attempt + 1,
                max_attempts=max_retries + 1,
                error_type=type(exc).__name__,
                error=str(exc),
                status_code=getattr(exc, "status_code", None),
                delay_seconds=round(delay, 3),
            )
            sleep(delay)
            attempt += 1
