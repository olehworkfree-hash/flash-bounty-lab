"""Bounded HTTP retries for allowlisted, read-only RPC requests; no redirects."""
import time
import urllib.error
import urllib.request

RETRY_STATUS = {429, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 8.0

class SafeTransportError(RuntimeError):
    """Message contains a fixed code, never the endpoint or a response body."""

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafeTransportError('RPC_REDIRECT_REJECTED')

def fetch_body(req, limit, *, opener=None, sleep=time.sleep):
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect()).open
    for attempt in range(MAX_ATTEMPTS):
        delay = float(2 ** attempt)
        try:
            with opener(req, timeout=20) as reply:
                body = reply.read(limit + 1)
            if len(body) > limit:
                raise SafeTransportError('RPC_RESPONSE_TOO_LARGE')
            return body
        except urllib.error.HTTPError as exc:
            status = exc.code
            retry_after = exc.headers.get('Retry-After', '') if exc.headers else ''
            exc.close()
            if status not in RETRY_STATUS:
                raise SafeTransportError('RPC_HTTP_' + str(status)) from None
            # Do not hammer a server asking for a longer cooldown than our time budget.
            if retry_after:
                try:
                    requested = float(retry_after)
                except (TypeError, ValueError):
                    raise SafeTransportError('RPC_RETRY_AFTER_UNSUPPORTED') from None
                if not 0 <= requested <= MAX_RETRY_AFTER:
                    raise SafeTransportError('RPC_SERVER_COOLDOWN_EXCEEDS_BUDGET') from None
                delay = max(delay, requested)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        if attempt == MAX_ATTEMPTS - 1:
            raise SafeTransportError('RPC_TRANSPORT_EXHAUSTED') from None
        sleep(delay)
    raise SafeTransportError('RPC_TRANSPORT_EXHAUSTED')


def safe_urlopen(req, timeout=20):
    """Context-manager adapter used by the original strict batch decoder."""
    import io
    if timeout != 20:
        raise SafeTransportError('RPC_TIMEOUT_POLICY')
    return io.BytesIO(fetch_body(req, 2 * 1024 * 1024))
