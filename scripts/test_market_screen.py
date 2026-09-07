import unittest
from market_screen import amount_out, premium, evaluate, words, address
class MarketScreenTest(unittest.TestCase):
 def test_integer_rounding(self): self.assertEqual(amount_out(1000,100000,100000),987)
 def test_invalid(self):
  for v in [0,-1,1.5,True]:
   with self.subTest(v=v),self.assertRaises(ValueError): amount_out(v,100,100)
 def test_equal_pools_lose_before_gas(self):
  p={n:dict(weth=10**22,usdc=25*10**12) for n in ['uniswap-v2','sushiswap-v2']}; rows=evaluate(p,5); self.assertEqual(len(rows),12); self.assertTrue(all(int(r['gross_before_gas_weth_wei'])<0 for r in rows))
 def test_artificial_edge_is_only_quote_not_income(self):
  p={'uniswap-v2':dict(weth=10**22,usdc=25*10**12),'sushiswap-v2':dict(weth=10**22,usdc=20*10**12)}; rows=evaluate(p,5); self.assertTrue(any(r['status']=='QUOTE_ONLY_NEEDS_FORK_AND_FEE' for r in rows))
 def test_half_up_premium(self): self.assertEqual(premium(1000,5),1); self.assertEqual(premium(999,5),0)
 def test_invalid_fee(self):
  for b in [-1,10001,True]:
   with self.assertRaises(ValueError): premium(100,b)
 def test_bad_abi(self):
  with self.assertRaises(ValueError): words('0x00',1)
 def test_address_range(self):
  with self.assertRaises(ValueError): address('0x'+'f'*64)
 def test_address_decode(self): self.assertEqual(address('0x'+'0'*24+'1'*40),'0x'+'1'*40)
if __name__=='__main__': unittest.main()
