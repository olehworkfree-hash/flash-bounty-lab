#!/usr/bin/env python3
"""Bounded read-only retries. Strict 3/3 gate, no transaction broadcast."""
import time
import urllib.error
import fork_ci

original_rpc = fork_ci.rpc
def retry_rpc(provider, method, params):
    for attempt in range(3):
        try:
            result = original_rpc(provider, method, params)
            if method == 'eth_getBlockByNumber':
                print('HEADER_PROVIDER=' + provider + ' number=' + str(result.get('number') if isinstance(result, dict) else None), flush=True)
            return result
        except urllib.error.HTTPError as exc:
            print('RPC_TRANSPORT_FAILURE provider=' + provider + ' method=' + method + ' http=' + str(exc.code) + ' attempt=' + str(attempt + 1), flush=True)
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError('RPC_UNAVAILABLE:' + provider + ':' + method + ':' + str(exc.code)) from None
            retry_after = exc.headers.get('Retry-After', '')
            wait = max(2 * (attempt + 1), int(retry_after)) if retry_after.isdigit() else 2 * (attempt + 1)
            if wait > 30: raise RuntimeError('RPC_BACKOFF_EXCEEDS_BUDGET') from None
            time.sleep(wait)
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2: raise RuntimeError('RPC_TIMEOUT:' + provider + ':' + method) from None
            time.sleep(2 * (attempt + 1))
fork_ci.rpc = retry_rpc
raise SystemExit(fork_ci.main())
