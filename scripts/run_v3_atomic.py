#!/usr/bin/env python3
"""Run real-code V3 swaps ONLY in loopback Anvil after verifying pinned header."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from real_quorum import PROVIDERS, digest
from v3_market_screen import validate_quorum

LOCAL='http://127.0.0.1:8547'


def local(method,params):
    if method not in {'eth_chainId','eth_getBlockByNumber'}:
        raise ValueError('LOCAL_READ_POLICY')
    req=urllib.request.Request(LOCAL,data=json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=2) as reply:
        data=json.load(reply)
    if data.get('id')!=1 or 'error' in data:
        raise ValueError('LOCAL_RPC_FAILED')
    return data['result']


def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--quorum',type=Path,required=True); ap.add_argument('--out-dir',type=Path,required=True); args=ap.parse_args()
    root=args.out_dir; root.mkdir(parents=True,exist_ok=True)
    report=dict(schema='flash.v3_atomic_fork.v1',status='FAILED',realized_pnl='0',mainnet_broadcast=False,user_funds_used=False,exact_arbitrum_fee_known=False,local_native_eth_seeded=True,flash_loan_attempted_in_local_test=True,profitable_trade_not_claimed=True,source_commit=os.getenv('GITHUB_SHA'))
    proc=None
    try:
        q,qd=validate_quorum(json.loads(args.quorum.read_text()),time.time())
        report.update(block_number=q['block_number'],block_hash=q['header']['hash'],quorum_sha256=qd)
        for label in ['alchemy-public','publicnode','arbitrum-official']:
            if label not in q['state_voters']: continue
            with (root/f'anvil-atomic-{label}.log').open('w') as log:
                proc=subprocess.Popen(['anvil','--fork-url',PROVIDERS[label],'--fork-block-number',str(q['block_number']),'--hardfork','shanghai','--chain-id','31337','--host','127.0.0.1','--port','8547','--silent'],stdout=log,stderr=subprocess.STDOUT)
            ready=False
            for _ in range(30):
                if proc.poll() is not None: break
                try:
                    ready=local('eth_chainId',[])=='0x7a69'
                except Exception:
                    pass
                if ready: break
                time.sleep(1)
            if ready:
                h=local('eth_getBlockByNumber',[hex(q['block_number']),False])
                if not h or any(h[k].lower()!=v for k,v in q['header'].items()):
                    raise ValueError('LOCAL_FORK_HEADER_MISMATCH')
                report['provider']=label
                break
            proc.terminate();proc.wait(timeout=10);proc=None
        if proc is None or not ready: raise ValueError('LOCAL_FORK_UNAVAILABLE')
        env=dict(os.environ,FOUNDRY_PROFILE='fork')
        with (root/'v3-atomic-tests.log').open('w') as log:
            run=subprocess.run(['forge','test','--fork-url',LOCAL,'--match-contract','V3AtomicForkTest','-vvvv'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=420)
        if run.returncode: raise ValueError('V3_ATOMIC_TEST_FAILED')
        report.update(status='PASS',local_chain_id=31337,anvil_header_matched=True)
    except Exception as exc:
        report.update(failure_type=type(exc).__name__,failure_code=str(exc) if isinstance(exc,ValueError) else 'FORK_FAILED')
    finally:
        if proc is not None:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    report['sha256']=digest(report); (root/'v3-atomic-gate.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    if report['status']!='PASS':raise SystemExit(1)
if __name__=='__main__': main()
