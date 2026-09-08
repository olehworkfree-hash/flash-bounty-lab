import json
import unittest
import v3_market_screen as v


def result(n):
    return {'jsonrpc':'2.0','id':1,'result':'0x'+v.uint(n)}


class V3ScreenTests(unittest.TestCase):
    def test_uint_max_and_overflow(self):
        self.assertEqual(len(v.uint(2**256-1)),64)
        for x in (-1,2**256,True,1.2):
            with self.assertRaises(ValueError): v.uint(x)
    def test_address_roundtrip(self):
        self.assertEqual(v.address('0x'+v.addr(v.WETH)),v.WETH)
    def test_address_reject(self):
        for a in ('0x1','https://rpc.test', '0x'+'g'*40):
            with self.assertRaises(ValueError): v.addr(a)
    def test_tuple_layout(self):
        data=v.quote_data(v.WETH,v.USDC,10**18,500)
        self.assertEqual(len(data),10+64*5)
        self.assertEqual(data[:10],'0xc6a5026a')
        self.assertEqual(v.words('0x'+data[10:],5)[2:],[10**18,500,0])
    def test_bad_quote_input(self):
        for amount,fee,out in [(0,500,v.USDC),(1,200,v.USDC),(1,500,v.WETH)]:
            with self.assertRaises(ValueError): v.quote_data(v.WETH,out,amount,fee)
    def test_quote_decode(self):
        q,gas=v.decode_quote('0x'+''.join(v.uint(n) for n in (23,2**96,2,100000)))
        self.assertEqual(q['amount_out'],'23'); self.assertNotIn('gas',q); self.assertEqual(gas,100000)
    def test_malformed_quote(self):
        for nums in [(0,2**96,1,1),(1,2**160,1,1),(1,2**96,2**32,1),(1,2**96,1,0)]:
            with self.assertRaises(ValueError): v.decode_quote('0x'+''.join(v.uint(n) for n in nums))
    def test_short_quote_rejected(self):
        with self.assertRaises(ValueError): v.decode_quote('0x'+v.uint(1))
    def test_batch_order(self):
        a,b=result(10),result(20); b['id']=2
        got=v.decode_batch(json.dumps([b,a]).encode(),2)
        self.assertEqual(v.words(got[0]['result'],1),[10])
    def test_rpc_error_is_not_zero_quote(self):
        body=json.dumps([{'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'private/url'}}]).encode()
        self.assertEqual(v.decode_batch(body,1),[{'ok':False,'code':-32000}])
    def test_bool_id_rejected(self):
        a=result(1); a['id']=True
        with self.assertRaises(ValueError): v.decode_batch(json.dumps([a]).encode(),1)
    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError): v.decode_batch(json.dumps([result(1),result(2)]).encode(),2)
    def test_result_error_conflict(self):
        a=result(1); a['error']={'code':-32000}
        with self.assertRaises(ValueError): v.decode_batch(json.dumps([a]).encode(),1)
    def test_bad_result_rejected(self):
        for raw in ('0xg1',None,'0x1'):
            a=result(1); a['result']=raw
            with self.assertRaises(ValueError): v.decode_batch(json.dumps([a]).encode(),1)
    def test_payload_limit(self):
        with self.assertRaises(ValueError): v.decode_batch(b' '* (v.LIMIT+1),1)
    def test_send_method_rejected(self):
        reader=v.Reader('arbitrum-official',{})
        with self.assertRaises(ValueError): reader.read([('eth_sendRawTransaction',[])])
    def test_budget_rejected_without_network(self):
        reader=v.Reader('arbitrum-official',{}); reader.count=v.MAX_CALLS
        with self.assertRaises(ValueError): reader.read([reader.code(v.WETH)])
    def test_v2_formula_used_only_for_v2(self):
        class Fake:
            def read(self,calls):
                assert not calls
                return []
        pool=dict(kind='v2',weth_reserve='100000',usd_reserve='200000')
        q=v.quote_stage(Fake(),[('one',pool,v.WETH,v.USDC,1000)])
        self.assertEqual(int(q['one']['amount_out']),v.amount_out(1000,100000,200000))
    def test_roundtrip_classification_and_pool_reuse(self):
        a=dict(id='a',pool='p1',token=v.USDC,symbol='USDC')
        b=dict(id='b',pool='p2',token=v.USDC,symbol='USDC')
        first={(x,10000):dict(ok=True,amount_out='20000') for x in ('a','b')}
        second={('a','b',10000):dict(ok=True,amount_out='10001'),('b','a',10000):dict(ok=True,amount_out='10030')}
        rows=v.route_rows([a,b],first,second,5,(10000,))
        self.assertEqual([x['status'] for x in rows],['NO_EDGE_BEFORE_GAS','POSITIVE_QUOTE_UNVERIFIED'])
        b['pool']='p1'; self.assertEqual(v.route_rows([a,b],first,second,5,(10000,)),[])
    def test_usdc_and_usdce_never_mixed(self):
        a=dict(id='a',pool='p1',token=v.USDC,symbol='USDC')
        b=dict(id='b',pool='p2',token=v.USDCE,symbol='USDC.e')
        self.assertEqual(v.route_rows([a,b],{}, {},5,(1,)),[])
    def test_failure_not_no_edge(self):
        a=dict(id='a',pool='p1',token=v.USDC,symbol='USDC')
        b=dict(id='b',pool='p2',token=v.USDC,symbol='USDC')
        rows=v.route_rows([a,b],{('a',1):{'ok':False},('b',1):{'ok':False}}, {},5,(1,))
        self.assertTrue(all(x['status']=='QUOTE_UNAVAILABLE' and 'gross_before_gas_wei' not in x for x in rows))
    def test_quorum_integrity_freshness_and_voters(self):
        q=dict(status='PASS',historical=False,state_voters=['arbitrum-official','publicnode'],header={'timestamp':hex(1000)})
        q['evidence_sha256']=v.digest(q)
        self.assertEqual(v.validate_quorum(q,1001)[1],q['evidence_sha256'])
        with self.assertRaises(ValueError): v.validate_quorum(q,2000)
        q['status']='FAIL'
        with self.assertRaises(ValueError): v.validate_quorum(q,1001)
    def test_single_provider_and_historical_blocked(self):
        for historical,voters in [(True,['arbitrum-official','publicnode']),(False,['publicnode'])]:
            q=dict(status='PASS',historical=historical,state_voters=voters,header={'timestamp':hex(1000)})
            q['evidence_sha256']=v.digest(q)
            with self.assertRaises(ValueError): v.validate_quorum(q,1001)
    def test_two_provider_agreement_required(self):
        with self.assertRaises(ValueError): v.agreement({'publicnode':{'out':'1'}})
        got,readers=v.agreement({'arbitrum-official':{'out':'1'},'alchemy-public':{'out':'1'},'publicnode':{'out':'2'}})
        self.assertEqual(got,{'out':'1'}); self.assertEqual(len(readers),2)

if __name__=='__main__': unittest.main()
