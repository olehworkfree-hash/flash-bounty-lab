#!/usr/bin/env python3
"""Bounded multi-provider triangle pruning; an exact subset is passed to a fork.
No wallet, broadcast, or positive-bound-as-income. Not a continuous scanner.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import triangle_screen as t
import v3_market_screen as v
from triangle_bounds import bound_routes, verify_exact
from bounded_screen import JournalReader, atomic_json, run_workers, strict_agreement, safe_code

MAX_EXACT = 64


def capture(label,q,checkpoint_dir,scope="native-bridged"):
    if scope not in t.STABLE_CONFIGS:raise ValueError("DISCOVERY_SCOPE")
    stable_pair=t.STABLE_CONFIGS[scope]
    reader=JournalReader(label,dict(blockHash=q['header']['hash'],requireCanonical=True),directory=checkpoint_dir)
    pools,excluded,hashes,bps=t.discover(reader,stable_pair)
    if bps!=t.words(q['state']['premium_raw'],1)[0]:raise ValueError('PREMIUM_DISAGREEMENT')
    bounds=bound_routes(pools,bps,stable_pair)
    survivors=[r for r in bounds if not r['bound_pruned']]
    ranked=sorted(survivors or bounds,key=lambda r:int(r['upper_gross_before_gas_wei']),reverse=True)
    chosen=ranked[:MAX_EXACT] if survivors else ranked[:1]
    values=reader.read([reader.call(t.QUOTER,t.encode_quote(r['tokens'],r['fees'],int(r['amount_in']))) for r in chosen])
    if len(values)!=len(chosen):raise ValueError('QUOTE_RESPONSE_COUNT')
    exact=[];unavailable=[]
    for r,item in zip(chosen,values):
        # Only an explicit RPC execution-revert result may be retained as unavailable.
        # State failures, transport failures, missing responses and malformed ABI still fail.
        # No unavailable row gets a price; all complete providers must agree on this set.
        if item.get('ok') is False and type(item.get('code')) is int and item['code']==3:
            missing={k:r[k] for k in ('tokens','fees','pools','amount_in')}
            missing.update(status='QUOTE_REVERTED_UNAVAILABLE',rpc_error_code=3)
            unavailable.append(missing)
            continue
        output=t.decode_quote(t.require_result(item));verify_exact(r,int(output['amount_out']))
        fee=t.premium(int(r['amount_in']),bps);gross=int(output['amount_out'])-int(r['amount_in'])-fee
        row={k:r[k] for k in ('tokens','fees','pools','amount_in')}
        row.update(**output,premium_wei=str(fee),gross_before_gas_wei=str(gross),
                   status='POSITIVE_UNVERIFIED' if gross>0 else 'NO_EDGE_BEFORE_GAS')
        row['candidate_id']=t.digest(dict(block_hash=q['header']['hash'],route=row));exact.append(row)
    if not exact:raise ValueError('NO_VALID_EXACT_QUOTES')
    if t.header(label,q['block_number'])!=q['header']:raise ValueError('BLOCK_CHANGED')
    return dict(scope=scope,stable_pair=list(stable_pair),fee_tiers=list(t.FEES),pools=pools,excluded=excluded,runtime_hashes=hashes,premium_bps=bps,
                bound_rows=bounds,exact_rows=exact,unavailable_quotes=unavailable,quote_attempt_count=len(chosen),route_count=len(bounds),
                bound_pruned=sum(r['bound_pruned'] for r in bounds),bound_survivors=len(survivors),
                unquoted_survivors=max(0,len(survivors)-len(chosen)),unavailable_quote_count=len(unavailable),exact_quote_count=len(exact),
                diagnostic_quote_without_candidate=not survivors,rpc_state_call_count=reader.count)


def worker(label,quorum_path,output,token,scope="native-bridged"):
    result=dict(status='FAILED',provider=label,token=token,execution_allowed=False,realized_pnl='0')
    try:
        original=json.loads(Path(quorum_path).read_text());q,qd=v.validate_quorum(original,time.time())
        if label not in q['state_voters']:raise ValueError('PROVIDER_NOT_IN_QUORUM')
        data=capture(label,q,Path(output).parent/'batches',scope)
        v.validate_quorum(original,time.time())
        result.update(status='PASS',observation=data,quorum_sha256=qd)
    except Exception as exc:
        result.update(failure_code=safe_code(exc),failure_type=type(exc).__name__)
    atomic_json(output,result)
    return 0 if result['status']=='PASS' else 1


def projection(report):
    """Explicitly project ONLY executed eth_call quotes, never synthetic bounds."""
    obs=report['observations'];rows=obs['exact_rows']
    p=dict(schema='flash.triangle_screen.v1',status='PASS',execution_allowed=False,realized_pnl='0',
           source_commit=report['source_commit'],run_id=report['run_id'],header=report['header'],
           block_number=report['block_number'],quorum_sha256=report['quorum_sha256'],voters=report['voters'],
           observations=dict(stable_pair=obs['stable_pair'],fee_tiers=obs['fee_tiers'],pools=obs['pools'],rows=rows,premium_bps=obs['premium_bps']),requested=len(rows),
           quoted=len(rows),positive_before_gas=sum(int(r['gross_before_gas_wei'])>0 for r in rows),
           matched_fork_selection=t.select_candidates(rows),projection_scope='EXACT_QUOTED_SUBSET_ONLY',
           bound_screen_sha256=report['sha256'],excluded_reverted_quotes=obs['unavailable_quote_count'],
           total_market_coverage=False,exact_arbitrum_fee_known=False)
    p['sha256']=t.digest(p)
    return p


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--worker',choices=tuple(v.PROVIDERS));ap.add_argument('--token',default='')
    ap.add_argument('--scope',choices=tuple(t.STABLE_CONFIGS),default='native-bridged')
    args=ap.parse_args()
    if args.worker:return worker(args.worker,args.quorum,args.out,args.token,args.scope)
    report=dict(schema='flash.triangle_bound_screen.v1',status='FAILED',execution_allowed=False,realized_pnl='0',
                source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
                exact_arbitrum_fee_known=False,total_market_coverage=False,runtime_hashes_preapproved=False,
                bounds_are_quotes=False,started_at=dt.datetime.now(dt.timezone.utc).isoformat())
    atomic_json(args.out,report)
    atomic_json(args.out.with_name('matched-selection.json'),dict(status='FAILED',execution_allowed=False,realized_pnl='0',reason='NEW_CAPTURE_NOT_COMPLETE'))
    try:
        original=json.loads(args.quorum.read_text());q,qd=v.validate_quorum(original,time.time())
        root=Path(tempfile.mkdtemp(prefix='triangle-providers-',dir=args.out.parent)).resolve();token=root.name
        commands={label:[sys.executable,str(Path(__file__).resolve()),'--quorum',str(args.quorum.resolve()),
                         '--out',str(root/label/'result.json'),'--worker',label,'--token',token,'--scope',args.scope] for label in q['state_voters']}
        supervisor=run_workers(commands,root,token)
        complete,errors={},{}
        for label,row in supervisor['workers'].items():
            if row['status']=='PASS' and row['result'].get('quorum_sha256')==qd:
                complete[label]=row['result']['observation']
            else:errors[label]=dict(status=row['status'],failure_code=row.get('failure_code','WORKER_SOURCE_MISMATCH'))
        report.update(complete_providers=sorted(complete),provider_failures=errors,
                      capture_elapsed_seconds=supervisor['elapsed_seconds'],provider_diagnostics_directory=root.name)
        obs,voters=strict_agreement(complete);v.validate_quorum(original,time.time())
        # Recompute every bound independently from the accepted pool-state records.
        if obs['scope']!=args.scope or tuple(obs['stable_pair'])!=t.STABLE_CONFIGS[args.scope]:raise ValueError('WORKER_SCOPE_MISMATCH')
        if bound_routes(obs['pools'],obs['premium_bps'],t.STABLE_CONFIGS[args.scope])!=obs['bound_rows']:raise ValueError('BOUND_RECALCULATION')
        positive=sum(int(r['gross_before_gas_wei'])>0 for r in obs['exact_rows'])
        report.update(status='PASS',header=q['header'],block_number=q['block_number'],quorum_sha256=qd,
                      voters=voters,observations=obs,positive_exact_quotes=positive,
                      decision='UNRESOLVED_BOUND_CANDIDATES_REMAIN' if obs['unquoted_survivors'] or obs['unavailable_quote_count'] else
                      'EXACT_CANDIDATES_REQUIRE_FORK_AND_FEES' if positive else 'NO_POSITIVE_ROUTE_IN_CAPTURED_SUBSET')
    except Exception as exc:report.update(failure_type=type(exc).__name__,failure_code=safe_code(exc))
    report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();report['sha256']=t.digest(report)
    atomic_json(args.out,report)
    if report['status']=='PASS':atomic_json(args.out.with_name('matched-selection.json'),projection(report))
    print(json.dumps({k:report[k] for k in ('status','block_number','capture_elapsed_seconds','positive_exact_quotes','decision','failure_code') if k in report}),flush=True)
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    def interrupt(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt)
    raise SystemExit(main())
