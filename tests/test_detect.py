import unittest

from totp_autofill.detect import FieldInfo, is_user_field, otp_confidence


def field(**kw):
    return FieldInfo(**kw)


class OtpDetectionTest(unittest.TestCase):
    def test_strong(self):
        for info in (
            field(autocomplete="one-time-code"),
            field(label="Código", html_id="otp", maxlength=6),
            field(label="Verification code"),
            field(html_name="totp", input_type="number"),
            field(placeholder="Código de 6 dígitos", input_type="tel"),
            field(label="2FA", input_type="password"),
            field(html_id="otp-1", maxlength=1),
        ):
            with self.subTest(info=info):
                self.assertEqual(otp_confidence(info), 2)

    def test_weak(self):
        self.assertEqual(otp_confidence(field(maxlength=6)), 1)
        self.assertEqual(otp_confidence(field(maxlength=1, css_class="digit")), 1)
        # Firefox no expone maxlength: se reconoce el grupo de 6 cajas.
        self.assertEqual(otp_confidence(field(css_class="digit"), group_size=6), 1)
        self.assertEqual(otp_confidence(field(css_class="digit"), group_size=2), 0)
        self.assertEqual(otp_confidence(field(label="Nombre"), group_size=6), 0)

    def test_not_otp(self):
        for info in (
            field(label="Email", input_type="email"),
            field(label="Usuario"),
            field(label="Contraseña", input_type="password"),
            field(label="Código postal", maxlength=5),
            field(label="Código promocional"),
            field(label="Buscar"),
            field(label="Nombre"),
            field(label="Código", maxlength=4),
            field(label="code", input_type="url"),
        ):
            with self.subTest(info=info):
                self.assertEqual(otp_confidence(info), 0)

    def test_from_atspi(self):
        info = FieldInfo.from_atspi("Código", {
            "tag": "input", "id": "otp", "html-input-name": "otp_code",
            "text-input-type": "text", "maxlength": "6"})
        self.assertEqual((info.html_id, info.html_name, info.maxlength), ("otp", "otp_code", 6))
        self.assertEqual(otp_confidence(info), 2)
        self.assertEqual(FieldInfo.from_atspi("", {"maxlength": "x"}).maxlength, 0)


class UserFieldTest(unittest.TestCase):
    def test_user_fields(self):
        self.assertTrue(is_user_field(field(input_type="email")))
        self.assertTrue(is_user_field(field(label="Usuario")))
        self.assertTrue(is_user_field(field(html_name="username")))
        self.assertTrue(is_user_field(field(autocomplete="username")))

    def test_not_user_fields(self):
        self.assertFalse(is_user_field(field(label="Contraseña", input_type="password")))
        self.assertFalse(is_user_field(field(label="Código", html_id="otp")))
        self.assertFalse(is_user_field(field(label="Buscar", input_type="number")))


if __name__ == "__main__":
    unittest.main()
