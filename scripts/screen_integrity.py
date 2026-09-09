"""Offline accounting consistency checks, not RPC authenticity or a trading approval.

Recalculate every flash-loan fee and pre-gas result. Check V2 amounts from captured
reserves; V3 outputs still require independent RPC/fork verification. SHA256 is an
integrity checksum, not a signature. Never estimate gas from the quoter's gas field.
"""
import itertools
import re

SIZES = (10**15, 10**16, 10**17, 10**18)
U256 = 2**256
DEC = re.compile(r'(?:0|[1-9][0-9]{0,77})\Z')
SIGNED = re.compile(r'(?:0|-?[1-9][0-9]{0,77})\Z')
ADDRESS = re.compile(r'0x[0-9a-f]{40}\Z')


def need(condition, code):
    if not condition:
        raise ValueError(code)


def integer(value, signed=False):
    need(isinstance(value, str) and (SIGNED if signed else DEC).fullmatch(value), 'INTEGER_FORMAT')
    n = int(value)
    need(-U256 < n < U256 if signed else 0 <= n < U256, 'INTEGER_RANGE')
    return n


def v2_output(amount, reserve_in, reserve_out):
    need(reserve_in > 0 and reserve_out > 0, 'V2_RESERVES')
    return amount * 997 * reserve_out // (reserve_in * 1000 + amount * 997)


def audit_screen(quorum, screen):
    """Raise on inconsistent captured accounting; does not certify live prices."""
    try:
        return _audit_screen(quorum, screen)
    except (KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError('SCREEN_ACCOUNTING_SHAPE') from None


def _audit_screen(quorum, screen):
    need(isinstance(quorum, dict) and isinstance(screen, dict), 'SCREEN_ACCOUNTING_SHAPE')
    need(quorum.get('commit') == screen.get('source_commit') and
         quorum.get('run_id') == screen.get('run_id'), 'RUN_SOURCE_MISMATCH')
    need(screen.get('execution_allowed') is False and screen.get('realized_pnl') == '0', 'NO_LIVE_OR_EARNINGS')
    o = screen['observations']
    bps = o['premium_bps']
    need(type(bps) is int and 0 <= bps <= 10000, 'PREMIUM_RANGE')
    raw = quorum['state']['premium_raw']
    need(isinstance(raw, str) and re.fullmatch(r'0x[0-9a-fA-F]{64}', raw), 'PREMIUM_ABI')
    need(int(raw, 16) == bps, 'PREMIUM_STATE_MISMATCH')
    venues, rows = o['venues'], o['quote_rows']
    need(isinstance(venues, list) and 2 <= len(venues) <= 64, 'VENUE_COUNT')
    need(isinstance(rows, list) and 0 < len(rows) <= 10000, 'ROW_COUNT')
    by_id, pools = {}, set()
    for v in venues:
        name, pool, token = v['id'], v['pool'], v['token']
        need(isinstance(name, str) and 0 < len(name) <= 128 and name not in by_id, 'VENUE_ID')
        need(isinstance(pool, str) and ADDRESS.fullmatch(pool) and int(pool, 16) != 0 and pool not in pools, 'VENUE_POOL')
        need(isinstance(token, str) and ADDRESS.fullmatch(token) and int(token, 16) != 0, 'VENUE_TOKEN')
        need(isinstance(v['symbol'], str) and v['kind'] in ('v2', 'v3'), 'VENUE_TYPE')
        if v['kind'] == 'v2':
            need(v['fee'] == 3000 and type(v['fee']) is int, 'UNSUPPORTED_V2_FEE')
            for field in ('weth_reserve', 'usd_reserve'):
                need(0 < integer(v[field]) < 2**112, 'V2_RESERVES')
        by_id[name] = v
        pools.add(pool)
    expected = {(a['id'], b['id'], n) for a, b in itertools.permutations(venues, 2)
                if a['token'] == b['token'] for n in SIZES}
    seen, first_by_input, gross_values = set(), {}, []
    for r in rows:
        a, b, n = by_id[r['buy']], by_id[r['sell']], integer(r['amount_in'])
        key = (r['buy'], r['sell'], n)
        need(key in expected and key not in seen, 'DUPLICATE_OR_UNEXPECTED_ROUTE')
        seen.add(key)
        need(r['buy_pool'] == a['pool'] and r['sell_pool'] == b['pool'] and
             r['symbol'] == a['symbol'] == b['symbol'], 'ROUTE_IDENTITY')
        fee = (n * bps + 5000) // 10000
        need(integer(r['fee_wei']) == fee, 'FEE_ARITHMETIC')
        first, second = r['first_quote'], r['second_quote']
        need(isinstance(first, dict) and type(first.get('ok')) is bool, 'FIRST_QUOTE_SHAPE')
        fkey = (r['buy'], n)
        if fkey in first_by_input:
            need(first_by_input[fkey] == first, 'INCONSISTENT_FIRST_QUOTE')
        first_by_input[fkey] = first
        mid = integer(first['amount_out']) if first['ok'] else None
        if mid is not None:
            need(mid > 0, 'ZERO_SUCCESS_OUTPUT')
            if a['kind'] == 'v2':
                need(mid == v2_output(n, integer(a['weth_reserve']), integer(a['usd_reserve'])), 'V2_FIRST_ARITHMETIC')
            need(isinstance(second, dict) and type(second.get('ok')) is bool, 'SECOND_QUOTE_SHAPE')
        else:
            need(second is None, 'SECOND_WITHOUT_FIRST')
        complete = first['ok'] and second['ok']
        if not complete:
            need(r['status'] == 'QUOTE_UNAVAILABLE' and 'gross_before_gas_wei' not in r, 'UNAVAILABLE_MARKED_PROFIT')
            continue
        returned = integer(second['amount_out'])
        need(returned > 0, 'ZERO_SUCCESS_OUTPUT')
        if b['kind'] == 'v2':
            need(returned == v2_output(mid, integer(b['usd_reserve']), integer(b['weth_reserve'])), 'V2_SECOND_ARITHMETIC')
        gross = returned - n - fee
        need(integer(r['gross_before_gas_wei'], signed=True) == gross, 'GROSS_ARITHMETIC')
        need(r['status'] == ('POSITIVE_QUOTE_UNVERIFIED' if gross > 0 else 'NO_EDGE_BEFORE_GAS'), 'PROFIT_STATUS')
        gross_values.append(gross)
    need(seen == expected, 'INCOMPLETE_ROUTE_GRID')
    counts = {'rows_requested': len(rows), 'successful_quotes': len(gross_values),
              'unavailable_quotes': len(rows)-len(gross_values),
              'positive_before_gas': sum(g > 0 for g in gross_values)}
    for name, n in counts.items():
        need(type(screen[name]) is int and screen[name] == n, 'ACCOUNTING_COUNT_MISMATCH')
    need(bool(gross_values), 'NO_SUCCESSFUL_QUOTES')
    return dict(status='PASS', **counts, best_gross_before_gas_wei=str(max(gross_values)),
                execution_allowed=False, realized_pnl='0', v3_prices_independently_verified=False,
                exact_arbitrum_fee_known=False)
