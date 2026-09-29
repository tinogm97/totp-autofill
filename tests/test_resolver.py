import unittest

from totp_autofill.resolver import Context, resolve
from totp_autofill.store import Account

ANA = Account("Portal dev", username="ana@x.com", sites=["localhost:4200"])
LUIS = Account("Portal dev", username="luis@x.com", sites=["localhost:4200"])
GITHUB = Account("GitHub", username="tino", sites=["github.com"])
VPN = Account("VPN", window_titles=["Verificación - VPN Empresa"])
ALL = [ANA, LUIS, GITHUB, VPN]


class ResolverTest(unittest.TestCase):
    def test_by_site_is_trusted(self):
        res = resolve(ALL, Context(host="github.com"))
        self.assertIs(res.account, GITHUB)
        self.assertEqual(res.via, "site")
        self.assertTrue(res.trusted)

    def test_same_site_needs_user(self):
        res = resolve(ALL, Context(host="localhost:4200"))
        self.assertIsNone(res.account)
        self.assertEqual(res.candidates[:2], [ANA, LUIS])  # las del sitio primero
        self.assertEqual(len(res.candidates), 4)

    def test_same_site_by_typed_user(self):
        res = resolve(ALL, Context(host="localhost:4200", recent_user="LUIS@x.com"))
        self.assertIs(res.account, LUIS)
        self.assertTrue(res.trusted)

    def test_same_site_by_email_in_page(self):
        res = resolve(ALL, Context(host="localhost:4200",
                                   page_text="Introduce el código para ana@x.com"))
        self.assertIs(res.account, ANA)

    def test_both_emails_in_page_is_ambiguous(self):
        res = resolve(ALL, Context(host="localhost:4200", page_text="ana@x.com luis@x.com"))
        self.assertIsNone(res.account)

    def test_by_window_title_is_not_trusted(self):
        res = resolve(ALL, Context(title="Verificación - VPN Empresa - Google Chrome"))
        self.assertIs(res.account, VPN)
        self.assertEqual(res.via, "title")
        self.assertFalse(res.trusted)  # el título lo controla la página

    def test_site_wins_over_title(self):
        res = resolve(ALL, Context(host="github.com", title="Verificación - VPN Empresa"))
        self.assertIs(res.account, GITHUB)

    def test_unknown_site_asks(self):
        res = resolve(ALL, Context(host="evil.com", title="GitHub"))
        self.assertIsNone(res.account)
        self.assertFalse(res.trusted)
        self.assertEqual(len(res.candidates), 4)

    def test_unknown_site_orders_by_user(self):
        res = resolve(ALL, Context(host="nuevo.com", recent_user="tino"))
        self.assertIsNone(res.account)
        self.assertIs(res.candidates[0], GITHUB)

    def test_single_account(self):
        res = resolve([GITHUB], Context(title="Cualquier cosa"))
        self.assertIs(res.account, GITHUB)
        self.assertEqual(res.via, "only")
        self.assertFalse(res.trusted)  # el modo automático no la usa sin sitio

    def test_no_accounts(self):
        res = resolve([], Context(host="x.com"))
        self.assertIsNone(res.account)
        self.assertEqual(res.candidates, [])


if __name__ == "__main__":
    unittest.main()
