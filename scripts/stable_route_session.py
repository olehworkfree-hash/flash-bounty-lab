#!/usr/bin/env python3
"""At most three stable-pair experiments. No continuous monitoring or public trades."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from bounded_screen import atomic_json
from real_quorum import digest
from triangle_screen import STABLE_CONFIGS
from run_triangle_fork import validate_selection


def economics(row, transaction_fee_wei=None):
    """A positive pre-gas quote is not permission to trade or confirmed income."""
    gross=int(row['gross_before_gas_wei'])
    if transaction_fee_wei is not None and (type(transaction_fee_wei) is not int or transaction_fee_wei<0):
        raise ValueError('INVALID_FEE_ESTIMATE')
    return dict(candidate_id=row['candidate_id'],gross_before_gas_wei=str(gross),
        break_even_total_fee_wei=str(max(0,gross)),
        transaction_fee_wei=None if transaction_fee_wei is None else str(transaction_fee_wei),
        net_estimate_wei=None if transaction_fee_wei is None else str(gross-transaction_fee_wei),
        decision='REJECT_BEFORE_GAS' if gross<=0 else ('FULL_TRANSACTION_FEE_REQUIRED' if transaction_fee_wei is None else
            'REJECT_AFTER_ESTIMATED_FEE' if gross<=transaction_fee_wei else 'REQUIRES_REVIEW_NOT_EXECUTION'),
        execution_allowed=False,realized_pnl='0')


def check_gate(q,s,g,now):
    _,_,sd,selected=validate_selection(q,s,now)
    body=dict(g);dg=body.pop('sha256',None)
    if digest(body)!=dg or g.get('status')!='PASS' or g.get('schema')!='flash.matched_triangle_fork.v1':raise ValueError('GATE_INTEGRITY')
    if g.get('source_commit')!=s.get('source_commit') or g.get('run_id')!=s.get('run_id') or g.get('screen_sha256')!=sd or g.get('block_hash')!=q['header']['hash']:raise ValueError('GATE_SOURCE_LINK')
    if g.get('execution_allowed') is not False or g.get('mainnet_broadcast') is not False or g.get('user_funds_used') is not False or g.get('realized_pnl')!='0':raise ValueError('GATE_RESEARCH_POLICY')
    if len(g.get('tests',[]))!=len(selected) or g.get('selected_candidate_ids')!=[r['candidate_id'] for r in selected]:raise ValueError('GATE_SELECTION')
    for tested,r in zip(g['tests'],selected):
        if tested.get('candidate')!=r or tested.get('status')!='PASS' or tested.get('solidity_tests')!=2:raise ValueError('GATE_CANDIDATE')
    return [economics(r) for r in selected]


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out-dir',type=Path,required=True)
    args=ap.parse_args();root=args.out_dir
    # Each run is separate; no preexisting PASS can be accepted after a child fails.
    root.mkdir(parents=True,exist_ok=False)
    result=dict(schema='flash.stable_route_session.v1',status='FAILED',scopes=[],source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
        execution_allowed=False,realized_pnl='0',mainnet_broadcast=False,user_funds_used=False,exact_arbitrum_fee_known=False,
        next_block_survival_verified=False,unique_opportunities_not_counted=True)
    def save():
        result.pop('sha256',None);result['sha256']=digest(result);atomic_json(root/'summary.json',result)
    save()
    for scope in STABLE_CONFIGS:
        entry=dict(scope=scope,status='FAILED');result['scopes'].append(entry)
        d=root/scope;d.mkdir();q=d/'quorum.json';s=d/'screen.json'
        stages=[('real_quorum.py',['--out',str(q)],120),('bounded_triangle.py',['--quorum',str(q),'--out',str(s),'--scope',scope],135),
            ('run_triangle_fork.py',['--quorum',str(q),'--screen',str(s),'--out-dir',str(d/'matched')],900)]
        try:
            for script,argv,limit in stages:
                if (root/'STOP').exists():raise ValueError('STOP_REQUESTED')
                entry['stage']=script;save()
                with (d/(script+'.log')).open('w') as log:
                    child=subprocess.run([sys.executable,str(Path(__file__).with_name(script)),*argv],stdout=log,stderr=subprocess.STDOUT,timeout=limit)
                if child.returncode:raise ValueError('CHILD_FAILED')
            qv,sv,gv=(json.loads(x.read_text()) for x in (q,s,d/'matched/matched-triangle-gate.json'))
            econ=check_gate(qv,sv,gv,time.time())
            entry.update(status='PASS',block_number=qv['block_number'],block_hash=qv['header']['hash'],quoted=sv['quoted'],requested=sv['requested'],
                positive_before_gas=sv['positive_before_gas'],selected_candidates=len(econ),matched_tests=len(econ)*2,economics=econ)
        except Exception as exc:
            entry.update(failure_type=type(exc).__name__,failure_code=str(exc) if isinstance(exc,ValueError) else 'STAGE_FAILED')
        save()
    result.update(status='PASS' if all(s['status']=='PASS' for s in result['scopes']) else 'FAILED',finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
    save();print(json.dumps(result),flush=True)
    return 0 if result['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
