import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from totp_autofill import qr
from totp_autofill.migration import (
    ImportedAccount, accounts_from_uris, find_uris, import_accounts, missing_batches,
    parse_migration_uri,
)
from totp_autofill.store import Account, AccountStore, MemoryBackend
from totp_autofill.totp import totp

from migration_fixtures import BATCH_1, BATCH_2, migration_uri, otp  # noqa: E402

DATA = Path(__file__).parent / "data"
b32 = lambda raw: base64.b32encode(raw).decode().rstrip("=")  # noqa: E731


class MigrationParseTest(unittest.TestCase):
    def test_batch_1(self):
        batch = parse_migration_uri(BATCH_1)
        self.assertEqual((batch.index, batch.size, batch.batch_id), (0, 2, 42))
        github, dropbox = batch.accounts
        self.assertEqual((github.name, github.username), ("GitHub", "ana@empresa.com"))
        self.assertEqual(github.secret, b32(b"Hello!\xde\xad\xbe\xef"))
        # "Emisor:cuenta" en el nombre, sin issuer aparte
        self.assertEqual((dropbox.name, dropbox.username), ("Dropbox", "ana@empresa.com"))
        self.assertEqual(len(batch.skipped), 1)
        self.assertIn("HOTP", batch.skipped[0])

    def test_algorithm_and_digits(self):
        (vpn,) = parse_migration_uri(BATCH_2).accounts
        self.assertEqual((vpn.name, vpn.algorithm, vpn.digits), ("VPN Empresa", "SHA256", 8))
        self.assertRegex(totp(vpn.secret, digits=8, algorithm="SHA256"), r"^\d{8}$")

    def test_name_without_issuer(self):
        (acc,) = parse_migration_uri(migration_uri([otp(b"1234567890", "Mi banco")])).accounts
        self.assertEqual((acc.name, acc.username), ("Mi banco", ""))

    def test_md5_is_skipped(self):
        batch = parse_migration_uri(migration_uri([otp(b"1234567890", "X", algorithm=4)]))
        self.assertEqual(batch.accounts, [])
        self.assertIn("MD5", batch.skipped[0])

    def test_invalid(self):
        for uri in ("https://x", "otpauth-migration://offline?foo=1",
                    "otpauth-migration://offline?data=CgQK"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                parse_migration_uri(uri)

    def test_find_and_merge_uris(self):
        text = f"basura {BATCH_1}\n{BATCH_2} y otpauth://totp/Acme:yo@x.com?secret=GEZDGNBVGY3TQOJQ&issuer=Acme\n{BATCH_1}"
        uris = find_uris(text)
        self.assertEqual(len(uris), 4)
        accounts, skipped, batches = accounts_from_uris(uris)
        self.assertEqual([a.label for a in accounts], [
            "GitHub <ana@empresa.com>", "Dropbox <ana@empresa.com>",
            "VPN Empresa <tino@empresa.com>", "Acme <yo@x.com>"])  # sin duplicar el lote 1
        self.assertEqual(missing_batches(batches), [])
        self.assertEqual(missing_batches(batches[:1]), [2])


class ImportTest(unittest.TestCase):
    def test_import_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccountStore(Path(tmp) / "a.json", MemoryBackend())
            store.save(Account("GitHub (ya estaba)"), b32(b"Hello!\xde\xad\xbe\xef"))
            accounts, _, _ = accounts_from_uris([BATCH_1, BATCH_2])
            result = import_accounts(store, accounts)
            self.assertEqual(result.existing, ["GitHub <ana@empresa.com>"])
            self.assertEqual(len(result.imported), 2)
            again = import_accounts(store, accounts)  # idempotente
            self.assertEqual((again.imported, len(again.existing)), ([], 3))
            self.assertEqual(len(store.load()), 3)


@unittest.skipUnless(qr.available(), "falta libzbar")
class QrTest(unittest.TestCase):
    def test_decode_png(self):
        self.assertEqual(qr.decode_file(str(DATA / "google-export-1.png")), [BATCH_1])

    def test_decode_photo(self):
        self.assertEqual(qr.decode_file(str(DATA / "google-export-2-photo.jpg")), [BATCH_2])

    def test_no_qr(self):
        self.assertEqual(qr.decode_gray(4, 4, bytes(16)), [])


if __name__ == "__main__":
    unittest.main()
