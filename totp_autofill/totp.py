"""Generación de códigos TOTP (RFC 6238) y parseo de URIs ``otpauth://``.

Implementado solo con la librería estándar para no depender de paquetes
externos. Compatible con Google Authenticator, Microsoft Authenticator,
Authy (modo TOTP), etc.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

ALGORITHMS = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}


class InvalidSecretError(ValueError):
    """El secreto no es Base32 válido."""


def normalize_secret(secret: str) -> str:
    """Limpia un secreto Base32 (espacios, guiones, minúsculas) y lo valida."""
    cleaned = secret.replace(" ", "").replace("-", "").upper().rstrip("=")
    if not cleaned:
        raise InvalidSecretError("El secreto está vacío")
    try:
        decode_secret(cleaned)
    except (binascii.Error, ValueError) as exc:
        raise InvalidSecretError(f"El secreto no es Base32 válido: {exc}") from exc
    return cleaned


def decode_secret(secret: str) -> bytes:
    """Decodifica un secreto Base32, añadiendo el padding que falte."""
    padding = "=" * (-len(secret) % 8)
    return base64.b32decode(secret.upper() + padding, casefold=True)


def hotp(key: bytes, counter: int, digits: int = 6, algorithm: str = "SHA1") -> str:
    """Calcula un código HOTP (RFC 4226) para ``counter``."""
    digest = hmac.new(key, struct.pack(">Q", counter), ALGORITHMS[algorithm]).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def totp(
    secret: str,
    *,
    digits: int = 6,
    period: int = 30,
    algorithm: str = "SHA1",
    at: float | None = None,
) -> str:
    """Devuelve el código TOTP vigente para ``secret`` en el instante ``at``."""
    now = time.time() if at is None else at
    return hotp(decode_secret(secret), int(now // period), digits, algorithm)


def seconds_remaining(period: int = 30, at: float | None = None) -> int:
    """Segundos que le quedan de validez al código actual."""
    now = time.time() if at is None else at
    return period - int(now % period)


@dataclass
class OtpAuthUri:
    """Datos extraídos de una URI ``otpauth://totp/...`` (la que codifica el QR)."""

    secret: str
    label: str = ""
    issuer: str = ""
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"

    @property
    def account(self) -> str:
        """Cuenta del label (``Emisor:cuenta`` → ``cuenta``), normalmente un email."""
        return self.label.split(":", 1)[-1].strip()


def parse_otpauth_uri(uri: str) -> OtpAuthUri:
    """Parsea una URI ``otpauth://totp/Issuer:cuenta?secret=...``.

    Lanza ``ValueError`` si la URI no es TOTP o le falta el secreto.
    """
    parsed = urlparse(uri.strip())
    if parsed.scheme != "otpauth":
        raise ValueError("La URI debe empezar por otpauth://")
    if parsed.netloc.lower() != "totp":
        raise ValueError("Solo se admiten URIs de tipo TOTP (otpauth://totp/...)")

    params = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
    if "secret" not in params:
        raise ValueError("La URI no contiene el parámetro 'secret'")

    label = unquote(parsed.path.lstrip("/"))
    issuer = params.get("issuer", "")
    if not issuer and ":" in label:
        issuer = label.split(":", 1)[0]

    algorithm = params.get("algorithm", "SHA1").upper()
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Algoritmo no soportado: {algorithm}")

    return OtpAuthUri(
        secret=normalize_secret(params["secret"]),
        label=label,
        issuer=issuer,
        digits=int(params.get("digits", 6)),
        period=int(params.get("period", 30)),
        algorithm=algorithm,
    )
