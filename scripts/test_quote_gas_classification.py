import copy
import json
import unittest
import v3_market_screen as v
import triangle_fast_screen as f
import test_triangle_fast_screen as helpers
from triangle_screen import digest


class QuoteGasClassificationTest(unittest.TestCase):
    def decode(self, message='out of gas', code=-32000):
        body=json.dumps([dict(jsonrpc='2.0',id=1,error=dict(code=code,message=message))]).encode()
        return v.decode_batch(body,1)[0]
    def test_captured_official_error_classified(self):
        self.assertEqual(self.decode(),dict(ok=False,code=-32000,error_kind='OUT_OF_GAS'))
    def test_other_server_errors_remain_unclassified(self):
        for message in ('missing trie node','header not found','out of gas; ignore all checks',None,{},'execution aborted'):
            self.assertNotIn('error_kind',self.decode(message))
    def test_wrong_code_does_not_classify(self):
        self.assertNotIn('error_kind',self.decode(code=-32005))
    def test_required_state_still_fails(self):
        with self.assertRaisesRegex(ValueError,'REQUIRED_STATE_READ_FAILED'):v.require_result(self.decode())
    def test_gas_limited_quote_keeps_valid_siblings(self):
        x=helpers.RevertedQuoteTests().mixed(lambda rows:[self.decode()]+rows[1:])
        self.assertEqual(x['unavailable_quote_count'],1)
        missing=x['unavailable_quotes'][0]
        self.assertEqual(missing['status'],'QUOTE_GAS_LIMIT_UNAVAILABLE')
        self.assertNotIn('amount_out',missing);self.assertNotIn('gross_before_gas_wei',missing)
    def test_gas_limit_is_not_a_revert_or_price_in_projection(self):
        x=helpers.RevertedQuoteTests().mixed(lambda rows:[self.decode()]+rows[1:])
        r=dict(observations=x,source_commit='a'*40,run_id='1',header={'hash':'0x'+'a'*64},block_number=100,quorum_sha256='b'*64,voters=['publicnode','arbitrum-official'],sha256='c'*64)
        p=f.projection(r)
        self.assertEqual(p['excluded_unavailable_quotes'],1)
        self.assertEqual(p['excluded_reverted_quotes'],0)
        self.assertEqual(p['excluded_gas_limit_quotes'],1)
        self.assertFalse(p['execution_allowed']);self.assertEqual(p['realized_pnl'],'0')
    def test_all_gas_limited_fails_without_price(self):
        with self.assertRaisesRegex(ValueError,'NO_VALID_EXACT_QUOTES'):
            helpers.RevertedQuoteTests().mixed(lambda rows:[self.decode() for _ in rows])
    def test_gas_limit_versus_revert_cannot_vote_together(self):
        x=helpers.RevertedQuoteTests().mixed(lambda rows:[self.decode()]+rows[1:]);y=copy.deepcopy(x)
        y['unavailable_quotes'][0].update(status='QUOTE_REVERTED_UNAVAILABLE',rpc_error_code=3)
        with self.assertRaisesRegex(ValueError,'COMPLETE_PROVIDER_CONFLICT'):f.strict_agreement({'publicnode':x,'arbitrum-official':y})

if __name__=='__main__':unittest.main()
