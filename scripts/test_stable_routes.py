import copy
import unittest
from unittest.mock import patch
from bounded_triangle import make_report
from triangle_screen import *
from run_triangle_fork import validate_selection
from stable_route_session import economics,check_gate
from test_triangle import fixture,seal


def reseal_row(q,r):
    r.pop('candidate_id',None);r['candidate_id']=digest(dict(block_hash=q['header']['hash'],route=r))


class StableRouteTests(unittest.TestCase):
    def test_all_three_stable_pairs_and_both_directions(self):
        for pair in STABLE_CONFIGS.values():
            for a,b in (pair,pair[::-1]):self.assertEqual(len(packed_path([WETH,a,b,WETH],[100,500,3000])),89)
    def test_unknown_stable_rejected(self):
        with self.assertRaises(ValueError):packed_path([WETH,USDC,'0x'+'f'*40,WETH],[100,500,3000])
    def test_dai_decimals_are_not_usdc(self):self.assertEqual(STABLE_DECIMALS[DAI],18);self.assertEqual(STABLE_DECIMALS[USDC],6)
    def test_bounded_route_count_for_each_scope(self):
        for pair in STABLE_CONFIGS.values():
            pairs=((WETH,pair[0]),pair,(pair[1],WETH))
            pools=[dict(tokens=list(p),fee=f,pool='0x'+format(i*3+j+1,'040x')) for i,p in enumerate(pairs) for j,f in enumerate(BOUNDED_FEES)]
            self.assertEqual(len(build_routes(pools,pair)),216)
    def test_missing_grid_not_accepted_after_hash_recalculation(self):
        q,s=fixture();s['observations']['rows'].pop();s['requested']-=1;s['quoted']-=1;seal(s)
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_ROUTE_GRID'):validate_selection(q,s,1001)
    def test_false_positive_label_rejected(self):
        q,s=fixture();r=s['observations']['rows'][0];r['status']='POSITIVE_UNVERIFIED';reseal_row(q,r);seal(s)
        with self.assertRaisesRegex(ValueError,'QUOTE_STATUS'):validate_selection(q,s,1001)
    def test_run_mismatch_rejected(self):
        q,s=fixture();s['run_id']='other';seal(s)
        with self.assertRaisesRegex(ValueError,'RUN_SOURCE_MISMATCH'):validate_selection(q,s,1001)
    def test_missing_quote_cannot_have_output(self):
        q,s=fixture();r=s['observations']['rows'][0];r.pop('gross_before_gas_wei');r['status']='QUOTE_UNAVAILABLE';reseal_row(q,r);seal(s)
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE_QUOTE'):validate_selection(q,s,1001)
    def test_fee_tier_outside_declared_scope_rejected(self):
        q,s=fixture();s['observations']['fee_tiers']=list(BOUNDED_FEES);seal(s)
        with self.assertRaisesRegex(ValueError,'POOL_SCOPE'):validate_selection(q,s,1001)
    def test_boolean_counts_rejected(self):
        q,s=fixture();s['quoted']=True;seal(s)
        with self.assertRaisesRegex(ValueError,'SCREEN_COUNT_TYPE'):validate_selection(q,s,1001)
    def test_negative_does_not_require_fake_gas_cost(self):
        r=economics(dict(candidate_id='x',gross_before_gas_wei='-1'))
        self.assertEqual(r['decision'],'REJECT_BEFORE_GAS');self.assertIsNone(r['net_estimate_wei']);self.assertEqual(r['break_even_total_fee_wei'],'0')
    def test_positive_quote_without_fee_is_not_net_profit(self):
        r=economics(dict(candidate_id='x',gross_before_gas_wei='100'))
        self.assertEqual(r['decision'],'FULL_TRANSACTION_FEE_REQUIRED');self.assertFalse(r['execution_allowed']);self.assertEqual(r['realized_pnl'],'0')
    def test_estimated_fee_consumes_margin(self):
        self.assertEqual(economics(dict(candidate_id='x',gross_before_gas_wei='100'),101)['net_estimate_wei'],'-1')
    def test_even_synthetic_positive_net_is_not_authorization(self):
        r=economics(dict(candidate_id='x',gross_before_gas_wei='100'),50)
        self.assertFalse(r['execution_allowed']);self.assertEqual(r['decision'],'REQUIRES_REVIEW_NOT_EXECUTION')
    def test_invalid_fees(self):
        for x in [True,-1,0.1,'100']:
            with self.assertRaises(ValueError):economics(dict(candidate_id='x',gross_before_gas_wei='100'),x)
    def test_gate_must_be_sealed(self):
        q,s=fixture()
        with self.assertRaisesRegex(ValueError,'GATE_INTEGRITY'):check_gate(q,s,{},1001)
if __name__=='__main__':unittest.main()
