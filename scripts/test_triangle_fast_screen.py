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

if __name__=='__main__':unittest.main()
