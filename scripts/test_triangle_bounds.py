import copy
from fractions import Fraction
import random
import unittest
from triangle_screen import WETH,USDC,USDCE,PAIRS,uint,build_routes
from triangle_bounds import pool_index,route_bound,bound_routes,verify_exact

Q=2**96

def pools():
    result=[]
    for i,pair in enumerate(PAIRS):
        a,b=sorted(pair,key=lambda x:int(x,16))
        result.append(dict(pool='0x'+format(i+1,'040x'),tokens=list(pair),token0=a,token1=b,
                           fee=500,slot0_raw='0x'+''.join(uint(x) for x in (Q,0,0,1,1,0,1))))
    return result


def single_range_reference(amount,s,L,zero,fee):
    # Fraction-based constant-liquidity reference, no floating-point pricing.
    net=amount*(1_000_000-fee)//1_000_000
    after=Fraction(L*Q*s,L*Q+net*s) if zero else Fraction(s)+Fraction(net*Q,L)
    out=Fraction(L,Q)*(s-after) if zero else L*Q*(Fraction(1,s)-1/after)
    return int(out)


class TriangleBoundTest(unittest.TestCase):
    def test_equal_prices_always_lose_fees(self):
        rows=bound_routes(pools(),5)
        self.assertEqual(len(rows),8)
        self.assertTrue(all(r['bound_pruned'] for r in rows))
    def test_positive_upper_is_not_pruned(self):
        ps=pools();ps[1]['slot0_raw']='0x'+''.join(uint(x) for x in (Q*2,0,0,1,1,0,1))
        self.assertTrue(any(not r['bound_pruned'] for r in bound_routes(ps,5)))
    def test_integer_bound_matches_fraction(self):
        ps=pools();idx=pool_index(ps)
        for r in build_routes(ps):
            expected=Fraction(int(r['amount_in']))*Fraction(999500,1000000)**3
            self.assertEqual(route_bound(r,idx),int(expected))
    def test_bound_direction_is_not_decimal_converted(self):
        ps=pools();ps[0]['slot0_raw']='0x'+''.join(uint(x) for x in (Q*3,0,0,1,1,0,1))
        rs=bound_routes(ps,5)
        self.assertTrue(any(int(r['upper_bound_out'])>int(r['amount_in']) for r in rs))
        self.assertTrue(any(int(r['upper_bound_out'])<int(r['amount_in']) for r in rs))
    def test_duplicate_pool_rejected(self):
        ps=pools();ps[1]['pool']=ps[0]['pool']
        with self.assertRaisesRegex(ValueError,'DUPLICATE_POOL'):pool_index(ps)
    def test_unsorted_tokens_rejected(self):
        ps=pools();ps[0]['token0'],ps[0]['token1']=ps[0]['token1'],ps[0]['token0']
        with self.assertRaisesRegex(ValueError,'TOKEN_ORDER'):pool_index(ps)
    def test_unlocked_pool_required(self):
        ps=pools();ps[0]['slot0_raw']='0x'+''.join(uint(x) for x in (Q,0,0,1,1,0,0))
        with self.assertRaisesRegex(ValueError,'POOL_PRICE_OR_LOCK'):pool_index(ps)
    def test_zero_price_rejected(self):
        ps=pools();ps[0]['slot0_raw']='0x'+''.join(uint(x) for x in (0,0,0,1,1,0,1))
        with self.assertRaises(ValueError):pool_index(ps)
    def test_out_of_range_price_rejected(self):
        ps=pools();ps[0]['slot0_raw']='0x'+''.join(uint(x) for x in (2**160,0,0,1,1,0,1))
        with self.assertRaises(ValueError):pool_index(ps)
    def test_fee_allowlist(self):
        for f in (0,-1,1000000,True):
            ps=pools();ps[0]['fee']=f
            with self.assertRaises(ValueError):pool_index(ps)
    def test_flash_premium_type(self):
        for f in (True,-1,10001,'5'):
            with self.assertRaises(ValueError):bound_routes(pools(),f)
    def test_distinct_pool_guard(self):
        ps=pools();r=build_routes(ps)[0];r['pools'][1]=r['pools'][0]
        with self.assertRaises(ValueError):route_bound(r,pool_index(ps))
    def test_route_fee_must_match(self):
        ps=pools();r=build_routes(ps)[0];r['fees'][0]=100
        with self.assertRaisesRegex(ValueError,'ROUTE_POOL_MISMATCH'):route_bound(r,pool_index(ps))
    def test_noncanonical_amount(self):
        ps=pools();r=build_routes(ps)[0];r['amount_in']='0'+r['amount_in']
        with self.assertRaises(ValueError):route_bound(r,pool_index(ps))
    def test_exact_output_above_bound_stops(self):
        r=bound_routes(pools(),5)[0]
        with self.assertRaisesRegex(ValueError,'EXACT_EXCEEDS_UPPER_BOUND'):verify_exact(r,int(r['upper_bound_out'])+1)
    def test_equal_bound_accepted(self):
        r=bound_routes(pools(),5)[0];verify_exact(r,int(r['upper_bound_out']))
    def test_zero_quote_not_silently_profit(self):
        with self.assertRaises(ValueError):verify_exact({'upper_bound_out':'100'},0)
    def test_400_randomized_three_pool_swaps_below_bound(self):
        rng=random.Random(20260910)
        for i in range(400):
            ps=pools()
            for p in ps:
                s=rng.randint(2**70,2**110);p['fee']=rng.choice([100,500,3000,10000])
                p['slot0_raw']='0x'+''.join(uint(x) for x in (s,0,0,1,1,0,1))
            idx=pool_index(ps);r=rng.choice(build_routes(ps));out=int(r['amount_in'])
            for a,b,f,pa in zip(r['tokens'],r['tokens'][1:],r['fees'],r['pools']):
                t0,t1,fee,s=idx[pa]
                out=single_range_reference(out,s,rng.randint(10**20,10**28),a==t0,fee)
            self.assertLessEqual(out,route_bound(r,idx),msg=str(i))
    def test_empty_pool_set_rejected(self):
        with self.assertRaises(ValueError):bound_routes([],5)
    def test_bounds_have_no_claimed_quote(self):
        for r in bound_routes(pools(),5):
            self.assertNotIn('amount_out',r);self.assertNotIn('gross_before_gas_wei',r)

if __name__=='__main__':unittest.main()
