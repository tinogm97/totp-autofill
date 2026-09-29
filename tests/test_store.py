import json
import tempfile
import unittest
from pathlib import Path

from totp_autofill.store import (
    Account, AccountStore, MemoryBackend, Settings, clean_title, host_of,
    normalize_site, site_matches,
)

SECRET = "JBSWY3DPEHPK3PXP"


class SitesTest(unittest.TestCase):
    def test_normalize_site(self):
        self.assertEqual(normalize_site("https://SSO.empresa.com/mfa*"), "sso.empresa.com")
        self.assertEqual(normalize_site("localhost:4200"), "localhost:4200")
        self.assertEqual(normalize_site("http://localhost:4200/#/otp"), "localhost:4200")
        self.assertEqual(normalize_site("*.empresa.com"), "*.empresa.com")
        self.assertEqual(normalize_site("  "), "")

    def test_host_of(self):
        self.assertEqual(host_of("http://localhost:4200/login?x=1"), "localhost:4200")
        self.assertEqual(host_of("https://GitHub.com/sessions/two-factor"), "github.com")
        self.assertEqual(host_of("file:///tmp/x.html"), "")
        self.assertEqual(host_of("about:blank"), "")

    def test_site_matches(self):
        self.assertTrue(site_matches("localhost:4200", "localhost:4200"))
        self.assertFalse(site_matches("localhost:4200", "localhost:4201"))
        self.assertTrue(site_matches("*.empresa.com", "sso.empresa.com"))
        self.assertFalse(site_matches("*.empresa.com", "empresa.com.malo.com"))
        self.assertFalse(site_matches("empresa.com", "sso.empresa.com"))
        self.assertFalse(site_matches("a.b", "aXb"))  # el punto es literal
        self.assertFalse(site_matches("", "x.com"))

    def test_clean_title(self):
        self.assertEqual(clean_title("Verificación - MiApp - Google Chrome"), "Verificación - MiApp")
        self.assertEqual(clean_title("Login — Mozilla Firefox"), "Login")
        self.assertEqual(clean_title("Terminal"), "Terminal")


class AccountStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"
        self.secrets = MemoryBackend()
        self.store = AccountStore(self.path, self.secrets)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load_code(self):
        acc = self.store.save(Account("ACME", sites=["https://acme.com/2fa"]), SECRET)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(SECRET, self.path.read_text())  # secreto fuera del JSON
        self.assertEqual(self.store.get(acc.id).sites, ["acme.com"])
        code, remaining = self.store.code(acc)
        self.assertRegex(code, r"^\d{6}$")
        self.assertTrue(1 <= remaining <= 30)

    def test_sites_are_optional(self):
        acc = self.store.save(Account("Sin sitio"), SECRET)
        self.assertEqual(self.store.get(acc.id).sites, [])

    def test_new_account_requires_secret(self):
        with self.assertRaises(ValueError):
            self.store.save(Account("ACME"))

    def test_update_keeps_secret(self):
        acc = self.store.save(Account("ACME"), SECRET)
        acc.name = "ACME 2"
        self.store.save(acc)
        self.assertEqual(self.store.get(acc.id).name, "ACME 2")
        self.assertEqual(self.secrets.get(acc.id), SECRET)

    def test_delete_removes_secret(self):
        acc = self.store.save(Account("ACME"), SECRET)
        self.store.delete(acc.id)
        self.assertEqual(self.store.load(), [])
        self.assertIsNone(self.secrets.get(acc.id))

    def test_same_name_needs_different_user(self):
        self.store.save(Account("Dev", username="ana@x.com"), SECRET)
        self.store.save(Account("Dev", username="luis@x.com"), SECRET)
        with self.assertRaises(ValueError):
            self.store.save(Account("dev", username="ANA@x.com"), SECRET)

    def test_learn(self):
        acc = self.store.save(Account("Dev"), SECRET)
        self.store.learn(acc.id, host="LOCALHOST:4200")
        self.store.learn(acc.id, host="localhost:4200")  # sin duplicar
        self.store.learn(acc.id, title="Verificación - MiApp - Google Chrome")
        self.store.learn(acc.id, title="Verificación - MiApp")
        saved = self.store.get(acc.id)
        self.assertEqual(saved.sites, ["localhost:4200"])
        self.assertEqual(saved.window_titles, ["Verificación - MiApp"])

    def test_learn_host_covered_by_wildcard(self):
        acc = self.store.save(Account("Emp", sites=["*.empresa.com"]), SECRET)
        self.store.learn(acc.id, host="sso.empresa.com")
        self.assertEqual(self.store.get(acc.id).sites, ["*.empresa.com"])

    def test_migrates_v1_file(self):
        self.path.write_text(json.dumps({"version": 1, "accounts": [
            {"name": "Old", "url_pattern": "https://sso.acme.com/mfa*", "id": "a",
             "selector": "#otp", "auto_submit": True},
            {"name": "Todo", "url_pattern": "*", "id": "b"},
        ]}))
        old, everything = self.store.load()
        self.assertEqual(old.sites, ["sso.acme.com"])
        self.assertTrue(old.auto_submit)
        self.assertEqual(everything.sites, [])

    def test_validation(self):
        for bad in (Account(""), Account("x", digits=5), Account("x", algorithm="MD5")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.save(bad, SECRET)


class FileBackendTest(unittest.TestCase):
    def test_env_var_selects_file_backend(self):
        import os
        from unittest import mock

        from totp_autofill.store import FileBackend, default_secret_backend

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            with mock.patch.dict(os.environ, {"TOTP_AUTOFILL_TEST_SECRETS": str(path)}), \
                    mock.patch("totp_autofill.store.LibsecretBackend", object):
                # Solo la ruta no basta: hace falta también TOTP_AUTOFILL_TESTING=1.
                self.assertNotIsInstance(default_secret_backend(), FileBackend)
            with mock.patch.dict(os.environ, {"TOTP_AUTOFILL_TEST_SECRETS": str(path),
                                              "TOTP_AUTOFILL_TESTING": "1"}):
                backend = default_secret_backend()
            self.assertIsInstance(backend, FileBackend)
            backend.set("a", "A", SECRET)
            self.assertEqual(FileBackend(path).get("a"), SECRET)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class SettingsTest(unittest.TestCase):
    def test_roundtrip_and_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            self.assertTrue(Settings.load(path).auto_fill)
            Settings(auto_fill=False, shortcut="<Super>o").save(path)
            loaded = Settings.load(path)
            self.assertEqual((loaded.auto_fill, loaded.shortcut), (False, "<Super>o"))
            path.write_text("no es json")
            self.assertTrue(Settings.load(path).auto_fill)


if __name__ == "__main__":
    unittest.main()
