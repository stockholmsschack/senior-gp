"""Send HTTP requests with timeouts and retries to the member system and chess-results.com.

The policy follows JGP's `UpstreamClient`: a 3-second connect timeout and a
15-second read timeout per attempt. RequestException and HTTP 429 or 5xx
trigger up to two retries, after waits of 0.25 and 0.5 seconds. The caller
checks other statuses and handles errors while reading a streamed body.
These timeouts do not impose a total download deadline.
"""

from __future__ import annotations

from collections.abc import Callable
import time

import requests

CONNECT_TIMEOUT = 3.0
RESPONSE_TIMEOUT = 15.0
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.25

Sleep = Callable[[float], None]


class UpstreamRetryExhausted(RuntimeError):
    """Raised when all attempts raise RequestException or return HTTP 429 or 5xx."""


def send(session: requests.Session, method: str, url: str, *, sleep: Sleep = time.sleep,
         **options) -> requests.Response:
    """Retry request exceptions and HTTP 429 or 5xx, and return any other response.

    Raise UpstreamRetryExhausted after the last attempt.
    """
    last_failure = "unknown transient error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.request(method, url, timeout=(CONNECT_TIMEOUT, RESPONSE_TIMEOUT), **options)
        except requests.RequestException as error:
            last_failure = f"{type(error).__name__}: {error}"
        else:
            status = response.status_code
            if status != 429 and not 500 <= status <= 599:
                return response
            response.close()
            last_failure = f"HTTP {status}"
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_SECONDS * attempt)
    raise UpstreamRetryExhausted(f"{last_failure}; exhausted {MAX_ATTEMPTS} attempts")
