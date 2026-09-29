import tempfile
import unittest
from pathlib import Path

from totp_autofill.store import Account, AccountStore, MemoryBackend, url_matches

SECRET = "JBSWY3DPEHPK3PXP"


class UrlMatchesTest(unittest.TestCase):
    def test_wildcards(self):
        self.assertTrue(url_matches("https://login.acme.com/mfa*",
                                    "https://login.acme.com/mfa/verify"))
        self.assertTrue(url_matches("https://*.acme.com/2fa", "https://sso.acme.com/2fa"))
        self.assertFalse(url_matches("https://login.acme.com/mfa*",
                                     "https://evil.com/login.acme.com/mfa"))

    def test_query_and_fragment_ignored_unless_in_pattern(self):
        self.assertTrue(url_matches("https://acme.com/2fa", "https://acme.com/2fa?next=/#x"))
        self.assertFalse(url_matches("https://acme.com/2fa?step=otp",
                                     "https://acme.com/2fa?step=login"))
        self.assertTrue(url_matches("https://acme.com/2fa?step=otp*",
                                    "https://acme.com/2fa?step=otp&x=1"))

    def test_scheme_optional_and_case_insensitive(self):
        self.assertTrue(url_matches("acme.com/2fa", "https://ACME.com/2fa"))
        self.assertTrue(url_matches("acme.com/2fa", "http://acme.com/2fa"))

    def test_dots_are_literal(self):
        self.assertFalse(url_matches("https://acme.com/*", "https://acmeXcom/2fa"))

    def test_empty(self):
        self.assertFalse(url_matches("", "https://acme.com"))
        self.assertFalse(url_matches("*", ""))


class AccountStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"
        self.secrets = MemoryBackend()
        self.store = AccountStore(self.path, self.secrets)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load_and_match(self):
        acc = self.store.save(Account("ACME", "https://acme.com/2fa*"), SECRET)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(SECRET, self.path.read_text())  # secreto fuera del JSON
        self.assertEqual([a.id for a in self.store.match("https://acme.com/2fa/x")], [acc.id])
        self.assertEqual(self.store.match("https://other.com/2fa"), [])
        code, remaining = self.store.code(acc)
        self.assertRegex(code, r"^\d{6}$")
        self.assertTrue(1 <= remaining <= 30)

    def test_new_account_requires_secret(self):
        with self.assertRaises(ValueError):
            self.store.save(Account("ACME", "acme.com"))

    def test_update_keeps_secret(self):
        acc = self.store.save(Account("ACME", "acme.com"), SECRET)
        acc.name = "ACME 2"
        self.store.save(acc)
        self.assertEqual(self.store.get(acc.id).name, "ACME 2")
        self.assertEqual(self.secrets.get(acc.id), SECRET)

    def test_delete_removes_secret(self):
        acc = self.store.save(Account("ACME", "acme.com"), SECRET)
        self.store.delete(acc.id)
        self.assertEqual(self.store.load(), [])
        self.assertIsNone(self.secrets.get(acc.id))

    def test_validation(self):
        for bad in (Account("", "acme.com"), Account("x", ""),
                    Account("x", "acme.com", digits=5)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.save(bad, SECRET)


if __name__ == "__main__":
    unittest.main()
