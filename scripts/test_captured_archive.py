import json
import unittest
import captured_archive as c
import real_quorum as q

class CapturedArchiveTest(unittest.TestCase):
    def fixture(self):
        # Deliberately synthetic unit data. NEVER a network capture or earned PnL.
        h = {'number': hex(q.PRE_BLOCK), 'hash': q.PRE_HASH,
             'parentHash': '0x'+'11'*32, 'stateRoot': '0x'+'22'*32, 'timestamp': '0x1000'}
        after = dict(h, number=hex(q.PRE_BLOCK+1), hash='0x'+'33'*32,
                     parentHash=q.PRE_HASH, timestamp='0x1001')
        receipt = dict(status='0x1', blockHash=after['hash'], blockNumber=after['number'],
                       transactionHash=q.HISTORICAL_TX,
                       logs=[dict(address=q.POOL, topics=['0x'+'44'*32], data='0x')])
        values = ['0xa4b1',h,'0x'+format(5,'064x'),
                  '0x'+'0'*320+format(1000000000174597223,'064x'),'0x6000','0x6001',after,receipt]
        body = [{'jsonrpc':'2.0','id':i,'result':v} for i,v in enumerate(values,1)]
        return dict(schema='flash.make_archive_capture.v1', responses={label:json.dumps(body) for label in c.LABELS})
    def change(self, capture, index, value):
        key='nodeflare-public'; rows=json.loads(capture['responses'][key]); rows[index]['result']=value
        capture['responses'][key]=json.dumps(rows)
    def test_agreed_synthetic_fixture(self):
        r=c.validate(self.fixture()); self.assertEqual(r['status'],'PASS')
        self.assertFalse(r['current_trade_signal']); self.assertEqual(r['actual_earnings'],'0')
        self.assertEqual(len(r['state_voters']),2)
    def test_one_capture_rejected(self):
        x=self.fixture(); del x['responses']['nodeflare-public']
        with self.assertRaises(ValueError): c.validate(x)
    def test_wrong_chain_rejected(self):
        x=self.fixture(); self.change(x,0,'0x1')
        with self.assertRaises(ValueError): c.validate(x)
    def test_runtime_change_rejected(self):
        x=self.fixture(); self.change(x,4,'0x6002')
        with self.assertRaises(ValueError): c.validate(x)
    def test_wrong_health_rejected(self):
        x=self.fixture(); self.change(x,3,'0x'+'0'*384)
        with self.assertRaises(ValueError): c.validate(x)
    def test_duplicate_id_rejected(self):
        x=self.fixture(); key='nodeflare-public'; rows=json.loads(x['responses'][key]); rows[1]['id']=1
        x['responses'][key]=json.dumps(rows)
        with self.assertRaises(ValueError): c.validate(x)
    def test_response_error_rejected(self):
        x=self.fixture(); key='nodeflare-public'; rows=json.loads(x['responses'][key]); rows[3]['error']={'code':-32000}
        x['responses'][key]=json.dumps(rows)
        with self.assertRaises(ValueError): c.validate(x)
    def test_duplicate_json_field_rejected(self):
        with self.assertRaises(ValueError): c.parse_batch('[{"id":1,"id":2}]')
    def test_wrong_transaction_rejected(self):
        x=self.fixture(); key='nodeflare-public'; rows=json.loads(x['responses'][key]); rows[7]['result']['transactionHash']='0x'+'55'*32
        x['responses'][key]=json.dumps(rows)
        with self.assertRaises(ValueError): c.validate(x)
    def test_future_gap_rejected(self):
        x=self.fixture(); key='nodeflare-public'; rows=json.loads(x['responses'][key]); rows[6]['result']['timestamp']='0x2000'
        x['responses'][key]=json.dumps(rows)
        with self.assertRaises(ValueError): c.validate(x)
    def test_live_request_function_restored_after_failure(self):
        old=q.request; x=self.fixture(); self.change(x,0,'0x1')
        with self.assertRaises(ValueError): c.validate(x)
        self.assertIs(q.request,old)
if __name__=='__main__': unittest.main()
