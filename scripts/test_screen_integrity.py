import copy
import itertools
import unittest
from real_quorum import digest
from screen_integrity import audit_screen, integer, SIZES, v2_output


def seal(s):
    s.pop('sha256', None)
    s['sha256'] = digest(s)


def fixture(number=100, gross=-1):
    venues = [dict(id=name, pool='0x'+digit*40, token='0x'+'c'*40,
                   symbol='TEST', kind='v3') for name, digit in [('a','1'),('b','2')]]
    q = dict(status='PASS', historical=False, block_number=number,
             header=dict(number=hex(number), hash='0x'+format(number,'064x'), timestamp=hex(1000+number)),
             state_voters=['arbitrum-official','publicnode'], state={'premium_raw':'0x'+format(5,'064x')},
             commit='a'*40, run_id='1')
    q['evidence_sha256'] = digest(q)
    rows = []
    for a,b in itertools.permutations(venues,2):
        for n in SIZES:
            fee=(n*5+5000)//10000
            rows.append(dict(buy=a['id'], sell=b['id'], buy_pool=a['pool'], sell_pool=b['pool'],
                             symbol='TEST', amount_in=str(n), fee_wei=str(fee),
                             first_quote=dict(ok=True,amount_out='100000000'),
                             second_quote=dict(ok=True,amount_out=str(n+fee+gross)),
                             gross_before_gas_wei=str(gross),
                             status='POSITIVE_QUOTE_UNVERIFIED' if gross>0 else 'NO_EDGE_BEFORE_GAS'))
    s = dict(status='PASS', execution_allowed=False, realized_pnl='0', voters=q['state_voters'],
             quorum_sha256=q['evidence_sha256'], header=q['header'], block_number=number,
             rows_requested=len(rows), successful_quotes=len(rows), unavailable_quotes=0,
             positive_before_gas=len(rows) if gross>0 else 0, source_commit=q['commit'],run_id=q['run_id'],
             observations=dict(premium_bps=5, venues=venues, quote_rows=rows))
    seal(s)
    return q,s


class ScreenIntegrityTest(unittest.TestCase):
    def mutate(self, fn, code=None):
        q,s=fixture()
        fn(q,s)
        # The producer can recompute checksums, so test semantic checks, not just hashes.
        seal(s)
        if code:
            with self.assertRaisesRegex(ValueError, '^'+code+'$'): audit_screen(q,s)
        else:
            with self.assertRaises(ValueError): audit_screen(q,s)

    def test_honest_negative(self):
        q,s=fixture(); r=audit_screen(q,s)
        self.assertEqual(r['successful_quotes'],8)
        self.assertEqual(r['positive_before_gas'],0)
    def test_synthetic_positive_is_not_income(self):
        q,s=fixture(gross=42); r=audit_screen(q,s)
        self.assertEqual(r['positive_before_gas'],8)
        self.assertFalse(r['execution_allowed']);self.assertEqual(r['realized_pnl'],'0')
    def test_gross_forgery_with_recomputed_checksum(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(gross_before_gas_wei='999'), 'GROSS_ARITHMETIC')
    def test_wrong_loan_fee(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(fee_wei='0'), 'FEE_ARITHMETIC')
    def test_premium_disagrees_with_quorum(self):
        self.mutate(lambda q,s:s['observations'].update(premium_bps=10), 'PREMIUM_STATE_MISMATCH')
    def test_boolean_premium(self):
        self.mutate(lambda q,s:s['observations'].update(premium_bps=True), 'PREMIUM_RANGE')
    def test_malformed_abi(self):
        self.mutate(lambda q,s:q['state'].update(premium_raw='0x05'), 'PREMIUM_ABI')
    def test_duplicate_route(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'].append(copy.deepcopy(s['observations']['quote_rows'][0])), 'DUPLICATE_OR_UNEXPECTED_ROUTE')
    def test_missing_route(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'].pop(), 'INCOMPLETE_ROUTE_GRID')
    def test_route_pool_substitution(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(buy_pool='0x'+'f'*40), 'ROUTE_IDENTITY')
    def test_reversed_pool_same_leg(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(sell='a'), 'DUPLICATE_OR_UNEXPECTED_ROUTE')
    def test_duplicate_venue(self):
        self.mutate(lambda q,s:s['observations']['venues'].append(copy.deepcopy(s['observations']['venues'][0])), 'VENUE_ID')
    def test_duplicate_pool(self):
        self.mutate(lambda q,s:s['observations']['venues'][1].update(pool=s['observations']['venues'][0]['pool']), 'VENUE_POOL')
    def test_missing_quote(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(second_quote=None), 'SECOND_QUOTE_SHAPE')
    def test_boolean_success_flag(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0]['first_quote'].update(ok=1), 'FIRST_QUOTE_SHAPE')
    def test_wrong_count(self):
        self.mutate(lambda q,s:s.update(successful_quotes=True), 'ACCOUNTING_COUNT_MISMATCH')
    def test_wrong_status(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(status='POSITIVE_QUOTE_UNVERIFIED'), 'PROFIT_STATUS')
    def test_noncanonical_integers(self):
        for value in [True,1,1.0,'+1','01','1e18',' 1','1.0','-0','NaN','',str(2**256)]:
            with self.subTest(value=value),self.assertRaises(ValueError):integer(value)
    def test_signed_integers(self):
        self.assertEqual(integer('-123',signed=True),-123)
        self.assertEqual(integer('0',signed=True),0)
        with self.assertRaises(ValueError):integer('-0',signed=True)
    def test_wrong_source_commit(self):
        self.mutate(lambda q,s:s.update(source_commit='b'*40), 'RUN_SOURCE_MISMATCH')
    def test_wrong_run(self):
        self.mutate(lambda q,s:s.update(run_id='2'), 'RUN_SOURCE_MISMATCH')
    def test_live_execution_flag(self):
        self.mutate(lambda q,s:s.update(execution_allowed=True), 'NO_LIVE_OR_EARNINGS')
    def test_paper_earnings(self):
        self.mutate(lambda q,s:s.update(realized_pnl='42'), 'NO_LIVE_OR_EARNINGS')
    def test_partial_quote_is_not_success_or_profit(self):
        q,s=fixture();r=s['observations']['quote_rows'][0]
        r.update(second_quote=dict(ok=False,reason='UNAVAILABLE'),status='QUOTE_UNAVAILABLE')
        r.pop('gross_before_gas_wei')
        s.update(successful_quotes=7,unavailable_quotes=1)
        self.assertEqual(audit_screen(q,s)['unavailable_quotes'],1)
    def test_unavailable_with_fake_profit(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0].update(second_quote=dict(ok=False)), 'UNAVAILABLE_MARKED_PROFIT')
    def test_zero_success_output(self):
        self.mutate(lambda q,s:s['observations']['quote_rows'][0]['second_quote'].update(amount_out='0'), 'ZERO_SUCCESS_OUTPUT')
    def test_v2_formula(self):
        self.assertEqual(v2_output(1000,100000,100000),987)
    def test_v2_bad_first_leg(self):
        def change(q,s):s['observations']['venues'][0].update(kind='v2',fee=3000,weth_reserve=str(10**22),usd_reserve=str(10**13))
        self.mutate(change, 'V2_FIRST_ARITHMETIC')
    def test_unknown_fields_fail_closed(self):
        self.mutate(lambda q,s:s.pop('observations'), 'SCREEN_ACCOUNTING_SHAPE')


if __name__=='__main__':unittest.main()
