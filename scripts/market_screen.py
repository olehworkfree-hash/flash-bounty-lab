#!/usr/bin/env python3
"""One bounded real-state V2 quote screen. No signing or transaction broadcast."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import time
from real_quorum import agreement, parallel, request, header, digest
WETH='0x82af49447d8a07e3bd95bd0d56f35241523fbab1'
USDC='0xaf88d065e77c8cc2239327c5edb3a432268e5831'
POOLS={'uniswap-v2':('0xf64dfe17c8b87f012fcf50fbda1d62bfa148366a','0xf1d7cc64fb4452f05c498126312ebe29f30fbcf9'),'sushiswap-v2':('0x57b85fef094e10b5eecdf350af688299e9553378','0xc35dadb65012ec5796536bd9864ed8773abc74c4')}
SIZES=[10**14,10**15,10**16,10**17,10**18,5*10**18]
def words(raw,count):
 if not isinstance(raw,str) or not raw.startswith('0x') or len(raw)!=2+64*count: raise ValueError('BAD_ABI')
 return [int(raw[2+64*i:66+64*i],16) for i in range(count)]
def address(raw):
 n=words(raw,1)[0]
 if n>=2**160: raise ValueError('BAD_ABI_ADDRESS')
 return '0x'+format(n,'040x')
def amount_out(amount,reserve_in,reserve_out):
 if any(type(n) is not int or n<=0 for n in (amount,reserve_in,reserve_out)): raise ValueError('INVALID_POOL_AMOUNTS')
 return amount*997*reserve_out//(reserve_in*1000+amount*997)
def premium(amount,bps):
 if type(amount) is not int or amount<=0 or type(bps) is not int or not 0<=bps<=10000: raise ValueError('INVALID_PREMIUM')
 return (amount*bps+5000)//10000
def evaluate(pools,bps,sizes=SIZES):
 rows=[]
 for buy,sell in [('uniswap-v2','sushiswap-v2'),('sushiswap-v2','uniswap-v2')]:
  for n in sizes:
   a=pools[buy]; b=pools[sell]; middle=amount_out(n,a['weth'],a['usdc']); returned=amount_out(middle,b['usdc'],b['weth']) if middle else 0; fee=premium(n,bps); gross=returned-n-fee
   rows.append(dict(buy=buy,sell=sell,borrow_weth_wei=str(n),intermediate_native_usdc_units=str(middle),returned_weth_wei=str(returned),premium_weth_wei=str(fee),gross_before_gas_weth_wei=str(gross),status='QUOTE_ONLY_NEEDS_FORK_AND_FEE' if gross>0 else 'NO_EDGE_BEFORE_GAS'))
 return rows
def capture(label,q):
 h=q['header']; ref=dict(blockHash=h['hash'],requireCanonical=True); calls=[]
 for pair,factory in POOLS.values():
  calls.append(('eth_getCode',[pair,ref]))
  for selector in ['0x0dfe1681','0xd21220a7','0xc45a0155','0x0902f1ac']: calls.append(('eth_call',[dict(to=pair,data=selector),ref]))
 raw=request(label,calls); pools={}
 for i,(name,(pair,factory)) in enumerate(POOLS.items()):
  code,t0,t1,f,res=raw[i*5:i*5+5]
  if not isinstance(code,str) or code=='0x': raise ValueError('EMPTY_PAIR_CODE')
  t0,t1=address(t0),address(t1)
  if {t0,t1}!={WETH,USDC} or address(f)!=factory: raise ValueError('PAIR_IDENTITY')
  r0,r1,stamp=words(res,3)
  if not (0<r0<2**112 and 0<r1<2**112 and stamp<2**32): raise ValueError('RESERVE_LIMIT')
  pools[name]=dict(weth=r0 if t0==WETH else r1,usdc=r1 if t0==WETH else r0,pair=pair,token0=t0,token1=t1)
 if header(label,q['block_number'])!=h: raise ValueError('BLOCK_CHANGED')
 return dict(raw=raw,pools=pools)
def main():
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--quorum',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
 result=dict(schema='flash.bounded_market_screen.v1',status='FAILED',actual_earnings='0',execution_allowed=False,native_usdc=True,exact_execution_fee_known=False,source_commit=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'),observed_at=dt.datetime.now(dt.timezone.utc).isoformat())
 try:
  q=json.loads(args.quorum.read_text()); expected=q.pop('evidence_sha256')
  if digest(q)!=expected or q.get('status')!='PASS' or q.get('historical') is not False: raise ValueError('QUORUM_REJECTED')
  if not -30<=time.time()-int(q['header']['timestamp'],16)<=600: raise ValueError('STALE_BLOCK')
  bps=words(q['state']['premium_raw'],1)[0]; seen,errors=parallel(lambda label:capture(label,q),q['state_voters']); agreed,voters=agreement(seen); rows=evaluate(agreed['pools'],bps)
  result.update(status='PASS',block_number=q['block_number'],block_hash=q['header']['hash'],quorum_evidence_sha256=expected,voters=voters,read_errors=errors,raw_state=agreed,quotes=rows,positive_before_gas=sum(int(x['gross_before_gas_weth_wei'])>0 for x in rows),quotes_evaluated=len(rows))
 except Exception as e: result['failure_type']=type(e).__name__
 result['sha256']=digest(result); args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps({k:result[k] for k in ('status','quotes_evaluated','positive_before_gas','failure_type') if k in result}))
 if result['status']!='PASS': raise SystemExit(1)
if __name__=='__main__': main()
