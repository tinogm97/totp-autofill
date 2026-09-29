import tempfile
import unittest
from pathlib import Path

from totp_autofill import chrome_setup
from totp_autofill.chrome_setup import FLAG

SYSTEM_DESKTOP = """[Desktop Entry]
Name=Google Chrome
Exec=/usr/bin/google-chrome-stable %U

[Desktop Action new-window]
Exec=/usr/bin/google-chrome-stable
"""


class ChromeSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.system = root / "system"
        self.user = root / "user"
        self.backups = root / "backups"
        self.system.mkdir()
        (self.system / "google-chrome.desktop").write_text(SYSTEM_DESKTOP)

    def tearDown(self):
        self.tmp.cleanup()

    def test_enable_creates_user_copy_and_undo_removes_it(self):
        changed = chrome_setup.enable(self.user, [self.system], self.backups)
        text = (self.user / "google-chrome.desktop").read_text()
        self.assertEqual(changed, [self.user / "google-chrome.desktop"])
        self.assertIn(f"Exec=env QT_ACCESSIBILITY=1 /usr/bin/google-chrome-stable {FLAG} %U", text)
        self.assertIn(f"Exec=env QT_ACCESSIBILITY=1 /usr/bin/google-chrome-stable {FLAG}\n", text)
        self.assertTrue(chrome_setup.is_enabled(self.user))
        self.assertEqual(chrome_setup.enable(self.user, [self.system], self.backups), [])  # idempotente
        chrome_setup.disable(self.user, self.backups)
        self.assertFalse((self.user / "google-chrome.desktop").exists())
        self.assertEqual((self.system / "google-chrome.desktop").read_text(), SYSTEM_DESKTOP)

    def test_existing_user_file_is_modified_and_restored(self):
        self.user.mkdir()
        own = SYSTEM_DESKTOP.replace("%U", "--profile-directory=Work %U")
        (self.user / "google-chrome.desktop").write_text(own)
        chrome_setup.enable(self.user, [self.system], self.backups)
        self.assertIn(f"stable {FLAG} --profile-directory=Work %U",
                      (self.user / "google-chrome.desktop").read_text())
        chrome_setup.disable(self.user, self.backups)
        self.assertEqual((self.user / "google-chrome.desktop").read_text(), own)

    def test_firefox_snap_and_deb(self):
        snap = ("[Desktop Entry]\nName=Firefox\nExec=env BAMF_DESKTOP_FILE_HINT=/var/lib/snapd/"
                "desktop/applications/firefox_firefox.desktop /snap/bin/firefox %u\n")
        (self.system / "firefox_firefox.desktop").write_text(snap)
        (self.system / "firefox.desktop").write_text("[Desktop Entry]\nExec=firefox %u\n")
        chrome_setup.enable(self.user, [self.system], self.backups)
        self.assertIn("Exec=env GNOME_ACCESSIBILITY=1 BAMF_DESKTOP_FILE_HINT=",
                      (self.user / "firefox_firefox.desktop").read_text())
        deb = (self.user / "firefox.desktop").read_text()
        self.assertIn("Exec=env GNOME_ACCESSIBILITY=1 firefox %u", deb)
        self.assertNotIn(FLAG, deb)  # el flag de Chrome no aplica a Firefox
        self.assertTrue(chrome_setup.is_enabled(self.user))
        chrome_setup.disable(self.user, self.backups)
        self.assertFalse((self.user / "firefox_firefox.desktop").exists())

    def test_add_flag_respects_env_and_quotes(self):
        cases = {
            "Exec=env FOO=1 /usr/bin/google-chrome %U":
                f"Exec=env QT_ACCESSIBILITY=1 FOO=1 /usr/bin/google-chrome {FLAG} %U",
            'Exec="/opt/My Browser/chrome" --x %U':
                f'Exec=env QT_ACCESSIBILITY=1 "/opt/My Browser/chrome" {FLAG} --x %U',
            "Exec=env QT_ACCESSIBILITY=1 chrome":
                f"Exec=env QT_ACCESSIBILITY=1 chrome {FLAG}",
            f"Exec=chrome {FLAG}": f"Exec=chrome {FLAG}",  # ya lo tenía: no se toca
        }
        for before, after in cases.items():
            with self.subTest(before=before):
                self.assertEqual(chrome_setup._add_flag(before), after)

    def test_user_flag_survives_undo(self):
        self.user.mkdir()
        own = SYSTEM_DESKTOP.replace("%U", f"{FLAG} %U").replace(
            "Exec=/usr/bin/google-chrome-stable\n", "Exec=/usr/bin/google-chrome-stable --new\n")
        (self.user / "google-chrome.desktop").write_text(own)
        chrome_setup.enable(self.user, [self.system], self.backups)
        chrome_setup.disable(self.user, self.backups)
        self.assertEqual((self.user / "google-chrome.desktop").read_text(), own)

    def test_running_browsers(self):
        proc = Path(self.tmp.name) / "proc"
        for pid, args in {
            "10": ["/opt/google/chrome/chrome"],
            "11": ["/opt/google/chrome/chrome", "--type=renderer"],
            "12": ["/opt/google/chrome/chrome", "--user-data-dir=/home/t/.config/vpn", FLAG],
            "13": ["/usr/bin/python3"],
            "20": ["/snap/firefox/6000/usr/lib/firefox/firefox"],
            "21": ["/snap/firefox/6000/usr/lib/firefox/firefox", "-contentproc", "tab"],
        }.items():
            (proc / pid).mkdir(parents=True)
            (proc / pid / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
            (proc / pid / "environ").write_bytes(b"HOME=/h\0GNOME_ACCESSIBILITY=1\0")
        (proc / "self").mkdir()
        found = sorted(chrome_setup.running_browsers(proc), key=lambda p: p.pid)
        self.assertEqual([(p.pid, p.accessible, p.user_data_dir) for p in found],
                         [(10, False, ""), (12, True, "/home/t/.config/vpn"), (20, True, "")])


if __name__ == "__main__":
    unittest.main()
