#!/usr/bin/env python3
"""Bounded three-distinct-pool V3 cycles. Quotes are NOT earnings or trade orders."""
import argparse
import datetime as dt
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import hashlib
import v3_market_screen as v
from bounded_screen import JournalReader, atomic_json, run_workers, strict_agreement, safe_code

FEES = (100, 500, 3000)
SIZES = (10**15, 10**16, 10**17)
SELECTOR = '0xcdca1753'  # IQuoterV2.quoteExactInput(bytes,uint256)
POLICY = dict(tokens=[v.WETH, v.USDC, v.USDCE], fees=list(FEES), sizes=list(SIZES),
              hops=3, no_repeated_pool=True, max_routes=54, max_quotes=162)


def path_bytes(tokens, fees):
    if tokens not in ([v.WETH, v.USDC, v.USDCE, v.WETH], [v.WETH, v.USDCE, v.USDC, v.WETH]):
        raise ValueError('TOKEN_CYCLE')
    if len(fees) != 3 or any(type(f) is not int or f not in FEES for f in fees):
        raise ValueError('PATH_FEES')
    return bytes.fromhex(tokens[0][2:] + ''.join(format(f, '06x') + t[2:] for f,t in zip(fees,tokens[1:])))


def quote_data(tokens, fees, amount):
    if type(amount) is not int or amount not in SIZES:
        raise ValueError('QUOTE_SIZE')
    path = path_bytes(tokens, fees)
    return SELECTOR + v.uint(64) + v.uint(amount) + v.uint(len(path)) + path.hex().ljust(192, '0')


def decode_quote(raw):
    w = v.words(raw, 12)
    if w[1] != 128 or w[2] != 256 or w[4] != 3 or w[8] != 3:
        raise ValueError('QUOTE_ABI_OFFSETS')
    if w[0] <= 0 or w[3] <= 0 or any(not 0 < n < 2**160 for n in w[5:8]) or any(n >= 2**32 for n in w[9:12]):
        raise ValueError('QUOTE_ABI_RANGE')
    # Quoter-internal gas varies with execution context; never a total-fee estimate or a consensus field.
    return dict(amount_out=str(w[0]), sqrt_prices_after=[str(n) for n in w[5:8]], ticks_crossed=w[9:12])


def stable_pools(reader):
    raw = reader.read([reader.call(v.FACTORY_V3, '0x1698ee82'+v.addr(v.USDC)+v.addr(v.USDCE)+v.uint(f,24)) for f in FEES])
    pools, excluded = [], []
    for fee, value in zip(FEES, raw):
        pool = v.address(v.require_result(value))
        if pool == v.ZERO:
            excluded.append(dict(fee=fee, reason='POOL_NOT_DEPLOYED'))
            continue
        calls = [reader.code(pool)] + [reader.call(pool,sel) for sel in ('0x0dfe1681','0xd21220a7','0xc45a0155','0xddca3f43','0x1a686502','0x3850c7bd')]
        c,t0,t1,f,fee_raw,liq,slot = [v.require_result(x) for x in reader.read(calls)]
        t0,t1 = v.address(t0),v.address(t1)
        if c == '0x' or {t0,t1}!={v.USDC,v.USDCE} or v.address(f)!=v.FACTORY_V3 or v.words(fee_raw,1)[0]!=fee:
            raise ValueError('STABLE_POOL_IDENTITY')
        liquidity, state = v.words(liq,1)[0], v.words(slot,7)
        if liquidity >= 2**128 or state[0] >= 2**160:
            raise ValueError('STABLE_POOL_STATE')
        if not liquidity or not state[0]:
            excluded.append(dict(fee=fee, reason='ZERO_ACTIVE_LIQUIDITY'))
            continue
        pools.append(dict(pool=pool, fee=fee, token0=t0, token1=t1, liquidity=str(liquidity),
            slot0_raw=slot, runtime_sha256=hashlib.sha256(bytes.fromhex(c[2:])).hexdigest()))
    return pools, excluded


def routes(venues, stable):
    edges = [x for x in venues if x['kind']=='v3' and x['fee'] in FEES] + stable
    identities = set()
    for p in edges:
        addr = v.address('0x'+v.addr(p['pool']))
        if addr == v.ZERO or addr in identities:
            raise ValueError('DUPLICATE_POOL_IDENTITY')
        identities.add(addr)
    output = []
    for tokens in ([v.WETH,v.USDC,v.USDCE,v.WETH], [v.WETH,v.USDCE,v.USDC,v.WETH]):
        options = [[p for p in edges if {p['token0'],p['token1']}=={a,b}] for a,b in zip(tokens,tokens[1:])]
        for chosen in itertools.product(*options):
            fees, pools = [p['fee'] for p in chosen], [p['pool'] for p in chosen]
            path = path_bytes(tokens, fees)
            if len(set(pools)) != 3:
                raise ValueError('REPEATED_POOL')
            output.append(dict(id=hashlib.sha256(path).hexdigest(),tokens=tokens,fees=fees,pools=pools,path='0x'+path.hex()))
    if len(output)>POLICY['max_routes'] or len({r['id'] for r in output})!=len(output):
        raise ValueError('ROUTE_BOUND_OR_DUPLICATE')
    return sorted(output,key=lambda r:r['id'])


def capture(label, q, directory):
    reader=JournalReader(label,dict(blockHash=q['header']['hash'],requireCanonical=True),directory=directory)
    venues,excluded,hashes,bps=v.discover(reader)
    if bps!=v.words(q['state']['premium_raw'],1)[0]:
        raise ValueError('PREMIUM_DISAGREEMENT')
    stable,stable_excluded=stable_pools(reader)
    choices=routes(venues,stable)
    jobs=[(route,amount) for route in choices for amount in SIZES]
    if not jobs:
        raise ValueError('NO_ACTIVE_TRIANGLES')
    replies=reader.read([reader.call(v.QUOTER,quote_data(r['tokens'],r['fees'],n)) for r,n in jobs])
    rows=[]
    for (route,amount),reply in zip(jobs,replies):
        row=dict(route_id=route['id'],amount_in=str(amount),fee_wei=str(v.premium(amount,bps)),status='QUOTE_UNAVAILABLE')
        if reply['ok']:
            quote=decode_quote(reply['result'])
            gross=int(quote['amount_out'])-amount-v.premium(amount,bps)
            row.update(quote=quote,gross_before_gas_wei=str(gross),status='CANDIDATE_UNVERIFIED' if gross>0 else 'NO_EDGE_BEFORE_GAS')
        else:
            row.update(reason='QUOTER_CALL_FAILED',rpc_code=reply['code'])
        rows.append(row)
    if v.header(label,q['block_number'])!=q['header']:
        raise ValueError('BLOCK_CHANGED')
    return dict(venues=venues,stable_pools=stable,excluded=excluded,stable_excluded=stable_excluded,
                deployment_runtime_sha256=hashes,premium_bps=bps,routes=choices,quote_rows=rows,rpc_state_call_count=reader.count)


def audit(q, report):
    if report.get('quorum_sha256')!=v.digest(q) or report.get('header')!=q['header'] or report.get('block_number')!=q['block_number']:
        raise ValueError('SOURCE_LINK')
    if report.get('policy')!=POLICY or report.get('execution_allowed') is not False or report.get('realized_pnl')!='0':
        raise ValueError('RESEARCH_POLICY')
    voters=report.get('voters',[])
    if len(set(voters))<2 or len(set(voters))!=len(voters) or not set(voters)<=set(q['state_voters']):
        raise ValueError('QUOTE_QUORUM')
    obs=report['observations']
    bps=v.words(q['state']['premium_raw'],1)[0]
    if type(obs.get('premium_bps')) is not int or obs['premium_bps']!=bps:
        raise ValueError('PREMIUM_DISAGREEMENT')
    expected_routes=routes(obs['venues'],obs['stable_pools'])
    if obs['routes']!=expected_routes or not expected_routes:
        raise ValueError('ROUTE_SET')
    expected=[(r['id'],str(n)) for r in expected_routes for n in SIZES]
    if [(r['route_id'],r['amount_in']) for r in obs['quote_rows']]!=expected:
        raise ValueError('QUOTE_SET')
    valid=[]
    for row in obs['quote_rows']:
        amount=int(row['amount_in']); fee=v.premium(amount,bps)
        if row['fee_wei']!=str(fee):
            raise ValueError('FLASH_FEE')
        if row['status']=='QUOTE_UNAVAILABLE':
            if 'gross_before_gas_wei' in row or 'quote' in row or row.get('reason')!='QUOTER_CALL_FAILED' or type(row.get('rpc_code')) is not int:
                raise ValueError('UNAVAILABLE_NOT_PROFIT')
            continue
        quote=row['quote']; out=int(quote['amount_out'])
        if str(out)!=quote['amount_out'] or not 0<out<2**256 or len(quote['sqrt_prices_after'])!=3 or len(quote['ticks_crossed'])!=3:
            raise ValueError('QUOTE_RANGE')
        if any(not 0<int(x)<2**160 for x in quote['sqrt_prices_after']) or any(type(x) is not int or not 0<=x<2**32 for x in quote['ticks_crossed']):
            raise ValueError('QUOTE_ARRAY_RANGE')
        gross=out-amount-fee
        if row.get('gross_before_gas_wei')!=str(gross) or row['status']!=('CANDIDATE_UNVERIFIED' if gross>0 else 'NO_EDGE_BEFORE_GAS'):
            raise ValueError('PROFIT_ARITHMETIC')
        valid.append(row)
    positive=sum(int(r['gross_before_gas_wei'])>0 for r in valid)
    counts=dict(routes=len(expected_routes),requested=len(expected),quoted=len(valid),unavailable=len(expected)-len(valid),positive_before_gas=positive)
    if report.get('counts')!=counts:
        raise ValueError('QUOTE_COUNTS')
    return dict(status='PASS',**counts,quote_results_are_not_realized_pnl=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True); ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--worker',choices=tuple(v.PROVIDERS)); ap.add_argument('--token',default='')
    args=ap.parse_args()
    if args.worker:
        doc=dict(status='FAILED',provider=args.worker,token=args.token)
        try:
            q,qd=v.validate_quorum(json.loads(args.quorum.read_text()),time.time())
            if args.worker not in q['state_voters']:raise ValueError('PROVIDER_NOT_IN_QUORUM')
            observation=capture(args.worker,q,args.out.parent/'batches')
            v.validate_quorum(json.loads(args.quorum.read_text()),time.time())
            doc.update(status='PASS',observation=observation,quorum_sha256=qd)
        except Exception as exc:doc['failure_code']=safe_code(exc)
        atomic_json(args.out,doc); return 0 if doc['status']=='PASS' else 1
    report=dict(schema='flash.v3_triangle_screen.v1',status='FAILED',policy=POLICY,execution_allowed=False,realized_pnl='0',
        exact_arbitrum_fee_known=False,all_candidates_fork_verified=False,runtime_hashes_preapproved=False,
        gas_estimate_from_quoter_used=False,total_market_coverage=False,source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
        started_at=dt.datetime.now(dt.timezone.utc).isoformat())
    atomic_json(args.out,report)
    try:
        q,qd=v.validate_quorum(json.loads(args.quorum.read_text()),time.time())
        root=Path(tempfile.mkdtemp(prefix='triangle-providers-',dir=args.out.parent)).resolve(); token=root.name
        commands={label:[sys.executable,str(Path(__file__).resolve()),'--worker',label,'--quorum',str(args.quorum.resolve()),
                        '--out',str(root/label/'result.json'),'--token',token] for label in q['state_voters']}
        sup=run_workers(commands,root,token)
        complete={k:x['result']['observation'] for k,x in sup['workers'].items() if x['status']=='PASS' and x['result'].get('quorum_sha256')==qd}
        report.update(complete_providers=sorted(complete),provider_states={k:x['status'] for k,x in sup['workers'].items()},capture_elapsed_seconds=sup['elapsed_seconds'])
        observation,voters=strict_agreement(complete)
        v.validate_quorum(json.loads(args.quorum.read_text()),time.time())
        rows=observation['quote_rows']; valid=[r for r in rows if 'gross_before_gas_wei' in r]; positive=sum(int(r['gross_before_gas_wei'])>0 for r in valid)
        report.update(quorum_sha256=qd,header=q['header'],block_number=q['block_number'],voters=voters,observations=observation,
            counts=dict(routes=len(observation['routes']),requested=len(rows),quoted=len(valid),unavailable=len(rows)-len(valid),positive_before_gas=positive),
            top_quotes=sorted(valid,key=lambda r:int(r['gross_before_gas_wei']),reverse=True)[:5],
            decision='CANDIDATES_REQUIRE_ATOMIC_FORK_AND_TOTAL_FEES' if positive else ('NO_EDGE_IN_QUOTED_SUBSET' if valid else 'NO_SUCCESSFUL_QUOTES'))
        report['accounting_check']=audit(q,report); report['status']='PASS'
    except Exception as exc:report.update(failure_type=type(exc).__name__,failure_code=safe_code(exc))
    report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();report['sha256']=v.digest(report);atomic_json(args.out,report)
    print(json.dumps({k:report[k] for k in ('status','counts','decision','failure_code') if k in report}),flush=True)
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
