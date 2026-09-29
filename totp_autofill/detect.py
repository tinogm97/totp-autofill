"""Heurísticas para reconocer campos de código 2FA y de usuario.

Trabajan sobre la información que la accesibilidad (AT-SPI) expone de un
``<input>``: etiqueta, placeholder, id, name, tipo y ``maxlength``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OTP_HINT = re.compile(
    r"(one.?time|otp|totp|2fa|mfa|two.?factor|second.?factor|verif|auth.?code|"
    r"security.?code|passcode|token|c[oó]digo|code|pin\b|authenticator|autenticaci)",
    re.IGNORECASE)
NOT_OTP = re.compile(
    r"(user|e-?mail|login|search|buscar|phone|tel[eé]fono|zip|postal|captcha|"
    r"coupon|promo|cup[oó]n|card|tarjeta|cvv|cvc|country|pa[ií]s|password|contrase)",
    re.IGNORECASE)
USER_HINT = re.compile(
    r"(user|e-?mail|login|correo|usuario|account|cuenta|identifier)", re.IGNORECASE)
TEXT_TYPES = {"", "text", "tel", "number", "email", "password"}


@dataclass
class FieldInfo:
    """Lo que se sabe de un campo de texto de una página."""

    label: str = ""  # nombre accesible (normalmente, la <label>)
    placeholder: str = ""
    html_id: str = ""
    html_name: str = ""
    css_class: str = ""
    input_type: str = ""  # text, tel, number, email, password...
    maxlength: int = 0  # 0 = sin límite
    autocomplete: str = ""

    @property
    def text(self) -> str:
        return " ".join((self.label, self.placeholder, self.html_id,
                         self.html_name, self.css_class))

    @classmethod
    def from_atspi(cls, name: str, attrs: dict[str, str]) -> "FieldInfo":
        try:
            maxlength = int(attrs.get("maxlength", "0"))
        except ValueError:
            maxlength = 0
        return cls(
            label=name or "",
            placeholder=attrs.get("placeholder-text", ""),
            html_id=attrs.get("id", ""),
            html_name=attrs.get("html-input-name", attrs.get("name", "")),
            css_class=attrs.get("class", ""),
            input_type=attrs.get("text-input-type", ""),
            maxlength=maxlength,
            autocomplete=attrs.get("autocomplete", ""),
        )


def otp_confidence(info: FieldInfo, digits: int = 6) -> int:
    """¿Parece el campo del código 2FA? 0 = no, 1 = puede, 2 = casi seguro.

    Con 2 (``autocomplete=one-time-code`` o una etiqueta que habla de código)
    se puede preguntar qué cuenta usar; con 1 (solo por la longitud) solo se
    rellena si el sitio ya está asociado a una cuenta.
    """
    if info.input_type not in TEXT_TYPES or info.input_type == "email":
        return 0
    if "one-time-code" in info.autocomplete:
        return 2
    if NOT_OTP.search(info.text):
        return 0
    if OTP_HINT.search(info.text):
        return 2 if info.maxlength in (0, 1) or info.maxlength >= digits else 0
    # Cajas de un dígito (código "partido") o campo de 6-8 caracteres.
    return 1 if info.maxlength == 1 or info.maxlength in (6, 7, 8) else 0


def is_otp_field(info: FieldInfo, digits: int = 6) -> bool:
    return otp_confidence(info, digits) > 0


def is_user_field(info: FieldInfo) -> bool:
    """¿Parece un campo de email o usuario de un formulario de login?"""
    if info.input_type == "email":
        return True
    if info.input_type not in ("", "text"):
        return False
    if "username" in info.autocomplete or "email" in info.autocomplete:
        return True
    return bool(USER_HINT.search(info.text)) and not OTP_HINT.search(
        info.html_id + " " + info.html_name)
