#!/usr/bin/env python3
"""Bounded three-block observation session, not an autonomous trader or PnL ledger."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from real_quorum import digest

MAX_ROUNDS = 3


def checked(document, field='sha256'):
    if not isinstance(document, dict):
        raise ValueError('DOCUMENT_SHAPE')
    body = dict(document)
    sha = body.pop(field, None)
    if not isinstance(sha, str) or digest(body) != sha or body.get('status') != 'PASS':
        raise ValueError('DOCUMENT_INTEGRITY_OR_STATUS')
    return body


def summarize(samples):
    if not 1 <= len(samples) <= MAX_ROUNDS:
        raise ValueError('ROUND_COUNT')
    blocks, details, row_counts, positives = set(), [], 0, 0
    last_number = -1
    for quorum, screen in samples:
        q = checked(quorum, 'evidence_sha256')
        s = checked(screen)
        if q.get('historical') is not False or s.get('execution_allowed') is not False:
            raise ValueError('RESEARCH_POLICY')
        if s.get('realized_pnl') != '0':
            raise ValueError('NO_PAPER_EARNINGS')
        voters = s.get('voters', [])
        if len(set(voters)) < 2 or not set(voters) <= set(q['state_voters']):
            raise ValueError('SCREEN_QUORUM')
        if s.get('quorum_sha256') != quorum['evidence_sha256'] or s.get('header') != q['header']:
            raise ValueError('SOURCE_LINK')
        number = s['block_number']
        if type(number) is not int or number != q['block_number'] or number != int(q['header']['number'], 16):
            raise ValueError('BLOCK_NUMBER')
        if number <= last_number or q['header']['hash'] in blocks:
            raise ValueError('DUPLICATE_OR_REVERSED_BLOCK')
        last_number = number; blocks.add(q['header']['hash'])
        rows = s['observations']['quote_rows']
        valid = [r for r in rows if 'gross_before_gas_wei' in r]
        wins = [r for r in valid if int(r['gross_before_gas_wei']) > 0]
        if len(rows) != s['rows_requested'] or len(valid) != s['successful_quotes'] or len(wins) != s['positive_before_gas']:
            raise ValueError('COUNT_MISMATCH')
        best = max(valid, key=lambda r: int(r['gross_before_gas_wei'])) if valid else None
        details.append(dict(block_number=number,block_hash=q['header']['hash'],
            block_timestamp=int(q['header']['timestamp'],16),rows=len(rows),quoted=len(valid),
            positive_before_gas=len(wins),best_quote=best,screen_sha256=screen['sha256']))
        row_counts += len(valid); positives += len(wins)
    return dict(schema='flash.bounded_session.v1',status='PASS',rounds=len(samples),
        observations=details,successful_quote_evaluations=row_counts,positive_quote_evaluations=positives,
        unique_opportunities_not_counted=True,execution_allowed=False,realized_pnl='0',
        consecutive_blocks_required=False,latency_survival_verified=False,
        all_candidates_fork_verified=False,exact_arbitrum_fee_known=False,
        decision='CANDIDATES_REQUIRE_MATCHED_ATOMIC_FORK_AND_FEES' if positives else 'NO_POSITIVE_QUOTE_IN_OBSERVED_SUBSET')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out-dir',type=Path,required=True)
    ap.add_argument('--rounds',type=int,default=3,choices=range(1,MAX_ROUNDS+1))
    args=ap.parse_args(); args.out_dir.mkdir(parents=True,exist_ok=True)
    report=dict(schema='flash.bounded_session.v1',status='FAILED',realized_pnl='0',execution_allowed=False)
    samples=[]
    try:
        for i in range(args.rounds):
            if (args.out_dir/'STOP').exists():
                raise ValueError('STOP_REQUESTED')
            root=args.out_dir/f'round-{i+1}'; root.mkdir(exist_ok=True)
            qpath,spath=root/'quorum.json',root/'screen.json'
            for script,extra in [('real_quorum.py',['--out',str(qpath)]),
                                 ('v3_market_screen.py',['--quorum',str(qpath),'--out',str(spath)])]:
                with (root/(script+'.log')).open('w') as log:
                    result=subprocess.run([sys.executable,str(Path(__file__).with_name(script)),*extra],
                        stdout=log,stderr=subprocess.STDOUT,timeout=240)
                if result.returncode:
                    raise ValueError('CHILD_CHECK_FAILED')
            samples.append((json.loads(qpath.read_text()),json.loads(spath.read_text())))
            summarize(samples)  # Stop on conflicting metadata immediately.
            if i+1<args.rounds:
                time.sleep(4)
        report=summarize(samples)
    except Exception as exc:
        report.update(failure_type=type(exc).__name__,failure_code=str(exc) if isinstance(exc,ValueError) else 'SESSION_FAILED')
    report.update(completed_rounds=len(samples),source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
        finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
    report['sha256']=digest(report)
    (args.out_dir/'session.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:report[k] for k in ('status','rounds','successful_quote_evaluations','positive_quote_evaluations','decision','failure_code') if k in report}))
    if report['status']!='PASS':
        raise SystemExit(1)
if __name__=='__main__':
    main()
