import unittest

from totp_autofill.totp import (
    InvalidSecretError,
    normalize_secret,
    parse_otpauth_uri,
    seconds_remaining,
    totp,
)

# Vectores de prueba del Apéndice B de la RFC 6238. Los secretos son el
# texto ASCII "12345678901234567890..." codificado en Base32.
SHA1_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
SHA256_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQGEZA"
SHA512_SECRET = (
    "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQGEZDGNA"
)
RFC_VECTORS = [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]


class TotpTest(unittest.TestCase):
    def test_rfc6238_vectors(self):
        for at, sha1, sha256, sha512 in RFC_VECTORS:
            with self.subTest(at=at):
                self.assertEqual(totp(SHA1_SECRET, digits=8, at=at), sha1)
                self.assertEqual(
                    totp(SHA256_SECRET, digits=8, algorithm="SHA256", at=at), sha256)
                self.assertEqual(
                    totp(SHA512_SECRET, digits=8, algorithm="SHA512", at=at), sha512)

    def test_six_digits_is_suffix(self):
        self.assertEqual(totp(SHA1_SECRET, at=59), "287082")

    def test_seconds_remaining(self):
        self.assertEqual(seconds_remaining(30, at=60), 30)
        self.assertEqual(seconds_remaining(30, at=89), 1)

    def test_normalize_secret(self):
        self.assertEqual(normalize_secret("gezd gnbv-gy3t qojq"), "GEZDGNBVGY3TQOJQ")
        with self.assertRaises(InvalidSecretError):
            normalize_secret("no es base32!")
        with self.assertRaises(InvalidSecretError):
            normalize_secret("   ")


class OtpAuthUriTest(unittest.TestCase):
    def test_full_uri(self):
        info = parse_otpauth_uri(
            "otpauth://totp/ACME%20Co:john@example.com?secret=JBSWY3DPEHPK3PXP"
            "&issuer=ACME%20Co&algorithm=SHA256&digits=8&period=60")
        self.assertEqual(info.secret, "JBSWY3DPEHPK3PXP")
        self.assertEqual(info.issuer, "ACME Co")
        self.assertEqual(info.label, "ACME Co:john@example.com")
        self.assertEqual(info.account, "john@example.com")
        self.assertEqual((info.digits, info.period, info.algorithm), (8, 60, "SHA256"))

    def test_issuer_from_label(self):
        info = parse_otpauth_uri("otpauth://totp/GitHub:tino?secret=JBSWY3DPEHPK3PXP")
        self.assertEqual(info.issuer, "GitHub")
        self.assertEqual(info.account, "tino")
        self.assertEqual(parse_otpauth_uri(
            "otpauth://totp/ana@x.com?secret=JBSWY3DPEHPK3PXP").account, "ana@x.com")
        self.assertEqual((info.digits, info.period, info.algorithm), (6, 30, "SHA1"))

    def test_rejects_invalid(self):
        for uri in ("https://example.com",
                    "otpauth://hotp/x?secret=JBSWY3DPEHPK3PXP&counter=1",
                    "otpauth://totp/x?issuer=foo"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                parse_otpauth_uri(uri)


if __name__ == "__main__":
    unittest.main()
