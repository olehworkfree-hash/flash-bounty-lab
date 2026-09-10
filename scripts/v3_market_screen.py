#!/usr/bin/env python3
"""Bounded V2/V3 quote screen; public-state eth_call only, NEVER a trade signal."""
import argparse
import datetime as dt
import hashlib
import itertools
import json
import os
from pathlib import Path
import time
import urllib.request
from real_quorum import PROVIDERS, ALLOWED, canonical, digest, parallel, agreement, header, POOL
from rpc_transport import fetch_body
from market_screen import WETH, USDC, address, words, amount_out, premium

USDCE = '0xff970a61a04b1ca14834a43f5de4533ebddb5cc8'
TOKENS = {'USDC': USDC, 'USDC.e': USDCE}
FACTORY_V3 = '0x1f98431c8ad98523631ae4a59f267346ea31f984'
QUOTER = '0x61ffe014ba17989e743c5f6cb21bf9697530b21e'
ROUTER_V3 = '0xe592427a0aece92de3edee1f18e0157c05861564'
FACTORIES_V2 = {'uniswap-v2': '0xf1d7cc64fb4452f05c498126312ebe29f30fbcf9',
                'sushiswap-v2': '0xc35dadb65012ec5796536bd9864ed8773abc74c4'}
FEES = (100, 500, 3000, 10000)
SIZES = (10**15, 10**16, 10**17, 10**18)
ZERO = '0x' + '0'*40
LIMIT = 2*1024*1024
MAX_CALLS = 800


def uint(n, bits=256):
    if type(n) is not int or not 0 <= n < 2**bits:
        raise ValueError('ABI_INTEGER_RANGE')
    return format(n, '064x')


def addr(a):
    if not isinstance(a, str) or len(a) != 42 or not a.startswith('0x'):
        raise ValueError('ABI_ADDRESS')
    try:
        return uint(int(a[2:], 16), 160)
    except ValueError:
        raise ValueError('ABI_ADDRESS') from None


def quote_data(token_in, token_out, amount, fee):
    if amount <= 0 or token_in == token_out or fee not in FEES:
        raise ValueError('QUOTE_INPUT')
    # IQuoterV2: tuple(tokenIn, tokenOut, amountIn, fee, sqrtPriceLimitX96)
    return '0xc6a5026a' + addr(token_in) + addr(token_out) + uint(amount) + uint(fee, 24) + uint(0)


def decode_quote(raw):
    out, sqrt_after, ticks, gas = words(raw, 4)
    if out <= 0 or not 0 < sqrt_after < 2**160 or ticks >= 2**32 or gas <= 0:
        raise ValueError('QUOTE_RESULT_RANGE')
    # gasEstimate is ONLY the quoter's internal measurement, NOT total Arbitrum fees.
    return dict(amount_out=str(out), sqrt_price_after=str(sqrt_after), ticks_crossed=ticks), gas


def decode_batch(body, count):
    if len(body) > LIMIT:
        raise ValueError('RPC_RESPONSE_LIMIT')
    entries = json.loads(body)
    if not isinstance(entries, list) or len(entries) != count:
        raise ValueError('RPC_BATCH_SHAPE')
    indexed = {}
    for item in entries:
        if not isinstance(item, dict) or type(item.get('id')) is not int:
            raise ValueError('RPC_ID_TYPE')
        ident = item['id']
        if ident in indexed or ident not in range(1, count+1) or item.get('jsonrpc') != '2.0':
            raise ValueError('RPC_IDENTITY')
        if ('result' in item) == ('error' in item):
            raise ValueError('RPC_RESULT_ERROR')
        if 'error' in item:
            error = item['error']
            if not isinstance(error, dict) or type(error.get('code')) is not int:
                raise ValueError('RPC_ERROR_SHAPE')
            # No provider URLs, arbitrary prose, or raw error data in reports.
            indexed[ident] = {'ok': False, 'code': error['code']}
            # Preserve only an exact, sanitized computational-limit classification.
            # A generic -32000 (missing state, backend failure, etc.) is NOT this.
            if error['code'] == -32000 and isinstance(error.get('message'), str) and error['message'].strip().lower() == 'out of gas':
                indexed[ident]['error_kind'] = 'OUT_OF_GAS'
        else:
            value = item['result']
            if not isinstance(value, str) or not value.startswith('0x') or len(value)%2:
                raise ValueError('RPC_HEX_RESULT')
            try:
                bytes.fromhex(value[2:])
            except ValueError:
                raise ValueError('RPC_HEX_RESULT') from None
            indexed[ident] = {'ok': True, 'result': value.lower()}
    return [indexed[i] for i in range(1, count+1)]


class Reader:
    def __init__(self, label, ref):
        if label not in PROVIDERS:
            raise ValueError('PROVIDER_NOT_ALLOWED')
        self.label, self.ref, self.count = label, ref, 0

    def read(self, calls):
        if self.count + len(calls) > MAX_CALLS:
            raise ValueError('CALL_BUDGET')
        if any(m not in {'eth_call', 'eth_getCode'} or m not in ALLOWED for m, _ in calls):
            raise ValueError('READ_ONLY_POLICY')
        result = []
        for offset in range(0, len(calls), 12):
            chunk = calls[offset:offset+12]
            self.count += len(chunk)
            payload = [dict(jsonrpc='2.0', id=i, method=m, params=p) for i, (m,p) in enumerate(chunk,1)]
            req = urllib.request.Request(PROVIDERS[self.label], data=canonical(payload).encode(),
                    headers={'Content-Type': 'application/json', 'User-Agent': 'FLASH-bounded-V3-read-only/1'})
            result.extend(decode_batch(fetch_body(req, LIMIT), len(chunk)))
            time.sleep(0.15)
        return result

    def call(self, target, data):
        return ('eth_call', [dict(to=target, data=data, gas='0x989680'), self.ref])

    def code(self, target):
        return ('eth_getCode', [target, self.ref])


def require_result(item):
    if item.get('ok') is not True:
        raise ValueError('REQUIRED_STATE_READ_FAILED')
    return item['result']


def quote_stage(reader, jobs):
    results, pending, calls = {}, [], []
    for key, venue, token_in, token_out, amount in jobs:
        if amount <= 0:
            results[key] = dict(ok=False, reason='ZERO_INTERMEDIATE_OUTPUT')
        elif venue['kind'] == 'v2':
            rin = venue['weth_reserve'] if token_in == WETH else venue['usd_reserve']
            rout = venue['usd_reserve'] if token_in == WETH else venue['weth_reserve']
            out = amount_out(amount, int(rin), int(rout))
            results[key] = dict(ok=out>0, amount_out=str(out))
        else:
            pending.append(key)
            calls.append(reader.call(QUOTER, quote_data(token_in, token_out, amount, venue['fee'])))
    for key, item in zip(pending, reader.read(calls)):
        if not item['ok']:
            results[key] = dict(ok=False, reason='QUOTER_CALL_FAILED', rpc_code=item['code'])
        else:
            normalized, _ = decode_quote(item['result'])
            results[key] = dict(ok=True, **normalized)
    return results


def discover(reader):
    targets = [WETH, USDC, USDCE, POOL, FACTORY_V3, QUOTER, ROUTER_V3, *FACTORIES_V2.values()]
    checks = reader.read([reader.code(x) for x in targets])
    code_hashes = {}
    for target, item in zip(targets, checks):
        raw = require_result(item)
        if raw == '0x':
            raise ValueError('MISSING_DEPLOYMENT_CODE')
        code_hashes[target] = hashlib.sha256(bytes.fromhex(raw[2:])).hexdigest()
    checks = reader.read([reader.call(x, '0x313ce567') for x in (WETH, USDC, USDCE)] +
             [reader.call(QUOTER,'0xc45a0155'), reader.call(QUOTER,'0x4aa4a4fc'),
              reader.call(POOL,'0x074b2e43')])
    if [words(require_result(x),1)[0] for x in checks[:3]] != [18,6,6]:
        raise ValueError('DECIMALS_MISMATCH')
    if address(require_result(checks[3])) != FACTORY_V3 or address(require_result(checks[4])) != WETH:
        raise ValueError('QUOTER_IDENTITY')
    bps = words(require_result(checks[5]),1)[0]
    if not 0 <= bps <= 10000:
        raise ValueError('FLASH_FEE_RANGE')
    specs, calls = [], []
    for symbol, token in TOKENS.items():
        for fee in FEES:
            specs.append(dict(id=f'{symbol}:uniswap-v3:{fee}',kind='v3',symbol=symbol,token=token,fee=fee,factory=FACTORY_V3))
            calls.append(reader.call(FACTORY_V3, '0x1698ee82'+addr(WETH)+addr(token)+uint(fee,24)))
        for name, factory in FACTORIES_V2.items():
            specs.append(dict(id=f'{symbol}:{name}',kind='v2',symbol=symbol,token=token,fee=3000,factory=factory))
            calls.append(reader.call(factory, '0xe6a43905'+addr(WETH)+addr(token)))
    venues, excluded = [], []
    for spec, item in zip(specs, reader.read(calls)):
        pair = address(require_result(item))
        if pair == ZERO:
            excluded.append(dict(id=spec['id'],reason='POOL_NOT_DEPLOYED'))
        else:
            venues.append(dict(**spec, pool=pair))
    calls = []
    for v in venues:
        calls.extend([reader.code(v['pool']), reader.call(v['pool'],'0x0dfe1681'),
                      reader.call(v['pool'],'0xd21220a7'), reader.call(v['pool'],'0xc45a0155')])
        if v['kind']=='v3':
            calls.extend([reader.call(v['pool'],'0xddca3f43'),reader.call(v['pool'],'0x1a686502'),reader.call(v['pool'],'0x3850c7bd')])
        else:
            calls.append(reader.call(v['pool'],'0x0902f1ac'))
    raw, index, active = reader.read(calls), 0, []
    for v in venues:
        n = 7 if v['kind']=='v3' else 5
        chunk = [require_result(x) for x in raw[index:index+n]]; index += n
        code,t0,t1,factory = chunk[:4]
        t0,t1 = address(t0),address(t1)
        if code=='0x' or {t0,t1}!={WETH,v['token']} or address(factory)!=v['factory']:
            raise ValueError('POOL_IDENTITY_MISMATCH')
        v['runtime_sha256'] = hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()
        v.update(token0=t0, token1=t1)
        if v['kind']=='v3':
            fee,L = words(chunk[4],1)[0], words(chunk[5],1)[0]
            slot = words(chunk[6],7)
            if fee!=v['fee'] or L>=2**128 or slot[0]>=2**160:
                raise ValueError('V3_STATE_MISMATCH')
            v.update(liquidity=str(L), slot0_raw=chunk[6])
            if not L or not slot[0]:
                excluded.append(dict(id=v['id'], reason='ZERO_ACTIVE_LIQUIDITY')); continue
        else:
            r0,r1,stamp = words(chunk[4],3)
            if max(r0,r1)>=2**112 or stamp>=2**32:
                raise ValueError('V2_RESERVE_RANGE')
            v.update(weth_reserve=str(r0 if t0==WETH else r1), usd_reserve=str(r1 if t0==WETH else r0))
            if not r0 or not r1:
                excluded.append(dict(id=v['id'],reason='ZERO_RESERVES')); continue
        active.append(v)
    return active, excluded, code_hashes, bps


def route_rows(venues, first, second, bps, sizes):
    rows = []
    for a,b in itertools.permutations(venues,2):
        if a['token']!=b['token'] or a['pool']==b['pool']:
            continue
        for amount in sizes:
            key = (a['id'],b['id'],amount)
            leg1,leg2 = first[(a['id'],amount)], second.get(key)
            row = dict(buy=a['id'],sell=b['id'],symbol=a['symbol'],amount_in=str(amount),
                       buy_pool=a['pool'],sell_pool=b['pool'],first_quote=leg1,second_quote=leg2,
                       fee_wei=str(premium(amount,bps)),status='QUOTE_UNAVAILABLE')
            if leg1['ok'] and leg2 and leg2['ok']:
                gross = int(leg2['amount_out'])-amount-premium(amount,bps)
                row.update(gross_before_gas_wei=str(gross), status='POSITIVE_QUOTE_UNVERIFIED' if gross>0 else 'NO_EDGE_BEFORE_GAS')
            rows.append(row)
    return rows


def capture(label, q):
    reader = Reader(label,dict(blockHash=q['header']['hash'],requireCanonical=True))
    venues, excluded, hashes, bps = discover(reader)
    if bps != words(q['state']['premium_raw'],1)[0]:
        raise ValueError('PREMIUM_DISAGREEMENT')
    first = quote_stage(reader, [((v['id'],n),v,WETH,v['token'],n) for v in venues for n in SIZES])
    jobs = []
    for a,b in itertools.permutations(venues,2):
        if a['token']==b['token'] and a['pool']!=b['pool']:
            for n in SIZES:
                f = first[(a['id'],n)]
                if f['ok']:
                    jobs.append(((a['id'],b['id'],n),b,b['token'],WETH,int(f['amount_out'])))
    second = quote_stage(reader,jobs)
    if header(label,q['block_number']) != q['header']:
        raise ValueError('BLOCK_CHANGED')
    rows = route_rows(venues,first,second,bps,SIZES)
    return dict(venues=venues,excluded=excluded,deployment_runtime_sha256=hashes,premium_bps=bps,
                quote_rows=rows,rpc_state_call_count=reader.count)


def validate_quorum(q,now):
    q = dict(q)
    expected = q.pop('evidence_sha256',None)
    if digest(q)!=expected or q.get('status')!='PASS' or q.get('historical') is not False:
        raise ValueError('QUORUM_REJECTED')
    voters = q.get('state_voters',[])
    if len(voters)<2 or len(set(voters))!=len(voters) or any(x not in PROVIDERS for x in voters):
        raise ValueError('VOTERS_REJECTED')
    if not -30 <= now-int(q['header']['timestamp'],16) <= 900:
        raise ValueError('STALE_BLOCK')
    return q,expected


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True); ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    report=dict(schema='flash.v2_v3_quote_screen.v1',status='FAILED',execution_allowed=False,
                realized_pnl='0',exact_arbitrum_fee_known=False,fork_execution_verified=False,
                total_market_coverage=False,runtime_hashes_preapproved=False,
                quote_gas_used_as_total_fee=False,source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
                started_at=dt.datetime.now(dt.timezone.utc).isoformat())
    try:
        q,qd=validate_quorum(json.loads(args.quorum.read_text()),time.time())
        observations, errors=parallel(lambda label:capture(label,q),q['state_voters'])
        value,voters=agreement(observations)
        validate_quorum(json.loads(args.quorum.read_text()),time.time())
        rows=value['quote_rows']; valid=[x for x in rows if 'gross_before_gas_wei' in x]
        if not valid:
            raise ValueError('NO_SUCCESSFUL_QUOTES')
        positive=[x for x in valid if int(x['gross_before_gas_wei'])>0]
        report.update(status='PASS',block_number=q['block_number'],header=q['header'],quorum_sha256=qd,
                      voters=voters,provider_failures=errors,observations=value,rows_requested=len(rows),
                      successful_quotes=len(valid),unavailable_quotes=len(rows)-len(valid),positive_before_gas=len(positive),
                      top_quotes=sorted(valid,key=lambda r:int(r['gross_before_gas_wei']),reverse=True)[:10],
                      decision='CANDIDATES_NEED_ATOMIC_FORK_AND_FEES' if positive else 'NO_PROFITABLE_QUOTE_IN_SUCCESSFUL_SUBSET')
    except Exception as exc:
        report.update(failure_type=type(exc).__name__,failure_code=str(exc) if isinstance(exc,ValueError) else 'CAPTURE_FAILED')
    report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat(); report['sha256']=digest(report)
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(canonical({k:report[k] for k in ('status','rows_requested','successful_quotes','positive_before_gas','decision','failure_code') if k in report}))
    if report['status']!='PASS':
        raise SystemExit(1)

if __name__=='__main__':
    main()
