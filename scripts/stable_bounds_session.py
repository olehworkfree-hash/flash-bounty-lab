#!/usr/bin/env python3
"""Three bounded, independently pinned stable-pair scopes. Never signs or broadcasts."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from bounded_screen import atomic_json, safe_code
from triangle_bounds import bound_routes, verify_exact
import triangle_fast_screen as fast
import triangle_screen as tri
from run_triangle_fork import validate_selection
from screen_integrity import integer
from v3_market_screen import validate_quorum


def require(ok, code):
    if not ok:
        raise ValueError(code)


def route_key(row):
    return tri.digest({k:row[k] for k in ('tokens','fees','pools','amount_in')})


def audit_capture(quorum, report, scope, now):
    """Semantic checks supplement checksums. Neither authenticates provider ownership."""
    require(scope in tri.STABLE_CONFIGS, 'SCOPE_UNKNOWN')
    q, qd = validate_quorum(quorum, now)
    r = dict(report); sha = r.pop('sha256', None)
    require(tri.digest(r)==sha and r.get('status')=='PASS', 'CAPTURE_INTEGRITY')
    require(r.get('schema')=='flash.triangle_bound_screen.v1', 'CAPTURE_SCHEMA')
    require(r.get('execution_allowed') is False and r.get('realized_pnl')=='0', 'CAPTURE_POLICY')
    require(r.get('source_commit')==q.get('commit') and r.get('run_id')==q.get('run_id'), 'CAPTURE_RUN_LINK')
    require(r.get('header')==q['header'] and r.get('block_number')==q['block_number'] and r.get('quorum_sha256')==qd, 'CAPTURE_BLOCK_LINK')
    voters = r.get('voters', [])
    require(len(voters)>=2 and len(set(voters))==len(voters) and set(voters)<=set(q['state_voters']), 'CAPTURE_VOTERS')
    obs = r['observations']; pair = tri.STABLE_CONFIGS[scope]
    require(obs.get('scope')==scope and obs.get('stable_pair')==list(pair) and obs.get('fee_tiers')==list(tri.FEES), 'CAPTURE_SCOPE')
    bps=obs['premium_bps']
    require(type(bps) is int and bps==tri.words(q['state']['premium_raw'],1)[0], 'CAPTURE_PREMIUM')
    bounds=bound_routes(obs['pools'],bps,pair)
    require(obs['bound_rows']==bounds, 'CAPTURE_BOUND_GRID')
    survivors=[row for row in bounds if not row['bound_pruned']]
    ranked=sorted(survivors or bounds,key=lambda row:integer(row['upper_gross_before_gas_wei'],signed=True),reverse=True)
    chosen=ranked[:fast.MAX_EXACT] if survivors else ranked[:1]
    planned={route_key(row):row for row in chosen}; seen=set();positive=0
    for row in obs['exact_rows']:
        key=route_key(row)
        require(key in planned and key not in seen,'CAPTURE_EXACT_SET');seen.add(key)
        out=integer(row['amount_out']);verify_exact(planned[key],out)
        amount=integer(row['amount_in']);fee=tri.premium(amount,bps);gross=out-amount-fee
        require(integer(row['premium_wei'])==fee and integer(row['gross_before_gas_wei'],signed=True)==gross,'CAPTURE_ARITHMETIC')
        require(row['status']==('POSITIVE_UNVERIFIED' if gross>0 else 'NO_EDGE_BEFORE_GAS'),'CAPTURE_QUOTE_STATUS')
        unsigned=dict(row);ident=unsigned.pop('candidate_id',None)
        require(ident==tri.digest(dict(block_hash=q['header']['hash'],route=unsigned)),'CAPTURE_CANDIDATE_SEAL')
        positive+=gross>0
    for row in obs['unavailable_quotes']:
        key=route_key(row)
        require(key in planned and key not in seen,'CAPTURE_UNAVAILABLE_SET');seen.add(key)
        require(set(row)=={'tokens','fees','pools','amount_in','status','rpc_error_code'} and type(row['rpc_error_code']) is int and (row['status'],row['rpc_error_code']) in {('QUOTE_REVERTED_UNAVAILABLE',3),('QUOTE_GAS_LIMIT_UNAVAILABLE',-32000)},'CAPTURE_UNAVAILABLE_NOT_PRICE')
    require(seen==set(planned) and bool(obs['exact_rows']),'CAPTURE_MISSING_QUOTES')
    counts=dict(route_count=len(bounds),bound_pruned=len(bounds)-len(survivors),bound_survivors=len(survivors),
                quote_attempt_count=len(chosen),exact_quote_count=len(obs['exact_rows']),unavailable_quote_count=len(obs['unavailable_quotes']),
                unquoted_survivors=max(0,len(survivors)-len(chosen)))
    for name,n in counts.items():require(type(obs.get(name)) is int and obs[name]==n,'CAPTURE_COUNT')
    require(obs['diagnostic_quote_without_candidate'] is (not survivors),'CAPTURE_DIAGNOSTIC')
    require(type(r.get('positive_exact_quotes')) is int and r['positive_exact_quotes']==positive,'CAPTURE_POSITIVE_COUNT')
    return dict(**counts,positive_exact_quotes=positive)


def check_gate(quorum, report, selection, gate, scope, now):
    counts=audit_capture(quorum,report,scope,now)
    require(fast.projection(report)==selection,'PROJECTION_MISMATCH')
    q,s,sd,selected=validate_selection(quorum,selection,now)
    g=dict(gate);sha=g.pop('sha256',None)
    require(tri.digest(g)==sha and g.get('status')=='PASS' and g.get('schema')=='flash.matched_triangle_fork.v1','GATE_INTEGRITY')
    require(g.get('source_commit')==s.get('source_commit') and g.get('run_id')==s.get('run_id') and g.get('screen_sha256')==sd and g.get('block_hash')==q['header']['hash'],'GATE_SOURCE_LINK')
    require(g.get('execution_allowed') is False and g.get('mainnet_broadcast') is False and g.get('user_funds_used') is False and g.get('realized_pnl')=='0','GATE_POLICY')
    require(g.get('selected_candidate_ids')==[r['candidate_id'] for r in selected] and len(g.get('tests',[]))==len(selected),'GATE_SELECTION')
    economics=[]
    for tested,row in zip(g['tests'],selected):
        gross=integer(row['gross_before_gas_wei'],signed=True)
        require(tested.get('candidate')==row and tested.get('status')=='PASS' and tested.get('solidity_tests')==2 and tested.get('expected_rejection') is (gross<2),'GATE_TEST_LINK')
        economics.append(dict(candidate_id=row['candidate_id'],gross_before_gas_wei=str(gross),full_transaction_fee_wei=None,net_after_fee_wei=None,
            decision='REJECT_BEFORE_GAS' if gross<=0 else 'FULL_TRANSACTION_FEE_AND_LIVE_SURVIVAL_REQUIRED',execution_allowed=False,realized_pnl='0'))
    return dict(**counts,matched_candidates=len(selected),matched_tests=2*len(selected),economics=economics)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out-dir',type=Path,required=True)
    args=ap.parse_args();root=args.out_dir;root.mkdir(parents=True,exist_ok=False)
    result=dict(schema='flash.stable_bounds_session.v1',status='FAILED',scopes=[],source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),
                execution_allowed=False,realized_pnl='0',mainnet_broadcast=False,user_funds_used=False,exact_arbitrum_fee_known=False,next_block_survival_verified=False)
    def save():
        result.pop('sha256',None);result['sha256']=tri.digest(result);atomic_json(root/'summary.json',result)
    save()
    for scope in tri.STABLE_CONFIGS:
        d=root/scope;d.mkdir();q=d/'quorum.json';b=d/'bounds.json';sel=d/'matched-selection.json';g=d/'matched/matched-triangle-gate.json'
        entry=dict(scope=scope,status='FAILED');result['scopes'].append(entry);save()
        try:
            stages=[('real_quorum.py',['--out',str(q)],150),('triangle_fast_screen.py',['--quorum',str(q),'--out',str(b),'--scope',scope],150),
                    ('run_triangle_fork.py',['--quorum',str(q),'--screen',str(sel),'--out-dir',str(d/'matched')],900)]
            for script,argv,limit in stages:
                if (root/'STOP').exists():raise ValueError('STOP_REQUESTED')
                entry['stage']=script;save()
                if script=='run_triangle_fork.py':
                    audit_capture(json.loads(q.read_text()),json.loads(b.read_text()),scope,time.time())
                    require(fast.projection(json.loads(b.read_text()))==json.loads(sel.read_text()),'PROJECTION_MISMATCH')
                with (d/(script+'.log')).open('w') as log:
                    child=subprocess.run([sys.executable,str(Path(__file__).with_name(script)),*argv],stdout=log,stderr=subprocess.STDOUT,timeout=limit)
                if child.returncode:raise ValueError('CHILD_FAILED')
            qv,bv,sv,gv=(json.loads(p.read_text()) for p in (q,b,sel,g))
            counts=check_gate(qv,bv,sv,gv,scope,time.time())
            entry.update(status='PASS',block_number=qv['block_number'],block_hash=qv['header']['hash'],capture_seconds=bv['capture_elapsed_seconds'],voters=bv['voters'],**counts)
        except Exception as exc:entry.update(failure_type=type(exc).__name__,failure_code=safe_code(exc))
        save()
    result.update(status='PASS' if all(s['status']=='PASS' for s in result['scopes']) else 'FAILED',finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
    result['totals']={k:sum(s.get(k,0) for s in result['scopes'] if s['status']=='PASS') for k in ('route_count','bound_pruned','bound_survivors','quote_attempt_count','exact_quote_count','unavailable_quote_count','unquoted_survivors','positive_exact_quotes','matched_tests')}
    save();print(json.dumps(result),flush=True)
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
