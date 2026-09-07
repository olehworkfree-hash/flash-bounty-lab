import unittest
from test_pinned_header import PinnedHeaderTest
from test_rpc_retry import RpcRetryTest
from test_head_policy import HeadPolicyTest
from real_quorum import agreement, request, digest

class QuorumPolicyTest(unittest.TestCase):
    def test_two_equal_values_pass(self):
        state, voters = agreement({'one': {'x': 1}, 'two': {'x': 1}, 'three': {'x': 2}})
        self.assertEqual(state, {'x': 1})
        self.assertEqual(voters, ['one', 'two'])
    def test_one_provider_is_not_quorum(self):
        with self.assertRaises(ValueError): agreement({'one': {'x': 1}})
    def test_all_disagree_fail(self):
        with self.assertRaises(ValueError): agreement({'one': {'x': 1}, 'two': {'x': 2}, 'three': {'x': 3}})
    def test_broadcast_method_is_rejected_before_network(self):
        with self.assertRaises(ValueError): request('arbitrum-official', [('eth_sendRawTransaction', [])])
    def test_unknown_endpoint_label_rejected(self):
        with self.assertRaises(ValueError): request('untrusted', [('eth_chainId', [])])
    def test_digest_is_order_independent(self):
        self.assertEqual(digest({'a': 1, 'b': 2}), digest({'b': 2, 'a': 1}))

if __name__ == '__main__': unittest.main()
