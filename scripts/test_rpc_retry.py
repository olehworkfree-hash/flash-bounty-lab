import unittest
import urllib.error
from rpc_retry import bounded_urlopen

class RpcRetryTest(unittest.TestCase):
    def test_retry_after_is_honored(self):
        calls, waits = [], []
        def opener(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError("https://example.test",429,"limited",{"Retry-After":"5"},None)
            return "ok"
        self.assertEqual(bounded_urlopen(None, opener=opener, sleeper=waits.append), "ok")
        self.assertEqual(waits, [5])
    def test_long_retry_after_fails(self):
        def opener(req,timeout):
            raise urllib.error.HTTPError("https://example.test",429,"limited",{"Retry-After":"60"},None)
        with self.assertRaises(ValueError): bounded_urlopen(None, opener=opener, sleeper=lambda _: self.fail())
    def test_only_three_attempts(self):
        calls, waits = [], []
        def opener(req, timeout):
            calls.append(1)
            raise TimeoutError()
        with self.assertRaises(TimeoutError): bounded_urlopen(None,opener=opener,sleeper=waits.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(waits,[2,4])
    def test_no_retry_on_forbidden(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError("https://example.test",403,"forbidden",{},None)
        with self.assertRaises(urllib.error.HTTPError): bounded_urlopen(None,opener=opener,sleeper=lambda _: self.fail())

if __name__ == "__main__": unittest.main()
