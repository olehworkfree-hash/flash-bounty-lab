import unittest
from head_policy import select_heads

class HeadPolicyTest(unittest.TestCase):
    def test_actual_stale_provider_observation(self):
        heads = {'alchemy': 502716119, 'official': 502716117, 'nodeflare': 502646576}
        self.assertEqual(select_heads(heads), {'alchemy': 502716119, 'official': 502716117})
    def test_lone_fake_high_head_does_not_win(self):
        self.assertEqual(select_heads({'bad': 999999, 'a': 500001, 'b': 500000}), {'a': 500001, 'b': 500000})
    def test_no_cluster_rejected(self):
        with self.assertRaises(ValueError): select_heads({'a': 1000, 'b': 2000, 'c': 3000})
    def test_single_provider_rejected(self):
        with self.assertRaises(ValueError): select_heads({'a': 1000})
    def test_invalid_head_rejected(self):
        with self.assertRaises(ValueError): select_heads({'a': True, 'b': 1000})

if __name__ == '__main__': unittest.main()
