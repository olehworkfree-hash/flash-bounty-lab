import copy
import unittest
import triangle_screen as t


def raw(nums): return '0x'+''.join(t.v.uint(x) for x in nums)
def encoded(out=999): return raw([out,128,256,12345,3,2**96,2**96,2**96,3,0,1,2])
def fixtures():
    p=lambda a,b,n:dict(pool='0x'+format(n,'040x'),fee=500,token0=a,token1=b,kind='v3')
    venues=[p(t.v.WETH,t.v.USDC,11),p(t.v.WETH,t.v.USDCE,12)]
    stable=[p(t.v.USDC,t.v.USDCE,13)]
    q=dict(header={'hash':'0x'+'1'*64},block_number=1,state_voters=['publicnode','arbitrum-official'],state={'premium_raw':raw([5])})
    routes=t.routes(venues,stable)
    rows=[]
    for r in routes:
        for amount in t.SIZES:
            fee=t.v.premium(amount,5);out=amount-1
            rows.append(dict(route_id=r['id'],amount_in=str(amount),fee_wei=str(fee),status='NO_EDGE_BEFORE_GAS',
                quote=t.decode_quote(encoded(out)),gross_before_gas_wei=str(out-amount-fee)))
    s=dict(quorum_sha256=t.v.digest(q),header=q['header'],block_number=1,policy=copy.deepcopy(t.POLICY),
        execution_allowed=False,realized_pnl='0',voters=q['state_voters'][:],
        observations=dict(venues=venues,stable_pools=stable,routes=routes,premium_bps=5,quote_rows=rows),
        counts=dict(routes=2,requested=6,quoted=6,unavailable=0,positive_before_gas=0))
    return q,s


class TriangleTests(unittest.TestCase):
    def test_path_length_and_both_directions(self):
        for tokens in ([t.v.WETH,t.v.USDC,t.v.USDCE,t.v.WETH],[t.v.WETH,t.v.USDCE,t.v.USDC,t.v.WETH]):
            b=t.path_bytes(tokens,[100,500,3000]);self.assertEqual(len(b),89)
            self.assertEqual(b[:20],bytes.fromhex(t.v.WETH[2:]));self.assertEqual(b[-20:],b[:20])
            self.assertEqual(int.from_bytes(b[20:23],'big'),100)
    def test_native_and_bridged_are_not_aliases(self):
        with self.assertRaises(ValueError):t.path_bytes([t.v.WETH,t.v.USDC,t.v.USDC,t.v.WETH],[500]*3)
    def test_fees_are_allowlisted_integers(self):
        for fees in ([10000]*3,[True,500,500],[500,500]):
            with self.assertRaises(ValueError):t.path_bytes([t.v.WETH,t.v.USDC,t.v.USDCE,t.v.WETH],fees)
    def test_dynamic_calldata_layout(self):
        tokens=[t.v.WETH,t.v.USDC,t.v.USDCE,t.v.WETH]
        data=t.quote_data(tokens,[500]*3,t.SIZES[0]);self.assertEqual(data[:10],t.SELECTOR)
        self.assertEqual(len(bytes.fromhex(data[2:])),196)
        w=t.v.words('0x'+data[10:10+192],3);self.assertEqual(w,[64,t.SIZES[0],89])
        self.assertEqual(bytes.fromhex(data[10+192:])[:89],t.path_bytes(tokens,[500]*3))
        self.assertEqual(bytes.fromhex(data[10+192:])[89:],bytes(7))
    def test_quote_size_bound(self):
        for amount in (0,1,-1,True,10**18):
            with self.assertRaises(ValueError):t.quote_data([t.v.WETH,t.v.USDC,t.v.USDCE,t.v.WETH],[500]*3,amount)
    def test_quote_decode_excludes_internal_gas(self):
        q=t.decode_quote(encoded());self.assertEqual(q['amount_out'],'999');self.assertNotIn('gas',q)
        self.assertEqual(q['ticks_crossed'],[0,1,2])
    def test_offsets_lengths_trailing_bytes_fail(self):
        for index,value in ((1,160),(2,288),(4,2),(8,4)):
            w=t.v.words(encoded(),12);w[index]=value
            with self.assertRaises(ValueError):t.decode_quote(raw(w))
        with self.assertRaises(ValueError):t.decode_quote(encoded()+'00'*32)
    def test_quote_overflow_and_zero_fail(self):
        for index,value in ((0,0),(3,0),(5,0),(6,2**160),(9,2**32)):
            w=t.v.words(encoded(),12);w[index]=value
            with self.assertRaises(ValueError):t.decode_quote(raw(w))
    def test_routes_both_orders_and_distinct_pools(self):
        _,s=fixtures();rs=s['observations']['routes'];self.assertEqual(len(rs),2)
        self.assertTrue(all(len(set(r['pools']))==3 for r in rs));self.assertNotEqual(rs[0]['path'],rs[1]['path'])
    def test_duplicate_pool_is_rejected(self):
        _,s=fixtures();o=s['observations'];o['stable_pools'][0]['pool']=o['venues'][0]['pool']
        with self.assertRaises(ValueError):t.routes(o['venues'],o['stable_pools'])
    def test_missing_stable_edge_means_no_routes(self):
        _,s=fixtures();self.assertEqual(t.routes(s['observations']['venues'],[]),[])
    def test_audit_recomputes_successful_quotes(self):
        q,s=fixtures();self.assertEqual(t.audit(q,s)['quoted'],6)
    def test_premium_tamper(self):
        q,s=fixtures();s['observations']['quote_rows'][0]['fee_wei']='0'
        with self.assertRaisesRegex(ValueError,'FLASH_FEE'):t.audit(q,s)
    def test_profit_tamper_even_if_outer_checksum_recomputed(self):
        q,s=fixtures();s['observations']['quote_rows'][0]['gross_before_gas_wei']='1';s['sha256']=t.v.digest(s)
        with self.assertRaisesRegex(ValueError,'PROFIT_ARITHMETIC'):t.audit(q,s)
    def test_missing_duplicated_or_extra_quote(self):
        for method in ('missing','duplicate','extra'):
            q,s=fixtures();rows=s['observations']['quote_rows']
            if method=='missing':rows.pop()
            elif method=='duplicate':rows[1]=copy.deepcopy(rows[0])
            else:rows.append(copy.deepcopy(rows[0]))
            with self.assertRaisesRegex(ValueError,'QUOTE_SET'):t.audit(q,s)
    def test_unavailable_is_not_a_loss_or_zero_output(self):
        q,s=fixtures();r=s['observations']['quote_rows'][0];r.pop('quote');r.pop('gross_before_gas_wei')
        r.update(status='QUOTE_UNAVAILABLE',reason='QUOTER_CALL_FAILED',rpc_code=-32000)
        s['counts'].update(quoted=5,unavailable=1);self.assertEqual(t.audit(q,s)['unavailable'],1)
        r['gross_before_gas_wei']='0'
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE_NOT_PROFIT'):t.audit(q,s)
    def test_counts_tamper(self):
        q,s=fixtures();s['counts']['positive_before_gas']=1
        with self.assertRaisesRegex(ValueError,'QUOTE_COUNTS'):t.audit(q,s)
    def test_single_or_duplicate_voter(self):
        for voters in (['publicnode'],['publicnode','publicnode']):
            q,s=fixtures();s['voters']=voters
            with self.assertRaisesRegex(ValueError,'QUOTE_QUORUM'):t.audit(q,s)
    def test_source_link_fails(self):
        q,s=fixtures();s['quorum_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'SOURCE_LINK'):t.audit(q,s)
    def test_live_or_paper_profit_prohibited(self):
        for key,value in [('execution_allowed',True),('realized_pnl','10')]:
            q,s=fixtures();s[key]=value
            with self.assertRaisesRegex(ValueError,'RESEARCH_POLICY'):t.audit(q,s)
    def test_path_metadata_tamper(self):
        q,s=fixtures();s['observations']['routes'][0]['fees'][0]=100
        with self.assertRaisesRegex(ValueError,'ROUTE_SET'):t.audit(q,s)
    def test_positive_quote_is_only_unverified_candidate(self):
        q,s=fixtures();r=s['observations']['quote_rows'][0]
        out=int(r['amount_in'])+int(r['fee_wei'])+1;r['quote']['amount_out']=str(out)
        r.update(status='CANDIDATE_UNVERIFIED',gross_before_gas_wei='1');s['counts']['positive_before_gas']=1
        self.assertEqual(t.audit(q,s)['positive_before_gas'],1);self.assertFalse(s['execution_allowed'])
    def test_third_complete_provider_disagreement_fails(self):
        with self.assertRaisesRegex(ValueError,'COMPLETE_PROVIDER_CONFLICT'):
            t.strict_agreement({'arbitrum-official':{'q':1},'publicnode':{'q':1},'alchemy-public':{'q':2}})
    def test_all_fee_combinations_are_bounded(self):
        _,s=fixtures();o=s['observations'];edges=[]
        for i,p in enumerate(o['venues']+o['stable_pools']):
            for j,fee in enumerate(t.FEES):edges.append(dict(p,fee=fee,pool='0x'+format(100+i*3+j,'040x')))
        r=t.routes(edges[:6],edges[6:]);self.assertEqual(len(r),54)
        self.assertEqual(len(r)*len(t.SIZES),162)

if __name__=='__main__':unittest.main()
