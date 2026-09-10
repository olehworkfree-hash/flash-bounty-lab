#!/usr/bin/env python3
"""Simulate only screen-selected, exact-route candidates on local Anvil; never broadcast."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from real_quorum import PROVIDERS, digest
from market_screen import premium, words, WETH
from v3_market_screen import validate_quorum
from triangle_screen import packed_path, SIZES, STABLES, STABLE_CONFIGS, FEES, build_routes, select_candidates
from screen_integrity import integer
from bounded_screen import atomic_json
from run_v3_atomic import local


def validate_selection(quorum, screen, now):
    q, qd = validate_quorum(quorum, now)
    s = dict(screen); sd = s.pop('sha256', None)
    if digest(s) != sd or s.get('schema') != 'flash.triangle_screen.v1' or s.get('status') != 'PASS':
        raise ValueError('SCREEN_INTEGRITY')
    if s.get('source_commit') != q.get('commit') or s.get('run_id')!=q.get('run_id'): raise ValueError('RUN_SOURCE_MISMATCH')
    if s.get('execution_allowed') is not False or s.get('realized_pnl') != '0':
        raise ValueError('RESEARCH_ONLY')
    if s.get('header') != q['header'] or s.get('block_number') != q['block_number'] or s.get('quorum_sha256') != qd:
        raise ValueError('SOURCE_LINK')
    voters=s.get('voters',[])
    if len(voters)<2 or len(set(voters))!=len(voters) or not set(voters)<=set(q['state_voters']):
        raise ValueError('SCREEN_QUORUM')
    rows=s['observations']['rows'];pools=s['observations']['pools']
    bps=s['observations']['premium_bps']
    if bps != words(q['state']['premium_raw'],1)[0] or type(bps) is not int or not 0<=bps<=10000:
        raise ValueError('PREMIUM_LINK')
    stable_pair=tuple(s['observations'].get('stable_pair',STABLES))
    fee_tiers=s['observations'].get('fee_tiers',list(FEES))
    if stable_pair not in STABLE_CONFIGS.values() or not fee_tiers or len(set(fee_tiers))!=len(fee_tiers) or any(type(f) is not int or f not in FEES for f in fee_tiers):
        raise ValueError('DISCOVERY_SCOPE')
    if not 3<=len(pools)<=12 or len({p['pool'] for p in pools})!=len(pools): raise ValueError('POOL_SET')
    for p in pools:
        if p['fee'] not in fee_tiers or len(p['tokens'])!=2 or len(set(p['tokens']))!=2 or not set(p['tokens'])<=set((WETH,*stable_pair)):
            raise ValueError('POOL_SCOPE')
    expected={digest(r) for r in build_routes(pools,stable_pair)}
    ids=set(); routes_seen=set(); valid=[]
    for row in rows:
        r=dict(row);ident=r.pop('candidate_id',None)
        if digest(dict(block_hash=q['header']['hash'],route=r))!=ident or ident in ids:
            raise ValueError('CANDIDATE_ID')
        ids.add(ident);packed_path(r['tokens'],r['fees'])
        amount=integer(r['amount_in'])
        if amount not in SIZES or len(r['pools'])!=3 or len(set(r['pools']))!=3:
            raise ValueError('AMOUNT_OR_POOLS')
        route_key=digest({k:r[k] for k in ('tokens','fees','pools','amount_in')})
        if route_key not in expected or route_key in routes_seen: raise ValueError('ROUTE_GRID')
        routes_seen.add(route_key)
        for a,b,fee,pool in zip(r['tokens'],r['tokens'][1:],r['fees'],r['pools']):
            if not any(p['pool']==pool and p['fee']==fee and set(p['tokens'])=={a,b} for p in pools):
                raise ValueError('POOL_LINK')
        if 'gross_before_gas_wei' in r:
            fee=premium(amount,bps);out=integer(r['amount_out'])
            if out<=0 or integer(r['premium_wei'])!=fee or integer(r['gross_before_gas_wei'],signed=True)!=out-amount-fee:
                raise ValueError('QUOTE_ARITHMETIC')
            if r['status']!=('POSITIVE_UNVERIFIED' if out-amount-fee>0 else 'NO_EDGE_BEFORE_GAS'): raise ValueError('QUOTE_STATUS')
            valid.append(row)
        elif r.get('status')!='QUOTE_UNAVAILABLE' or any(k in r for k in ('amount_out','premium_wei')): raise ValueError('UNAVAILABLE_QUOTE')
    if routes_seen!=expected: raise ValueError('INCOMPLETE_ROUTE_GRID')
    if any(type(s[k]) is not int for k in ('requested','quoted','positive_before_gas')): raise ValueError('SCREEN_COUNT_TYPE')
    if not 0<len(rows)<=512 or len(rows)!=s['requested'] or len(valid)!=s['quoted'] or sum(int(r['gross_before_gas_wei'])>0 for r in valid)!=s['positive_before_gas']:
        raise ValueError('SCREEN_COUNTS')
    selected=select_candidates(rows)
    if s.get('matched_fork_selection')!=selected:
        raise ValueError('SELECTION_CHANGED')
    return q,s,sd,selected


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True);ap.add_argument('--screen',type=Path,required=True);ap.add_argument('--out-dir',type=Path,required=True)
    args=ap.parse_args();root=args.out_dir;root.mkdir(parents=True,exist_ok=True)
    report=dict(schema='flash.matched_triangle_fork.v1',status='FAILED',execution_allowed=False,realized_pnl='0',
        user_funds_used=False,mainnet_broadcast=False,exact_arbitrum_fee_known=False,local_chain_id=31337,
        tests_include_local_prefund=True,tests=[],source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'))
    proc=None
    try:
        q,s,sd,selected=validate_selection(json.loads(args.quorum.read_text()),json.loads(args.screen.read_text()),time.time())
        if os.getenv('GITHUB_SHA') and s['source_commit']!=os.getenv('GITHUB_SHA'):
            raise ValueError('SOURCE_COMMIT_MISMATCH')
        report.update(block_number=q['block_number'],block_hash=q['header']['hash'],screen_sha256=sd,
            selected_candidate_ids=[r['candidate_id'] for r in selected],all_screened_candidates_fork_verified=False)
        ready=False
        for label in ['alchemy-public','publicnode','arbitrum-official']:
            if label not in s['voters']:continue
            with (root/f'anvil-triangle-{label}.log').open('w') as log:
                proc=subprocess.Popen(['anvil','--fork-url',PROVIDERS[label],'--fork-block-number',str(q['block_number']),
                    '--hardfork','shanghai','--chain-id','31337','--host','127.0.0.1','--port','8547','--silent'],stdout=log,stderr=subprocess.STDOUT)
            for _ in range(30):
                if proc.poll() is not None:break
                try:ready=local('eth_chainId',[])=='0x7a69'
                except Exception:pass
                if ready:break
                time.sleep(1)
            if ready:
                h=local('eth_getBlockByNumber',[hex(q['block_number']),False])
                if not h or any(h[k].lower()!=v for k,v in q['header'].items()):raise ValueError('FORK_HEADER_MISMATCH')
                report['provider']=label;break
            proc.terminate();proc.wait(timeout=10);proc=None
        if not ready or proc is None:raise ValueError('FORK_UNAVAILABLE')
        for i,r in enumerate(selected):
            if (root/'STOP').exists():raise ValueError('STOP_REQUESTED')
            env=dict(os.environ,FOUNDRY_PROFILE='fork',TRI_TOKEN1=r['tokens'][1],TRI_TOKEN2=r['tokens'][2],
                TRI_AMOUNT=r['amount_in'],TRI_RETURN=r['amount_out'],TRI_PREMIUM=r['premium_wei'])
            for j in range(3):env[f'TRI_FEE{j}']=str(r['fees'][j]);env[f'TRI_POOL{j}']=r['pools'][j]
            log_path=root/f'matched-triangle-{i+1}.log'
            with log_path.open('w') as log:
                result=subprocess.run(['forge','test','--fork-url','http://127.0.0.1:8547','--match-contract','MatchedTriangleForkTest','-vvvv'],
                    env=env,stdout=log,stderr=subprocess.STDOUT,timeout=420)
            log=log_path.read_text()
            if result.returncode or '[PASS] testMatchedTriangleZeroPrefund' not in log or '[PASS] testMatchedTriangleCannotSpendPrefund' not in log:
                raise ValueError('MATCHED_TRIANGLE_TEST_FAILED')
            report['tests'].append(dict(candidate=r,screen_sha256=sd,status='PASS',solidity_tests=2,
                expected_rejection=int(r['gross_before_gas_wei'])<2,log=log_path.name))
        report['status']='PASS'
    except Exception as exc:
        report.update(failure_type=type(exc).__name__,failure_code=str(exc) if isinstance(exc,ValueError) else 'FORK_FAILED')
    finally:
        if proc is not None:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    report['sha256']=digest(report);(root/'matched-triangle-gate.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:report[k] for k in ('status','selected_candidate_ids','failure_code') if k in report}))
    if report['status']!='PASS':raise SystemExit(1)
if __name__=='__main__':main()
