import copy
import unittest
from session_screen import checked, summarize
from real_quorum import digest


from test_screen_integrity import fixture


def seal(s):
    s.pop('sha256',None);s['sha256']=digest(s)


class SessionTest(unittest.TestCase):
    def test_negative_session_not_earnings(self):
        r=summarize([fixture(100),fixture(105),fixture(110)])
        self.assertEqual(r['positive_quote_evaluations'],0)
        self.assertEqual(r['realized_pnl'],'0'); self.assertFalse(r['execution_allowed'])
    def test_positive_quote_not_executable(self):
        r=summarize([fixture(gross=42)])
        self.assertEqual(r['positive_quote_evaluations'],8);self.assertFalse(r['all_candidates_fork_verified'])
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):summarize([fixture(),fixture()])
    def test_reverse_order_rejected(self):
        with self.assertRaises(ValueError):summarize([fixture(102),fixture(100)])
    def test_integrity_rejected(self):
        q,s=fixture();s['rows_requested']=2
        with self.assertRaises(ValueError):summarize([(q,s)])
    def test_count_claim_rejected(self):
        q,s=fixture();s['positive_before_gas']=1;seal(s)
        with self.assertRaises(ValueError):summarize([(q,s)])
    def test_source_link_rejected(self):
        q,s=fixture();s['quorum_sha256']='x';seal(s)
        with self.assertRaises(ValueError):summarize([(q,s)])
    def test_single_provider_rejected(self):
        q,s=fixture();s['voters']=['publicnode'];seal(s)
        with self.assertRaises(ValueError):summarize([(q,s)])
    def test_wrong_height_rejected(self):
        q,s=fixture();s['block_number']=101;seal(s)
        with self.assertRaises(ValueError):summarize([(q,s)])
    def test_claimed_earnings_rejected(self):
        q,s=fixture();s['realized_pnl']='42';seal(s)
        with self.assertRaises(ValueError):summarize([(q,s)])
    def test_round_bound_rejected(self):
        for v in [[],[fixture(n) for n in range(4)]]:
            with self.assertRaises(ValueError):summarize(v)
    def test_gaps_not_latency_measurement(self):
        r=summarize([fixture(100),fixture(200)])
        self.assertFalse(r['latency_survival_verified'])
if __name__=='__main__':unittest.main()
