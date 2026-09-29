"""Generador de exportaciones de Google Authenticator de prueba (secretos falsos).

Codifica el protobuf ``MigrationPayload`` a mano, igual que lo haría la app.
Lo usan los tests y ``scripts`` para crear las imágenes de ``tests/data``.
"""

import base64
from urllib.parse import quote


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(number: int, value) -> bytes:
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    data = value.encode() if isinstance(value, str) else value
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def otp(secret: bytes, name: str, issuer: str = "", algorithm: int = 1, digits: int = 1,
        otp_type: int = 2) -> bytes:
    return (_field(1, secret) + _field(2, name) + _field(3, issuer) + _field(4, algorithm)
            + _field(5, digits) + _field(6, otp_type))


def migration_uri(otps: list[bytes], index: int = 0, size: int = 1, batch_id: int = 42) -> str:
    payload = b"".join(_field(1, o) for o in otps)
    payload += _field(2, 1) + _field(3, size) + _field(4, index) + _field(5, batch_id)
    return "otpauth-migration://offline?data=" + quote(base64.b64encode(payload).decode())


# Exportación de ejemplo en dos QR (como hace Google con muchas cuentas).
BATCH_1 = migration_uri([
    otp(b"Hello!\xde\xad\xbe\xef", "ana@empresa.com", "GitHub"),
    otp(b"secret-two-12345", "Dropbox:ana@empresa.com"),
    otp(b"hotp-secret-xxxx", "Banco", otp_type=1),  # HOTP: no se importa
], index=0, size=2)
BATCH_2 = migration_uri([
    otp(b"secret-three-678", "tino@empresa.com", "VPN Empresa", algorithm=2, digits=2),
], index=1, size=2)
