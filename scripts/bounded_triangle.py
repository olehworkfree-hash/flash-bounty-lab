#!/usr/bin/env python3
"""Three-token routes with isolated providers, deadlines and exact-candidate checks.

No account, signing, broadcast or gas spending. Unknown full fees remain unknown.
The worker reuses the existing hash-pinned Reader and sanitized batch journal.
"""
import argparse
import datetime as dt
import functools
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

import triangle_screen as t
from real_quorum import PROVIDERS
from bounded_screen import JournalReader, atomic_json, run_workers, safe_code, strict_agreement
from run_triangle_fork import validate_selection


def worker(label, quorum_path, output, token, scope):
    result=dict(status='FAILED',provider=label,token=token,execution_allowed=False,realized_pnl='0')
    try:
        q,qd=t.validate_quorum(json.loads(Path(quorum_path).read_text()),time.time())
        if label not in q['state_voters']:raise ValueError('PROVIDER_NOT_IN_QUORUM')
        t.Reader=functools.partial(JournalReader,directory=Path(output).parent/'batches')
        value=t.capture(label,q,t.STABLE_CONFIGS[scope],t.BOUNDED_FEES)
        t.validate_quorum(json.loads(Path(quorum_path).read_text()),time.time())
        result.update(status='PASS',observation=value,quorum_sha256=qd)
    except Exception as exc:
        result.update(failure_code=safe_code(exc),failure_type=type(exc).__name__)
    atomic_json(output,result)
    return 0 if result['status']=='PASS' else 1


def make_report(original, value, voters, scope, *, now):
    q,qd=t.validate_quorum(original,now)
    if value['stable_pair']!=list(t.STABLE_CONFIGS[scope]) or value['fee_tiers']!=list(t.BOUNDED_FEES):
        raise ValueError('WRONG_CAPTURE_SCOPE')
    rows=value['rows'];valid=[r for r in rows if 'gross_before_gas_wei' in r]
    chosen=t.select_candidates(rows);positive=sum(int(r['gross_before_gas_wei'])>0 for r in valid)
    report=dict(schema='flash.triangle_screen.v1',status='PASS',scope=scope,header=q['header'],
        block_number=q['block_number'],quorum_sha256=qd,voters=voters,observations=value,
        requested=len(rows),quoted=len(valid),positive_before_gas=positive,matched_fork_selection=chosen,
        source_commit=q.get('commit'),run_id=q.get('run_id'),execution_allowed=False,realized_pnl='0',
        exact_arbitrum_fee_known=False,runtime_hashes_preapproved=False,fee_tiers_omitted=[10000],
        decision='NEEDS_MATCHED_FORK_AND_FEES' if positive else 'NO_POSITIVE_TRIANGLE_IN_SUBSET')
    report['sha256']=t.digest(report)
    validate_selection(original,report,now)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--scope',choices=tuple(t.STABLE_CONFIGS),required=True)
    ap.add_argument('--worker',choices=tuple(PROVIDERS));ap.add_argument('--token',default='')
    args=ap.parse_args()
    if args.worker:return worker(args.worker,args.quorum,args.out,args.token,args.scope)
    report=dict(schema='flash.triangle_screen.v1',status='FAILED',scope=args.scope,
        source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
        execution_allowed=False,realized_pnl='0',exact_arbitrum_fee_known=False)
    atomic_json(args.out,report)
    try:
        original=json.loads(args.quorum.read_text());q,qd=t.validate_quorum(original,time.time())
        if os.getenv('GITHUB_SHA') and (q.get('commit')!=os.environ['GITHUB_SHA'] or q.get('run_id')!=os.getenv('GITHUB_RUN_ID')):
            raise ValueError('QUORUM_RUN_SOURCE_MISMATCH')
        root=Path(tempfile.mkdtemp(prefix='triangle-providers-',dir=args.out.parent)).resolve();token=root.name
        commands={label:[sys.executable,str(Path(__file__).resolve()),'--worker',label,'--quorum',str(args.quorum.resolve()),
            '--out',str(root/label/'result.json'),'--scope',args.scope,'--token',token] for label in q['state_voters']}
        supervision=run_workers(commands,root,token)
        complete={label:row['result']['observation'] for label,row in supervision['workers'].items()
            if row['status']=='PASS' and row['result'].get('quorum_sha256')==qd}
        diagnostics=dict(provider_status={label:{k:row[k] for k in ('status','failure_code') if k in row}
            for label,row in supervision['workers'].items()},elapsed_seconds=supervision['elapsed_seconds'],directory=root.name)
        report['provider_diagnostics']=diagnostics
        value,voters=strict_agreement(complete)
        report=make_report(original,value,voters,args.scope,now=time.time())
        report['provider_diagnostics']=diagnostics
    except Exception as exc:
        report.update(status='FAILED',failure_code=safe_code(exc),failure_type=type(exc).__name__)
    report.pop('sha256',None);report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();report['sha256']=t.digest(report)
    atomic_json(args.out,report)
    print(json.dumps({k:report[k] for k in ('status','scope','requested','quoted','positive_before_gas','failure_code') if k in report}),flush=True)
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    def interrupt(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt)
    raise SystemExit(main())
