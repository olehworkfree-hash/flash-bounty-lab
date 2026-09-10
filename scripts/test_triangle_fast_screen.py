import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import triangle_fast_screen as f
from triangle_bounds import bound_routes
from test_triangle_bounds import pools
from triangle_screen import digest,uint,encode_quote

class FakeReader:
    def __init__(self,*args,**kwargs):self.count=0
    def call(self,target,data):return target,data
    def read(self,calls):
        self.count+=len(calls);out=[]
        ps=pools();rows=bound_routes(ps,5)
        lookup={encode_quote(r['tokens'],r['fees'],int(r['amount_in'])):int(r['upper_bound_out'])-1 for r in rows}
        for _,data in calls:
            n=lookup[data]
            out.append(dict(ok=True,result='0x'+''.join(uint(x) for x in (n,128,256,10000,3,2**96,2**96,2**96,3,0,0,0))))
        return out

class FastScreenTests(unittest.TestCase):
    def captured(self):
        q=dict(header={'hash':'0x'+'a'*64},block_number=100,state={'premium_raw':'0x'+uint(5)})
        with patch.object(f,'JournalReader',FakeReader),patch.object(f.t,'discover',return_value=(pools(),[],{},5)),patch.object(f.t,'header',return_value=q['header']):
            return f.capture('publicnode',q,Path('/unused-mock'))
    def test_all_negative_get_one_diagnostic(self):
        x=self.captured();self.assertEqual(x['route_count'],8);self.assertEqual(x['exact_quote_count'],1)
        self.assertEqual(x['bound_pruned'],8);self.assertTrue(x['diagnostic_quote_without_candidate'])
    def test_all_bounds_retained(self):
        x=self.captured();self.assertEqual(len(x['bound_rows']),8)
    def test_projection_cannot_present_bounds_as_quotes(self):
        x=self.captured();r=dict(observations=x,source_commit='a'*40,run_id='1',header={'hash':'0x'+'a'*64},
                                block_number=100,quorum_sha256='b'*64,voters=['publicnode','arbitrum-official'],sha256='c'*64)
        p=f.projection(r);self.assertEqual(p['quoted'],1);self.assertEqual(p['requested'],1)
        self.assertEqual(p['projection_scope'],'EXACT_QUOTED_SUBSET_ONLY')
        self.assertFalse(p['execution_allowed']);self.assertEqual(p['realized_pnl'],'0')
        self.assertEqual(p['bound_screen_sha256'],'c'*64)
        self.assertNotIn('upper_bound_out',p['observations']['rows'][0])
    def test_projection_checksum(self):
        x=self.captured();r=dict(observations=x,source_commit='a'*40,run_id='1',header={'hash':'0x'+'a'*64},
                                block_number=100,quorum_sha256='b'*64,voters=['publicnode','arbitrum-official'],sha256='c'*64)
        p=f.projection(r);h=p.pop('sha256');self.assertEqual(h,digest(p))
    def test_worker_rejects_untrusted_quorum_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=Path(tmp)/'q.json';q.write_text('{}');out=Path(tmp)/'result.json'
            with patch.object(f,'capture') as cap:
                self.assertEqual(f.worker('publicnode',q,out,'test'),1);cap.assert_not_called()
            self.assertEqual(json.loads(out.read_text())['status'],'FAILED')
    def test_bad_quoter_response_fails_provider(self):
        q=dict(header={'hash':'0x'+'a'*64},block_number=100,state={'premium_raw':'0x'+uint(5)})
        with patch.object(f,'JournalReader',FakeReader),patch.object(f.t,'discover',return_value=(pools(),[],{},5)),patch.object(FakeReader,'read',return_value=[dict(ok=False,code=-32000)]):
            with self.assertRaisesRegex(ValueError,'REQUIRED_STATE_READ_FAILED'):f.capture('publicnode',q,Path('/unused-mock'))
    def test_premium_mismatch_stops_before_quotes(self):
        q=dict(header={'hash':'0x'+'a'*64},block_number=100,state={'premium_raw':'0x'+uint(10)})
        with patch.object(f,'JournalReader',FakeReader),patch.object(f.t,'discover',return_value=(pools(),[],{},5)):
            with self.assertRaisesRegex(ValueError,'PREMIUM_DISAGREEMENT'):f.capture('publicnode',q,Path('/unused-mock'))
    def test_reorg_header_is_rejected(self):
        q=dict(header={'hash':'0x'+'a'*64},block_number=100,state={'premium_raw':'0x'+uint(5)})
        with patch.object(f,'JournalReader',FakeReader),patch.object(f.t,'discover',return_value=(pools(),[],{},5)),patch.object(f.t,'header',return_value={'hash':'0x'+'b'*64}):
            with self.assertRaisesRegex(ValueError,'BLOCK_CHANGED'):f.capture('publicnode',q,Path('/unused-mock'))

class RevertedQuoteTests(unittest.TestCase):
    def mixed(self, replacement=None):
        ps=pools()
        ps[1]['slot0_raw']='0x'+''.join(uint(x) for x in (2*2**96,0,0,1,1,0,1))
        q=dict(header={'hash':'0x'+'a'*64},block_number=100,state={'premium_raw':'0x'+uint(5)})
        candidates=[r for r in bound_routes(ps,5) if not r['bound_pruned']]
        candidates.sort(key=lambda r:int(r['upper_gross_before_gas_wei']),reverse=True)
        items=[dict(ok=True,result='0x'+''.join(uint(x) for x in (int(r['upper_bound_out'])-1,128,256,10000,3,2**96,2**96,2**96,3,0,0,0))) for r in candidates]
        items[0]=dict(ok=False,code=3)
        if replacement:items=replacement(items)
        with patch.object(f,'JournalReader',FakeReader),patch.object(f.t,'discover',return_value=(ps,[],{},5)),patch.object(f.t,'header',return_value=q['header']),patch.object(FakeReader,'read',return_value=items):
            return f.capture('publicnode',q,Path('/unused-mock'))
    def test_explicit_revert_retains_other_quotes(self):
        x=self.mixed()
        self.assertEqual(x['unavailable_quote_count'],1)
        self.assertEqual(x['exact_quote_count']+1,x['quote_attempt_count'])
        self.assertEqual(x['unquoted_survivors'],0)
        self.assertNotIn('amount_out',x['unavailable_quotes'][0])
        self.assertNotIn('gross_before_gas_wei',x['unavailable_quotes'][0])
    def test_all_reverted_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'NO_VALID_EXACT_QUOTES'):
            self.mixed(lambda rows:[dict(ok=False,code=3) for _ in rows])
    def test_missing_response_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'QUOTE_RESPONSE_COUNT'):
            self.mixed(lambda rows:rows[:-1])
    def test_rate_limit_error_is_not_execution_revert(self):
        with self.assertRaisesRegex(ValueError,'REQUIRED_STATE_READ_FAILED'):
            self.mixed(lambda rows:[dict(ok=False,code=-32005)]+rows[1:])
    def test_unknown_rpc_error_is_not_execution_revert(self):
        with self.assertRaisesRegex(ValueError,'REQUIRED_STATE_READ_FAILED'):
            self.mixed(lambda rows:[dict(ok=False,code=-32000)]+rows[1:])
    def test_string_revert_code_rejected(self):
        with self.assertRaisesRegex(ValueError,'REQUIRED_STATE_READ_FAILED'):
            self.mixed(lambda rows:[dict(ok=False,code='3')]+rows[1:])
    def test_malformed_success_is_not_dropped(self):
        with self.assertRaises(ValueError):
            self.mixed(lambda rows:[dict(ok=True,result='0x')]+rows[1:])
    def test_revert_set_mismatch_blocks_agreement(self):
        x=self.mixed();y=copy.deepcopy(x);y['unavailable_quotes'][0]['rpc_error_code']=4
        with self.assertRaises(ValueError):
            f.strict_agreement({'publicnode':x,'arbitrum-official':y})
    def test_projection_contains_only_successes(self):
        x=self.mixed();r=dict(observations=x,source_commit='a'*40,run_id='1',header={'hash':'0x'+'a'*64},block_number=100,quorum_sha256='b'*64,voters=['publicnode','arbitrum-official'],sha256='c'*64)
        p=f.projection(r)
        self.assertEqual(p['excluded_reverted_quotes'],1)
        self.assertTrue(all('amount_out' in row for row in p['observations']['rows']))
        self.assertEqual(p['quoted'],x['exact_quote_count'])
        self.assertFalse(p['execution_allowed'])

if __name__=='__main__':unittest.main()
