import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
JITTER_SECONDS = 1.0


def call_with_retry(
    fn: Callable[[], T],
    *,
    retryable_errors: tuple[type[BaseException], ...],
    description: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> T:
    """Call fn(), retrying on retryable_errors with exponential backoff + jitter
    (2s, 4s, 8s, ... plus up to JITTER_SECONDS random) before giving up.

    Only retryable_errors get a second attempt -- everything else (auth,
    permission, billing, a real model refusal) propagates immediately,
    since retrying those either fails identically every time or masks a
    real problem rather than a transient one.
    """
    last_error: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except retryable_errors as exc:
            last_error = exc
            if attempt < max_retries - 1:
                delay = BASE_BACKOFF_SECONDS * (2**attempt) + random.uniform(0, JITTER_SECONDS)
                logger.warning(
                    "%s attempt %d/%d failed (%s: %s), retrying in %.1fs",
                    description,
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                time.sleep(delay)
    assert last_error is not None
    raise last_error
