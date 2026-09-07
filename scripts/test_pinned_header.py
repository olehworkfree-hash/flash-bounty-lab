import unittest
from pinned_header import checked_header

class PinnedHeaderTest(unittest.TestCase):
    def setUp(self):
        self.h = dict(hash='0x11', parentHash='0x22', stateRoot='0x33', number='0x64', timestamp='0x99', l1BlockNumber='0x44')
        self.e = dict(status='PASS', header=self.h)
    def test_plain_header(self):
        self.assertEqual(checked_header(self.h, self.e), self.h)
    def test_successful_envelope(self):
        self.assertEqual(checked_header(dict(schema_version=1, success=True, errors=[], data=self.h), self.e), self.h)
    def test_failed_envelope(self):
        with self.assertRaises(ValueError): checked_header(dict(schema_version=1, success=False, data=self.h), self.e)
    def test_every_identity_field_is_checked(self):
        for key in self.h:
            with self.subTest(key=key), self.assertRaises(ValueError): checked_header({**self.h, key:'0x00'}, self.e)
    def test_failed_quorum_rejected(self):
        with self.assertRaises(ValueError): checked_header(self.h, dict(status='FAILED', header=self.h))
    def test_missing_field_rejected(self):
        with self.assertRaises(ValueError): checked_header({}, self.e)

if __name__ == '__main__': unittest.main()
