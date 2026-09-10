#!/usr/bin/env python3
"""Read-only, hash-pinned three-pool V3 screen. Positive quotes are NOT earnings."""
import argparse
import datetime as dt
import hashlib
import itertools
import json
import os
from pathlib import Path
import time
from market_screen import WETH, USDC, address, words, premium
from real_quorum import POOL, digest, parallel, agreement, header
from v3_market_screen import (USDCE, FACTORY_V3, QUOTER, ROUTER_V3, FEES, SIZES,
    ZERO, Reader, addr, uint, require_result, validate_quorum)

STABLES = (USDC, USDCE)
PAIRS = ((WETH, USDC), (USDC, USDCE), (USDCE, WETH))
MAX_QUOTES = 512


def packed_path(tokens, fees):
    if len(tokens) != 4 or len(fees) != 3 or tokens[0] != WETH or tokens[-1] != WETH:
        raise ValueError('CYCLE_SHAPE')
    if set(tokens[1:3]) != set(STABLES) or any(type(f) is not int or f not in FEES for f in fees):
        raise ValueError('CYCLE_ALLOWLIST')
    return bytes.fromhex(tokens[0][2:] + ''.join(format(f, '06x') + t[2:] for f, t in zip(fees, tokens[1:])))


def encode_quote(tokens, fees, amount):
    if type(amount) is not int or amount not in SIZES:
        raise ValueError('AMOUNT_ALLOWLIST')
    path = packed_path(tokens, fees)
    tail = uint(len(path)) + path.hex() + '00' * ((-len(path)) % 32)
    # IQuoterV2.quoteExactInput(bytes,uint256). No transaction is submitted.
    return '0xcdca1753' + uint(64) + uint(amount) + tail


def decode_quote(raw):
    w = words(raw, 12)  # uint,offset,offset,uint + two arrays of exactly three
    if w[1] != 128 or w[2] != 256 or w[4] != 3 or w[8] != 3 or w[0] <= 0 or w[3] <= 0:
        raise ValueError('MULTIHOP_ABI')
    if any(not 0 < x < 2**160 for x in w[5:8]) or any(x >= 2**32 for x in w[9:12]):
        raise ValueError('MULTIHOP_ARRAY_RANGE')
    # Quoter's gas estimate is deliberately NOT treated as a complete execution fee.
    return dict(amount_out=str(w[0]), sqrt_prices_after=[str(x) for x in w[5:8]], ticks_crossed=w[9:12])


def discover(reader):
    targets = (WETH, USDC, USDCE, FACTORY_V3, QUOTER, ROUTER_V3, POOL)
    hashes = {}
    for target, item in zip(targets, reader.read([reader.code(x) for x in targets])):
        code = require_result(item)
        if code == '0x':
            raise ValueError('NO_DEPLOYMENT_CODE')
        hashes[target] = hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()
    checks = reader.read([reader.call(t, '0x313ce567') for t in targets[:3]] +
        [reader.call(t, sig) for t in (QUOTER, ROUTER_V3) for sig in ('0xc45a0155', '0x4aa4a4fc')] +
        [reader.call(POOL, '0x074b2e43')])
    if [words(require_result(x), 1)[0] for x in checks[:3]] != [18, 6, 6]:
        raise ValueError('DECIMALS')
    if [address(require_result(x)) for x in checks[3:7]] != [FACTORY_V3, WETH] * 2:
        raise ValueError('PERIPHERY_IDENTITY')
    bps = words(require_result(checks[7]), 1)[0]
    if bps > 10000:
        raise ValueError('PREMIUM_RANGE')
    specs = [dict(tokens=list(pair), fee=f) for pair in PAIRS for f in FEES]
    calls = [reader.call(FACTORY_V3, '0x1698ee82' + addr(s['tokens'][0]) + addr(s['tokens'][1]) + uint(s['fee'],24)) for s in specs]
    active, excluded = [], []
    for s, item in zip(specs, reader.read(calls)):
        pool = address(require_result(item))
        if pool == ZERO:
            excluded.append(dict(**s, reason='NOT_DEPLOYED'))
        else:
            active.append(dict(**s, pool=pool))
    calls = []
    for s in active:
        calls += [reader.code(s['pool'])] + [reader.call(s['pool'], x) for x in
            ('0x0dfe1681','0xd21220a7','0xc45a0155','0xddca3f43','0x1a686502','0x3850c7bd')]
    raw, pools = reader.read(calls), []
    for i, s in enumerate(active):
        code, t0, t1, factory, fee, liq, slot = [require_result(x) for x in raw[i*7:(i+1)*7]]
        v, liquidity = words(slot, 7), words(liq, 1)[0]
        if code == '0x' or {address(t0),address(t1)} != set(s['tokens']) or address(factory) != FACTORY_V3 or words(fee,1)[0] != s['fee']:
            raise ValueError('POOL_IDENTITY')
        if liquidity >= 2**128 or v[0] >= 2**160 or v[-1] != 1:
            raise ValueError('POOL_STATE')
        if not liquidity or not v[0]:
            excluded.append(dict(**s, reason='NO_ACTIVE_LIQUIDITY'))
        else:
            pools.append(dict(**s, token0=address(t0), token1=address(t1), runtime_sha256=hashlib.sha256(bytes.fromhex(code[2:])).hexdigest(),
                liquidity=str(liquidity), slot0_raw=slot))
    return pools, excluded, hashes, bps


def build_routes(pools):
    routes = []
    for a, b in (STABLES, STABLES[::-1]):
        tokens = [WETH, a, b, WETH]
        legs = [[p for p in pools if set(p['tokens']) == {x,y}] for x,y in zip(tokens,tokens[1:])]
        for selected in itertools.product(*legs):
            if len({p['pool'] for p in selected}) != 3:
                raise ValueError('REPEATED_POOL')
            for amount in SIZES:
                routes.append(dict(tokens=tokens, fees=[p['fee'] for p in selected],
                    pools=[p['pool'] for p in selected], amount_in=str(amount)))
    if len(routes) > MAX_QUOTES or not routes:
        raise ValueError('ROUTE_BUDGET_OR_EMPTY')
    return routes


def capture(label, q):
    reader = Reader(label, dict(blockHash=q['header']['hash'], requireCanonical=True))
    pools, excluded, hashes, bps = discover(reader)
    if bps != words(q['state']['premium_raw'],1)[0]:
        raise ValueError('PREMIUM_DISAGREEMENT')
    routes = build_routes(pools)
    results = reader.read([reader.call(QUOTER, encode_quote(r['tokens'],r['fees'],int(r['amount_in']))) for r in routes])
    rows = []
    for r, item in zip(routes, results):
        row = dict(**r, status='QUOTE_UNAVAILABLE')
        if item['ok']:
            out = decode_quote(item['result'])
            fee = premium(int(r['amount_in']), bps)
            gross = int(out['amount_out']) - int(r['amount_in']) - fee
            row.update(**out, premium_wei=str(fee), gross_before_gas_wei=str(gross),
                status='POSITIVE_UNVERIFIED' if gross > 0 else 'NO_EDGE_BEFORE_GAS')
        row['candidate_id'] = digest(dict(block_hash=q['header']['hash'], route=row))
        rows.append(row)
    if header(label, q['block_number']) != q['header']:
        raise ValueError('BLOCK_CHANGED')
    return dict(pools=pools, excluded=excluded, runtime_hashes=hashes, premium_bps=bps,
        rows=rows, rpc_state_call_count=reader.count)


def select_candidates(rows):
    valid = [r for r in rows if 'gross_before_gas_wei' in r]
    if not valid:
        raise ValueError('NO_VALID_QUOTES')
    positive = sorted([r for r in valid if int(r['gross_before_gas_wei']) > 0], key=lambda r:int(r['gross_before_gas_wei']), reverse=True)
    return positive[:3] if positive else [max(valid, key=lambda r:int(r['gross_before_gas_wei']))]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    report=dict(schema='flash.triangle_screen.v1',status='FAILED',execution_allowed=False,realized_pnl='0',
        exact_arbitrum_fee_known=False,runtime_hashes_preapproved=False,source_commit=os.getenv('GITHUB_SHA'),
        run_id=os.getenv('GITHUB_RUN_ID'),started_at=dt.datetime.now(dt.timezone.utc).isoformat())
    try:
        original=json.loads(args.quorum.read_text());q,qd=validate_quorum(original,time.time())
        observations,errors=parallel(lambda label:capture(label,q),q['state_voters'])
        agreed,voters=agreement(observations);validate_quorum(original,time.time())
        rows=agreed['rows'];valid=[r for r in rows if 'gross_before_gas_wei' in r]
        chosen=select_candidates(rows);positive=sum(int(r['gross_before_gas_wei'])>0 for r in valid)
        report.update(status='PASS',header=q['header'],block_number=q['block_number'],quorum_sha256=qd,
            voters=voters,provider_failures=errors,observations=agreed,requested=len(rows),quoted=len(valid),
            positive_before_gas=positive,matched_fork_selection=chosen,
            decision='NEEDS_MATCHED_FORK_AND_FEES' if positive else 'NO_POSITIVE_TRIANGLE_IN_SUBSET')
    except Exception as exc:
        report.update(failure_type=type(exc).__name__,failure_code=str(exc) if isinstance(exc,ValueError) else 'SCREEN_FAILED')
    report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();report['sha256']=digest(report)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:report[k] for k in ('status','requested','quoted','positive_before_gas','decision','failure_code') if k in report}))
    if report['status']!='PASS':raise SystemExit(1)
if __name__=='__main__':main()
