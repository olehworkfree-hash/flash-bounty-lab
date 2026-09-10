import copy
import unittest
from unittest.mock import patch
from triangle_screen import *
from run_triangle_fork import validate_selection


def mock_pools():
    return [dict(tokens=list(pair),fee=fee,pool='0x'+format(i*4+j+1,'040x')) for i,pair in enumerate(PAIRS) for j,fee in enumerate(FEES)]


def quote_raw(amount=200):
    return '0x'+''.join(uint(x) for x in [amount,128,256,10000,3,2**96,2**96,2**96,3,0,1,2])


def fixture():
    h=dict(number=hex(100),timestamp=hex(1000),hash='0x'+'a'*64)
    q=dict(status='PASS',historical=False,header=h,block_number=100,state_voters=['arbitrum-official','publicnode'],state=dict(premium_raw='0x'+uint(5)))
    q['evidence_sha256']=digest(q)
    pools=mock_pools(); rows=build_routes(pools)
    for r in rows:
        n=int(r['amount_in']);fee=premium(n,5)
        r.update(amount_out=str(n-1),premium_wei=str(fee),gross_before_gas_wei=str(-1-fee),status='NO_EDGE_BEFORE_GAS')
        r['candidate_id']=digest(dict(block_hash=h['hash'],route=r))
    s=dict(schema='flash.triangle_screen.v1',status='PASS',execution_allowed=False,realized_pnl='0',header=h,block_number=100,
        quorum_sha256=q['evidence_sha256'],voters=q['state_voters'],observations=dict(pools=pools,rows=rows,premium_bps=5),
        requested=len(rows),quoted=len(rows),positive_before_gas=0,matched_fork_selection=select_candidates(rows))
    s['sha256']=digest(s)
    return q,s


def seal(s):
    s.pop('sha256',None);s['sha256']=digest(s)


class TriangleTest(unittest.TestCase):
    def test_path_89_bytes(self):self.assertEqual(len(packed_path([WETH,USDC,USDCE,WETH],[100,500,3000])),89)
    def test_abi_head_tail(self):
        raw=bytes.fromhex(encode_quote([WETH,USDC,USDCE,WETH],[100,500,3000],SIZES[0])[2:])
        self.assertEqual(raw[:4].hex(),'cdca1753');self.assertEqual(len(raw),196)
        self.assertEqual(int.from_bytes(raw[4:36],'big'),64);self.assertEqual(int.from_bytes(raw[68:100],'big'),89)
        self.assertEqual(raw[100:189],packed_path([WETH,USDC,USDCE,WETH],[100,500,3000]));self.assertEqual(raw[189:],bytes(7))
    def test_wrong_path_rejected(self):
        for tokens in [[WETH,USDC,WETH],[USDC,WETH,USDCE,USDC],[WETH,USDC,USDC,WETH]]:
            with self.assertRaises(ValueError):packed_path(tokens,[100,500,3000])
    def test_fee_allowlist(self):
        for fee in [-1,0,42,2**24,True]:
            with self.assertRaises(ValueError):packed_path([WETH,USDC,USDCE,WETH],[100,fee,3000])
    def test_amount_allowlist(self):
        for amount in [0,1,-1,True,10**20]:
            with self.assertRaises(ValueError):encode_quote([WETH,USDC,USDCE,WETH],[100,500,3000],amount)
    def test_quote_decoder(self):self.assertEqual(decode_quote(quote_raw())['amount_out'],'200')
    def test_bad_abi_rejected(self):
        for index,value in [(1,160),(2,0),(4,2),(8,4),(0,0),(3,0),(5,0),(6,2**160),(10,2**32)]:
            raw=words(quote_raw(),12);raw[index]=value
            with self.assertRaises(ValueError):decode_quote('0x'+''.join(uint(x) for x in raw))
    def test_extra_bytes_rejected(self):
        with self.assertRaises(ValueError):decode_quote(quote_raw()+'00'*32)
    def test_full_route_count(self):self.assertEqual(len(build_routes(mock_pools())),512)
    def test_distinct_pools_each_route(self):
        for r in build_routes(mock_pools()):self.assertEqual(len(set(r['pools'])),3)
    def test_duplicate_pool_rejected(self):
        p=mock_pools();p[4]['pool']=p[0]['pool']
        with self.assertRaises(ValueError):build_routes(p)
    def test_empty_routes_rejected(self):
        with self.assertRaises(ValueError):build_routes([])
    def test_selection_bounded(self):
        rows=[dict(gross_before_gas_wei=str(n)) for n in range(10)]
        self.assertEqual([r['gross_before_gas_wei'] for r in select_candidates(rows)],['9','8','7'])
    def test_best_negative_selected(self):self.assertEqual(select_candidates([{'gross_before_gas_wei':'-20'},{'gross_before_gas_wei':'-2'}])[0]['gross_before_gas_wei'],'-2')
    def test_no_quote_rejected(self):
        with self.assertRaises(ValueError):select_candidates([dict(status='QUOTE_UNAVAILABLE')])
    def test_selection_binding_passes(self):q,s=fixture();self.assertEqual(len(validate_selection(q,s,1001)[3]),1)
    def test_corrupted_hash_rejected(self):
        q,s=fixture();s['quoted']=2
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_single_provider_rejected(self):
        q,s=fixture();s['voters']=['publicnode'];seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_earnings_claim_rejected(self):
        q,s=fixture();s['realized_pnl']='1';seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_source_link_rejected(self):
        q,s=fixture();s['quorum_sha256']='x';seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_altered_selection_rejected(self):
        q,s=fixture();s['matched_fork_selection']=[];seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_altered_counts_rejected(self):
        q,s=fixture();s['positive_before_gas']=1;seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_arithmetic_and_row_seal_rejected(self):
        q,s=fixture();r=s['observations']['rows'][0];r['gross_before_gas_wei']='100';r.pop('candidate_id');r['candidate_id']=digest(dict(block_hash=q['header']['hash'],route=r));seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_pool_link_rejected(self):
        q,s=fixture();s['observations']['pools']=[];seal(s)
        with self.assertRaises(ValueError):validate_selection(q,s,1001)
    def test_stale_rejected(self):
        q,s=fixture()
        with self.assertRaises(ValueError):validate_selection(q,s,10000)
    def test_reader_cannot_send_transaction(self):
        reader=Reader('publicnode',{})
        with self.assertRaises(ValueError):reader.read([('eth_sendRawTransaction',[])])
if __name__=='__main__':unittest.main()
