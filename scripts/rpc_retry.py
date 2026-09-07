"""Bounded retries for public read-only RPC transport, without logging URLs."""
import time
import urllib.error
import urllib.request


def bounded_urlopen(req, timeout=20, *, opener=None, sleeper=None):
    opener = opener or urllib.request.urlopen
    sleeper = sleeper or time.sleep
    for attempt in range(3):
        try:
            return opener(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            raw = exc.headers.get("Retry-After", "") if exc.headers else ""
            if raw and not raw.isdigit():
                raise ValueError("RPC_RETRY_AFTER_NOT_NUMERIC") from None
            delay = max(2 ** (attempt + 1), int(raw or "0"))
            if delay > 30:
                raise ValueError("RPC_RETRY_AFTER_EXCEEDS_BUDGET") from None
            exc.close()
            sleeper(delay)
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
            sleeper(2 ** (attempt + 1))
    raise ValueError("RPC_RETRY_BUDGET_EXHAUSTED")
