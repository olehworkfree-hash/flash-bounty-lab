import io
import unittest
import urllib.error
from unittest.mock import Mock
from rpc_transport import fetch_body, NoRedirect, SafeTransportError

class TransportTests(unittest.TestCase):
    def response(self, data=b'[]'):
        return io.BytesIO(data)
    def error(self, code, headers=None):
        return urllib.error.HTTPError('https://never-log.invalid/secret', code, 'remote message', headers or {}, io.BytesIO())
    def test_success_without_retry(self):
        opener=Mock(return_value=self.response()); sleep=Mock()
        self.assertEqual(fetch_body(object(),20,opener=opener,sleep=sleep),b'[]')
        sleep.assert_not_called(); self.assertEqual(opener.call_count,1)
    def test_429_retry_after_honored(self):
        opener=Mock(side_effect=[self.error(429,{'Retry-After':'3'}), self.response()]); sleep=Mock()
        self.assertEqual(fetch_body(object(),20,opener=opener,sleep=sleep),b'[]')
        sleep.assert_called_once_with(3.0)
    def test_503_stops_after_three_attempts(self):
        opener=Mock(side_effect=[self.error(503) for _ in range(3)]); sleep=Mock()
        with self.assertRaisesRegex(SafeTransportError,'^RPC_TRANSPORT_EXHAUSTED$'):
            fetch_body(object(),20,opener=opener,sleep=sleep)
        self.assertEqual(opener.call_count,3); self.assertEqual(sleep.call_count,2)
    def test_auth_error_is_not_retried_or_leaked(self):
        opener=Mock(side_effect=self.error(401)); sleep=Mock()
        with self.assertRaisesRegex(SafeTransportError,'^RPC_HTTP_401$'):
            fetch_body(object(),20,opener=opener,sleep=sleep)
        self.assertEqual(opener.call_count,1); sleep.assert_not_called()
    def test_timeout_recovers(self):
        opener=Mock(side_effect=[TimeoutError('endpoint secret'),self.response()])
        self.assertEqual(fetch_body(object(),20,opener=opener,sleep=Mock()),b'[]')
    def test_oversize_is_not_retried(self):
        opener=Mock(return_value=self.response(b'12345'))
        with self.assertRaisesRegex(SafeTransportError,'^RPC_RESPONSE_TOO_LARGE$'):
            fetch_body(object(),4,opener=opener,sleep=Mock())
        self.assertEqual(opener.call_count,1)
    def test_long_server_cooldown_not_ignored(self):
        opener=Mock(side_effect=self.error(429,{'Retry-After':'3600'})); sleep=Mock()
        with self.assertRaisesRegex(SafeTransportError,'RPC_SERVER_COOLDOWN_EXCEEDS_BUDGET'):
            fetch_body(object(),20,opener=opener,sleep=sleep)
        sleep.assert_not_called()
    def test_invalid_retry_after_stops(self):
        opener=Mock(side_effect=self.error(429,{'Retry-After':'bad'}))
        with self.assertRaisesRegex(SafeTransportError,'RPC_RETRY_AFTER_UNSUPPORTED'):
            fetch_body(object(),20,opener=opener,sleep=Mock())
    def test_no_redirects(self):
        with self.assertRaisesRegex(SafeTransportError,'RPC_REDIRECT_REJECTED'):
            NoRedirect().redirect_request(None,None,302,'found',{},'https://evil.invalid')
if __name__=='__main__': unittest.main()
