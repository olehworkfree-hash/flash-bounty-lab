#!/usr/bin/env python3
"""Bounded read-only retry adapter. Does not weaken quorum or CI gates."""
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
            time.sleep(2 * (attempt + 1))
        except (TimeoutError, urllib.error.URLError) as exc:
            print('RPC_NETWORK_FAILURE provider=' + provider + ' method=' + method + ' attempt=' + str(attempt + 1), flush=True)
            if attempt == 2: raise RuntimeError('RPC_TIMEOUT:' + provider + ':' + method) from None
            time.sleep(2 * (attempt + 1))
fork_ci.rpc = retry_rpc
raise SystemExit(fork_ci.main())
