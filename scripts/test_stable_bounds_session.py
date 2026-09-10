import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import triangle_fast_screen as f
import triangle_screen as t
from triangle_bounds import bound_routes
from stable_bounds_session import audit_capture, check_gate


def fixture(scope='native-bridged'):
    pair=t.STABLE_CONFIGS[scope];ps=[]
    for i,leg in enumerate(((t.WETH,pair[0]),pair,(pair[1],t.WETH))):
        a,b=sorted(leg,key=lambda x:int(x,16))
        ps.append(dict(pool='0x'+format(i+1,'040x'),tokens=list(leg),token0=a,token1=b,fee=500,
                       slot0_raw='0x'+''.join(t.uint(x) for x in (2**96,0,0,1,1,0,1))))
    class Reader:
        def __init__(self,*args,**kw):self.count=0
        def call(self,target,data):return target,data
        def read(self,calls):
            self.count+=len(calls)
            lut={t.encode_quote(r['tokens'],r['fees'],int(r['amount_in'])):int(r['upper_bound_out'])-1 for r in bound_routes(ps,5,pair)}
            return [dict(ok=True,result='0x'+''.join(t.uint(x) for x in (lut[data],128,256,10000,3,2**96,2**96,2**96,3,0,0,0))) for _,data in calls]
    q=dict(status='PASS',historical=False,header=dict(hash='0x'+'a'*64,number=hex(100),timestamp=hex(1000)),block_number=100,
           state_voters=['arbitrum-official','publicnode'],state=dict(premium_raw='0x'+t.uint(5)),commit='a'*40,run_id='1')
    q['evidence_sha256']=t.digest(q)
    with patch.object(f,'JournalReader',Reader),patch.object(f.t,'discover',return_value=(ps,[],{},5)),patch.object(f.t,'header',return_value=q['header']):
        obs=f.capture('publicnode',q,Path('/unused-unit'),scope)
    r=dict(schema='flash.triangle_bound_screen.v1',status='PASS',execution_allowed=False,realized_pnl='0',source_commit=q['commit'],run_id='1',
           header=q['header'],block_number=100,quorum_sha256=q['evidence_sha256'],voters=q['state_voters'],observations=obs,positive_exact_quotes=0)
    r['sha256']=t.digest(r);s=f.projection(r)
    selected=s['matched_fork_selection']
    g=dict(schema='flash.matched_triangle_fork.v1',status='PASS',source_commit=q['commit'],run_id='1',screen_sha256=s['sha256'],block_hash=q['header']['hash'],
           execution_allowed=False,realized_pnl='0',mainnet_broadcast=False,user_funds_used=False,selected_candidate_ids=[x['candidate_id'] for x in selected],
           tests=[dict(status='PASS',candidate=x,solidity_tests=2,expected_rejection=True) for x in selected])
    g['sha256']=t.digest(g)
    return q,r,s,g


def seal(d):
    d.pop('sha256',None);d['sha256']=t.digest(d)


class StableBoundsTest(unittest.TestCase):
    def test_all_three_scopes(self):
        for scope in t.STABLE_CONFIGS:
            with self.subTest(scope=scope):
                q,r,s,g=fixture(scope);result=check_gate(q,r,s,g,scope,1001)
                self.assertEqual(result['route_count'],8)
                self.assertEqual(result['bound_pruned'],8)
                self.assertEqual(result['exact_quote_count'],1)
                self.assertEqual(result['matched_tests'],2)
                self.assertIsNone(result['economics'][0]['net_after_fee_wei'])
    def test_dai_is_18_decimals_not_usdc(self):self.assertEqual(t.STABLE_DECIMALS[t.DAI],18)
    def test_dai_packed_routes_allowed(self):
        self.assertEqual(len(t.packed_path([t.WETH,t.USDC,t.DAI,t.WETH],[100,500,3000])),89)
    def test_unlisted_stable_not_allowed(self):
        with self.assertRaises(ValueError):t.packed_path([t.WETH,t.USDC,'0x'+'f'*40,t.WETH],[100,500,3000])
    def mutate(self,func):
        q,r,s,g=fixture();func(q,r);seal(r)
        with self.assertRaises(ValueError):audit_capture(q,r,'native-bridged',1001)
    def test_scope_substitution(self):self.mutate(lambda q,r:r['observations'].update(scope='native-dai'))
    def test_pair_substitution(self):self.mutate(lambda q,r:r['observations'].update(stable_pair=list(t.STABLE_CONFIGS['native-dai'])))
    def test_bound_omission_with_resealed_checksum(self):self.mutate(lambda q,r:r['observations']['bound_rows'].pop())
    def test_false_quote_count(self):self.mutate(lambda q,r:r['observations'].update(exact_quote_count=True))
    def test_unavailable_cannot_contain_price(self):
        def change(q,r):
            row=copy.deepcopy(r['observations']['exact_rows'][0]);row.update(status='QUOTE_REVERTED_UNAVAILABLE',rpc_error_code=3)
            r['observations']['exact_rows']=[];r['observations']['unavailable_quotes']=[row]
        self.mutate(change)
    def test_fake_positive_arithmetic(self):self.mutate(lambda q,r:r['observations']['exact_rows'][0].update(gross_before_gas_wei='100'))
    def test_duplicate_exact_quote(self):self.mutate(lambda q,r:r['observations']['exact_rows'].append(copy.deepcopy(r['observations']['exact_rows'][0])))
    def test_missing_exact(self):self.mutate(lambda q,r:r['observations'].update(exact_rows=[]))
    def test_source_commit_mismatch(self):self.mutate(lambda q,r:r.update(source_commit='b'*40))
    def test_run_mismatch(self):self.mutate(lambda q,r:r.update(run_id='2'))
    def test_single_voter(self):self.mutate(lambda q,r:r.update(voters=['publicnode']))
    def test_fake_bound_bigger(self):self.mutate(lambda q,r:r['observations']['bound_rows'][0].update(upper_bound_out='99999999999999999999'))
    def test_stale_quorum(self):
        q,r,_,_=fixture()
        with self.assertRaisesRegex(ValueError,'STALE_BLOCK'):audit_capture(q,r,'native-bridged',10000)
    def test_gate_different_screen(self):
        q,r,s,g=fixture();g['screen_sha256']='0'*64;seal(g)
        with self.assertRaisesRegex(ValueError,'GATE_SOURCE_LINK'):check_gate(q,r,s,g,'native-bridged',1001)
    def test_gate_real_funds_forbidden(self):
        q,r,s,g=fixture();g['user_funds_used']=True;seal(g)
        with self.assertRaisesRegex(ValueError,'GATE_POLICY'):check_gate(q,r,s,g,'native-bridged',1001)
    def test_gate_wrong_expected_rejection(self):
        q,r,s,g=fixture();g['tests'][0]['expected_rejection']=False;seal(g)
        with self.assertRaisesRegex(ValueError,'GATE_TEST_LINK'):check_gate(q,r,s,g,'native-bridged',1001)
    def test_projected_bounds_not_quotes(self):
        q,r,s,g=fixture();s['observations']['rows']=r['observations']['bound_rows'];seal(s)
        with self.assertRaisesRegex(ValueError,'PROJECTION_MISMATCH'):check_gate(q,r,s,g,'native-bridged',1001)
    def test_wrong_unknown_scope(self):
        q,r,_,_=fixture()
        with self.assertRaisesRegex(ValueError,'SCOPE_UNKNOWN'):audit_capture(q,r,'all-tokens',1001)

if __name__=='__main__':unittest.main()
