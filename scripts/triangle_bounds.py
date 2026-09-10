"""Exact rational, optimistic return bounds for fixed, distinct Uniswap V3 pools.

This is a pruning bound, NOT a quote. Only standard exact-input swaps in the
WETH/USDC/USDC.e allowlist are covered. See docs/TRIANGLE_BOUNDS.md for proof.
"""
import re
from triangle_screen import packed_path, build_routes, SIZES, FEES, words, premium

Q192 = 2**192
D = 1_000_000
ADDRESS = re.compile(r'0x[0-9a-f]{40}\Z')


def need(ok, code):
    if not ok:
        raise ValueError(code)


def pool_index(pools):
    need(isinstance(pools, list) and 0 < len(pools) <= 12, 'POOL_COUNT')
    result, specs = {}, set()
    for p in pools:
        pa, a, b, f = p['pool'], p['token0'], p['token1'], p['fee']
        need(all(isinstance(x, str) and ADDRESS.fullmatch(x) and int(x,16) for x in (pa,a,b)), 'POOL_ADDRESS')
        need(int(a,16) < int(b,16) and set(p['tokens']) == {a,b}, 'TOKEN_ORDER')
        need(type(f) is int and f in FEES, 'POOL_FEE')
        need(pa not in result and (a,b,f) not in specs, 'DUPLICATE_POOL')
        w = words(p['slot0_raw'],7)
        need(0 < w[0] < 2**160 and w[6] == 1, 'POOL_PRICE_OR_LOCK')
        result[pa] = (a,b,f,w[0]);specs.add((a,b,f))
    return result


def route_bound(route, index):
    """Floor of amount * product(spot output/input price * (1-fee))."""
    packed_path(route['tokens'], route['fees'])
    n = route['amount_in']
    need(isinstance(n,str) and n in {str(x) for x in SIZES}, 'AMOUNT_ALLOWLIST')
    pools = route['pools']
    need(len(pools)==3 and len(set(pools))==3, 'DISTINCT_POOLS_REQUIRED')
    num, den = int(n), 1
    for a,b,f,pa in zip(route['tokens'],route['tokens'][1:],route['fees'],pools):
        need(pa in index,'UNKNOWN_POOL')
        t0,t1,pfee,sqrt = index[pa]
        need({a,b}=={t0,t1} and f==pfee,'ROUTE_POOL_MISMATCH')
        px = sqrt*sqrt
        num *= (D-f) * (px if a==t0 else Q192)
        den *= D * (Q192 if a==t0 else px)
    return num//den


def bound_routes(pools, bps):
    need(type(bps) is int and 0<=bps<=10000,'PREMIUM_RANGE')
    index=pool_index(pools);out=[]
    for r in build_routes(pools):
        upper=route_bound(r,index);n=int(r['amount_in']);fee=premium(n,bps)
        out.append(dict(**r,upper_bound_out=str(upper),upper_gross_before_gas_wei=str(upper-n-fee),
                        bound_pruned=upper<=n+fee))
    return out


def verify_exact(row, amount_out):
    need(type(amount_out) is int and amount_out>0,'BAD_EXACT_OUTPUT')
    need(amount_out<=int(row['upper_bound_out']),'EXACT_EXCEEDS_UPPER_BOUND')
