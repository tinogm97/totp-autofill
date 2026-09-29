"""Importación desde Google Authenticator (y URIs ``otpauth://`` sueltas).

Google Authenticator exporta sus cuentas (⋮ → *Transferir cuentas* →
*Exportar*) como uno o varios QR con una URI::

    otpauth-migration://offline?data=<protobuf en base64>

El protobuf (``MigrationPayload``) se decodifica aquí a mano, sin
dependencias::

    message MigrationPayload {
      message OtpParameters {
        bytes secret = 1;  string name = 2;  string issuer = 3;
        Algorithm algorithm = 4;   // 1 SHA1, 2 SHA256, 3 SHA512, 4 MD5
        DigitCount digits = 5;     // 1 seis, 2 ocho
        OtpType type = 6;          // 1 HOTP, 2 TOTP
        int64 counter = 7;
      }
      repeated OtpParameters otp_parameters = 1;
      int32 version = 2; int32 batch_size = 3; int32 batch_index = 4; int32 batch_id = 5;
    }
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

from .totp import parse_otpauth_uri

ALGORITHMS = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512"}  # 4 = MD5: no soportado
DIGITS = {0: 6, 1: 6, 2: 8}
TYPE_HOTP, TYPE_TOTP = 1, 2
URI_PATTERN = re.compile(r"otpauth(?:-migration)?://[^\s\"'<>]+", re.IGNORECASE)


@dataclass
class ImportedAccount:
    """Una cuenta leída de una exportación, lista para guardarse."""

    name: str
    username: str
    secret: str  # Base32
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"

    @property
    def label(self) -> str:
        return f"{self.name} <{self.username}>" if self.username else self.name


@dataclass
class Batch:
    """Contenido de un QR de exportación (Google reparte las cuentas en varios)."""

    accounts: list[ImportedAccount] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # no importables y por qué
    index: int = 0  # 0, 1, 2… de ``size``
    size: int = 1
    batch_id: int = 0


# -- protobuf mínimo ----------------------------------------------------------

def _varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("Datos de exportación truncados")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("Varint demasiado largo")


def _fields(data: bytes):
    """Recorre un mensaje protobuf: produce ``(número, tipo, valor)``."""
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 2:
            length, pos = _varint(data, pos)
            if pos + length > len(data):
                raise ValueError("Datos de exportación truncados")
            value, pos = data[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = data[pos:pos + 4], pos + 4
        elif wire == 1:
            value, pos = data[pos:pos + 8], pos + 8
        else:
            raise ValueError(f"Tipo protobuf no soportado: {wire}")
        yield number, wire, value


def _split_name(name: str, issuer: str) -> tuple[str, str]:
    """``Emisor:cuenta`` → (emisor, cuenta). Google guarda así el nombre."""
    name = name.strip()
    if ":" in name:
        prefix, account = name.split(":", 1)
        return (issuer or prefix).strip(), account.strip()
    return (issuer or name).strip(), (name if issuer else "").strip()


def _parse_otp(data: bytes) -> tuple[ImportedAccount | None, str]:
    values: dict[int, object] = {}
    for number, _wire, value in _fields(data):
        values[number] = value
    secret = values.get(1, b"")
    name = values.get(2, b"").decode("utf-8", "replace")
    issuer = values.get(3, b"").decode("utf-8", "replace")
    title, username = _split_name(name, issuer)
    label = f"{title} <{username}>" if username else title or "(sin nombre)"

    if values.get(6, TYPE_TOTP) == TYPE_HOTP:
        return None, f"{label}: es HOTP (por contador), solo se admite TOTP"
    algorithm = ALGORITHMS.get(values.get(4, 1))
    if algorithm is None:
        return None, f"{label}: algoritmo no soportado (MD5)"
    if not secret:
        return None, f"{label}: no tiene secreto"
    return ImportedAccount(
        name=title or username or "Sin nombre",
        username=username if title else "",
        secret=base64.b32encode(secret).decode().rstrip("="),
        digits=DIGITS.get(values.get(5, 1), 6),
        algorithm=algorithm,
    ), ""


def parse_migration_uri(uri: str) -> Batch:
    """Decodifica una URI ``otpauth-migration://offline?data=…``."""
    parsed = urlparse(uri.strip())
    if parsed.scheme.lower() != "otpauth-migration":
        raise ValueError("No es una exportación de Google Authenticator")
    data_param = parse_qs(parsed.query).get("data")
    if not data_param:
        raise ValueError("La exportación no contiene el parámetro 'data'")
    raw = unquote(data_param[0]).replace(" ", "+")
    try:
        payload = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=False)
    except binascii.Error as exc:
        raise ValueError(f"Exportación dañada: {exc}") from exc

    batch = Batch()
    for number, _wire, value in _fields(payload):
        if number == 1:
            account, reason = _parse_otp(value)
            if account:
                batch.accounts.append(account)
            else:
                batch.skipped.append(reason)
        elif number == 3:
            batch.size = max(1, value)
        elif number == 4:
            batch.index = value
        elif number == 5:
            batch.batch_id = value
    return batch


def find_uris(text: str) -> list[str]:
    """URIs ``otpauth://`` y ``otpauth-migration://`` que aparezcan en ``text``."""
    return URI_PATTERN.findall(text)


def accounts_from_uris(uris: list[str]) -> tuple[list[ImportedAccount], list[str], list[Batch]]:
    """Cuentas (sin duplicados) de una lista de URIs, avisos y lotes leídos."""
    accounts: list[ImportedAccount] = []
    skipped: list[str] = []
    batches: list[Batch] = []
    seen: set[str] = set()
    for uri in uris:
        try:
            if uri.lower().startswith("otpauth-migration://"):
                batch = parse_migration_uri(uri)
                batches.append(batch)
                found, skipped_here = batch.accounts, batch.skipped
            else:
                info = parse_otpauth_uri(uri)
                title, username = _split_name(info.label, info.issuer)
                found = [ImportedAccount(title or "Sin nombre", username if title else "",
                                         info.secret, info.digits, info.period,
                                         info.algorithm)]
                skipped_here = []
        except ValueError as exc:
            skipped.append(f"{uri[:40]}…: {exc}")
            continue
        skipped.extend(skipped_here)
        for account in found:
            if account.secret not in seen:
                seen.add(account.secret)
                accounts.append(account)
    return accounts, skipped, batches


def missing_batches(batches: list[Batch]) -> list[int]:
    """Números de QR (1, 2, …) de la exportación que aún no se han leído."""
    if not batches:
        return []
    by_id: dict[int, set[int]] = {}
    sizes: dict[int, int] = {}
    for batch in batches:
        by_id.setdefault(batch.batch_id, set()).add(batch.index)
        sizes[batch.batch_id] = batch.size
    missing = []
    for batch_id, seen in by_id.items():
        missing += [i + 1 for i in range(sizes[batch_id]) if i not in seen]
    return sorted(missing)


@dataclass
class ImportResult:
    imported: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)  # ya estaban (mismo secreto o nombre)
    errors: list[str] = field(default_factory=list)


def import_accounts(store, accounts: list[ImportedAccount]) -> ImportResult:
    """Guarda las cuentas en ``store``; omite las que ya existen."""
    from .store import Account

    result = ImportResult()
    known = set()
    for existing in store.load():
        secret = store.secrets.get(existing.id)
        if secret:
            known.add(secret.upper())
    for item in accounts:
        if item.secret.upper() in known:
            result.existing.append(item.label)
            continue
        account = Account(name=item.name, username=item.username, digits=item.digits,
                          period=item.period, algorithm=item.algorithm)
        try:
            store.save(account, item.secret)
        except ValueError as exc:
            (result.existing if "Ya existe" in str(exc) else result.errors).append(
                item.label if "Ya existe" in str(exc) else f"{item.label}: {exc}")
            continue
        known.add(item.secret.upper())
        result.imported.append(item.label)
    return result
