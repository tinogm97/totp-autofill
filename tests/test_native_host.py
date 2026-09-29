import io
import struct
import tempfile
import unittest
from pathlib import Path

from totp_autofill.native_host import handle, read_message, write_message
from totp_autofill.store import Account, AccountStore, MemoryBackend


class FramingTest(unittest.TestCase):
    def test_roundtrip(self):
        buf = io.BytesIO()
        write_message(buf, {"type": "ping", "ñ": "ü"})
        buf.seek(0)
        self.assertEqual(read_message(buf), {"type": "ping", "ñ": "ü"})
        self.assertIsNone(read_message(buf))  # EOF

    def test_rejects_huge_message(self):
        buf = io.BytesIO(struct.pack("=I", 10 * 1024 * 1024))
        with self.assertRaises(ValueError):
            read_message(buf)


class HandleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AccountStore(Path(self.tmp.name) / "a.json", MemoryBackend())
        self.acc = self.store.save(
            Account("ACME", "https://acme.com/2fa*", username="ana@acme.com",
                    selector="#otp"), "JBSWY3DPEHPK3PXP")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ping(self):
        self.assertTrue(handle({"type": "ping"}, self.store)["ok"])

    def test_patterns(self):
        res = handle({"type": "patterns"}, self.store)
        self.assertEqual(res["patterns"], ["https://acme.com/2fa*"])
        self.assertEqual(res["users"], ["ana@acme.com"])

    def test_match_returns_no_secret(self):
        res = handle({"type": "match", "url": "https://acme.com/2fa"}, self.store)
        self.assertEqual(len(res["accounts"]), 1)
        self.assertEqual(res["accounts"][0]["selector"], "#otp")
        self.assertEqual(res["accounts"][0]["username"], "ana@acme.com")
        self.assertNotIn("JBSWY3DPEHPK3PXP", str(res))

    def test_code_requires_matching_url(self):
        ok = handle({"type": "code", "id": self.acc.id, "url": "https://acme.com/2fa"},
                    self.store)
        self.assertTrue(ok["ok"])
        self.assertRegex(ok["code"], r"^\d{6}$")

        denied = handle({"type": "code", "id": self.acc.id, "url": "https://evil.com/"},
                        self.store)
        self.assertFalse(denied["ok"])
        self.assertNotIn("code", denied)

    def test_unknown(self):
        self.assertFalse(handle({"type": "nope"}, self.store)["ok"])
        self.assertFalse(handle({"type": "code", "id": "x", "url": ""}, self.store)["ok"])


if __name__ == "__main__":
    unittest.main()
