#!/usr/bin/env python3
"""Validate a selected screened triangle on a loopback-only Anvil fork. No broadcast."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from real_quorum import PROVIDERS, digest
from v3_market_screen import validate_quorum
from triangle_screen import audit
from bounded_screen import atomic_json, safe_code
from run_v3_fork import local, LOCAL


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum',type=Path,required=True);ap.add_argument('--screen',type=Path,required=True);ap.add_argument('--out-dir',type=Path,required=True)
    args=ap.parse_args();root=args.out_dir;root.mkdir(parents=True,exist_ok=True)
    report=dict(schema='flash.triangle_fork.v1',status='FAILED',realized_pnl='0',mainnet_broadcast=False,user_funds_used=False,
        exact_arbitrum_fee_known=False,local_native_eth_seeded_for_swap_test=True,flash_receiver_seeded=False,all_candidates_fork_verified=False,
        source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'));proc=None
    try:
        q,qd=validate_quorum(json.loads(args.quorum.read_text()),time.time())
        screen=json.loads(args.screen.read_text());sd=screen.pop('sha256',None)
        if sd!=digest(screen) or screen.get('status')!='PASS':raise ValueError('SCREEN_INTEGRITY')
        audit(q,screen)
        rows=[r for r in screen['observations']['quote_rows'] if 'gross_before_gas_wei' in r]
        if not rows:raise ValueError('NO_SUCCESSFUL_QUOTES')
        row=max(rows,key=lambda r:int(r['gross_before_gas_wei']))
        route=next(x for x in screen['observations']['routes'] if x['id']==row['route_id'])
        report.update(block_number=q['block_number'],block_hash=q['header']['hash'],quorum_sha256=qd,screen_sha256=sd,selected_route=route,selected_quote=row)
        alive=False
        try:local('eth_chainId',[]);alive=True
        except Exception:pass
        if alive:raise ValueError('LOCAL_RPC_PORT_BUSY')
        for label in ('alchemy-public','publicnode','arbitrum-official'):
            if label not in screen['voters']:continue
            with (root/f'anvil-triangle-{label}.log').open('w') as log:
                proc=subprocess.Popen(['anvil','--fork-url',PROVIDERS[label],'--fork-block-number',str(q['block_number']),
                    '--hardfork','shanghai','--chain-id','31337','--host','127.0.0.1','--port','8547','--silent'],stdout=log,stderr=subprocess.STDOUT)
            ready=False
            for _ in range(30):
                if proc.poll() is not None:break
                try:ready=local('eth_chainId',[])=='0x7a69'
                except Exception:pass
                if ready:break
                time.sleep(1)
            if ready:
                h=local('eth_getBlockByNumber',[hex(q['block_number']),False])
                if not h or any(h[k].lower()!=value for k,value in q['header'].items()):raise ValueError('FORK_HEADER_MISMATCH')
                report['provider']=label;break
            proc.terminate();proc.wait(timeout=10);proc=None
        if proc is None or not ready:raise ValueError('LOCAL_FORK_UNAVAILABLE')
        env=dict(os.environ,FOUNDRY_PROFILE='fork',TRI_PATH=route['path'],TRI_AMOUNT=row['amount_in'],TRI_EXPECTED=row['quote']['amount_out'])
        logpath=root/'triangle-fork-tests.log'
        with logpath.open('w') as log:
            run=subprocess.run(['forge','test','--fork-url',LOCAL,'--match-contract','^TriangularV3ForkTest$','-vvvv'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=420)
        if run.returncode or '3 passed; 0 failed' not in logpath.read_text():raise ValueError('TRIANGLE_FORGE_TEST_FAILED')
        report.update(status='PASS',tests_passed=3,anvil_header_matched=True,local_chain_id=31337,
            selected_flash_result='POSITIVE_DELTA_BEFORE_GAS_ON_FORK_ONLY' if int(row['gross_before_gas_wei'])>0 else 'UNPROFITABLE_TRIANGLE_REVERTED',
            exact_selected_quote_matched_actual_swaps=True)
    except Exception as exc:report.update(failure_type=type(exc).__name__,failure_code=safe_code(exc))
    finally:
        if proc is not None:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    report['sha256']=digest(report);atomic_json(root/'triangle-fork-gate.json',report)
    print(json.dumps({k:report[k] for k in ('status','tests_passed','selected_flash_result','failure_code') if k in report}))
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
