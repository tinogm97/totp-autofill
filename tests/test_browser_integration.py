import json
import tempfile
import unittest
from pathlib import Path

from totp_autofill.browser_integration import HOST_NAME, install, uninstall


class BrowserIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        # Chrome estándar, un Chrome con --user-data-dir propio y Firefox.
        (self.home / ".config/google-chrome").mkdir(parents=True)
        vpn = self.home / ".config/google-chrome-vpn"
        (vpn / "Default").mkdir(parents=True)
        (vpn / "Local State").write_text("{}")
        (vpn / "Default/Preferences").write_text("{}")
        # App Electron: tiene Local State pero no es un navegador.
        (self.home / ".config/Code").mkdir(parents=True)
        (self.home / ".config/Code/Local State").write_text("{}")
        (self.home / ".mozilla").mkdir()
        self.outside = self.home / "perfiles/chrome-pruebas"
        self.outside.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_detects_custom_user_data_dirs(self):
        written = install(self.home / "host", extra_data_dirs=[self.outside], home=self.home)
        rel = {str(p.relative_to(self.home)) for p in written}
        self.assertEqual(rel, {
            f".config/google-chrome/NativeMessagingHosts/{HOST_NAME}.json",
            f".config/google-chrome-vpn/NativeMessagingHosts/{HOST_NAME}.json",
            f"perfiles/chrome-pruebas/NativeMessagingHosts/{HOST_NAME}.json",
            f".mozilla/native-messaging-hosts/{HOST_NAME}.json",
        })
        chrome = json.loads(written[0].read_text())
        self.assertEqual(chrome["allowed_origins"],
                         ["chrome-extension://blnffoflcmdajflilndalbfcgeddaakd/"])

    def test_uninstall_removes_all(self):
        install(self.home / "host", extra_data_dirs=[self.outside], home=self.home)
        removed = uninstall(extra_data_dirs=[self.outside], home=self.home)
        self.assertEqual(len(removed), 4)
        self.assertFalse(list(self.home.rglob(f"{HOST_NAME}.json")))


if __name__ == "__main__":
    unittest.main()
