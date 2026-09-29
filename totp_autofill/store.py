"""Almacenamiento de cuentas.

- Los **metadatos** (nombre, patrón de URL, selector...) se guardan en
  ``~/.config/totp-autofill/accounts.json`` (permisos 600).
- Los **secretos TOTP** se guardan en el llavero del sistema (GNOME Keyring /
  KWallet vía libsecret) y nunca se escriben en disco en claro.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .totp import ALGORITHMS, normalize_secret, seconds_remaining, totp

APP_ID = "totp-autofill"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_ID


# --------------------------------------------------------------------------
# Patrones de URL
# --------------------------------------------------------------------------


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convierte un patrón con comodines ``*`` en una expresión regular.

    Solo ``*`` es especial (equivale a "cualquier cosa"); el resto de
    caracteres, incluidos ``?`` y ``.``, se comparan literalmente.
    """
    parts = (re.escape(chunk) for chunk in pattern.split("*"))
    return re.compile("^" + ".*".join(parts) + "$", re.IGNORECASE)


def url_matches(pattern: str, url: str) -> bool:
    """Indica si ``url`` encaja con ``pattern``.

    Reglas:
    - ``*`` es comodín. Ej: ``https://login.empresa.com/mfa*``.
    - Si el patrón no indica esquema (``https://``), vale cualquiera.
    - Si el patrón no contiene ``?`` ni ``#``, se ignoran la query y el
      fragmento de la URL, para que ``/2fa`` encaje con ``/2fa?next=/``.
    """
    pattern = pattern.strip()
    if not pattern or not url:
        return False
    if "://" not in pattern:
        pattern = "*://" + pattern
    if "?" not in pattern and "#" not in pattern:
        scheme, netloc, path, _query, _fragment = urlsplit(url)
        url = urlunsplit((scheme, netloc, path, "", ""))
    return bool(_pattern_to_regex(pattern).match(url))


# --------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------


@dataclass
class Account:
    """Una cuenta 2FA asociada a una página de formulario."""

    name: str
    url_pattern: str
    selector: str = ""  # selector CSS del campo; vacío = detección automática
    auto_submit: bool = False  # enviar el formulario tras rellenar
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("El nombre es obligatorio")
        if not self.url_pattern.strip():
            raise ValueError("El patrón de URL es obligatorio")
        if self.digits not in (6, 7, 8):
            raise ValueError("Los dígitos deben ser 6, 7 u 8")
        if self.period <= 0:
            raise ValueError("El periodo debe ser positivo")
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"Algoritmo no soportado: {self.algorithm}")

    def public_info(self) -> dict:
        """Datos que se pueden enviar a la extensión (sin secreto)."""
        return {
            "id": self.id,
            "name": self.name,
            "selector": self.selector,
            "autoSubmit": self.auto_submit,
            "digits": self.digits,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------
# Llavero
# --------------------------------------------------------------------------


class SecretBackend(Protocol):
    def get(self, account_id: str) -> str | None: ...
    def set(self, account_id: str, label: str, secret: str) -> None: ...
    def delete(self, account_id: str) -> None: ...


class LibsecretBackend:
    """Guarda los secretos en el llavero del escritorio mediante libsecret."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        self._secret = Secret
        self._schema = Secret.Schema.new(
            "com.github.tinogm97.TotpAutofill",
            Secret.SchemaFlags.NONE,
            {"account_id": Secret.SchemaAttributeType.STRING},
        )

    def get(self, account_id: str) -> str | None:
        return self._secret.password_lookup_sync(
            self._schema, {"account_id": account_id}, None
        )

    def set(self, account_id: str, label: str, secret: str) -> None:
        self._secret.password_store_sync(
            self._schema,
            {"account_id": account_id},
            self._secret.COLLECTION_DEFAULT,
            f"TOTP Autofill: {label}",
            secret,
            None,
        )

    def delete(self, account_id: str) -> None:
        self._secret.password_clear_sync(
            self._schema, {"account_id": account_id}, None
        )


class MemoryBackend:
    """Backend en memoria, solo para tests."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, account_id: str) -> str | None:
        return self.data.get(account_id)

    def set(self, account_id: str, label: str, secret: str) -> None:
        self.data[account_id] = secret

    def delete(self, account_id: str) -> None:
        self.data.pop(account_id, None)


# --------------------------------------------------------------------------
# Almacén
# --------------------------------------------------------------------------


class AccountStore:
    """Punto de acceso único a cuentas y secretos."""

    def __init__(
        self, path: Path | None = None, secrets: SecretBackend | None = None
    ) -> None:
        self.path = path or config_dir() / "accounts.json"
        self.secrets = secrets or LibsecretBackend()

    # -- persistencia de metadatos -------------------------------------

    def load(self) -> list[Account]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return [Account.from_dict(item) for item in data.get("accounts", [])]

    def _save(self, accounts: list[Account]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(
                {"version": 1, "accounts": [asdict(a) for a in accounts]},
                fh,
                indent=2,
                ensure_ascii=False,
            )
        os.replace(tmp, self.path)

    # -- operaciones ---------------------------------------------------

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self.load() if a.id == account_id), None)

    def save(self, account: Account, secret: str | None = None) -> Account:
        """Crea o actualiza ``account``. ``secret`` es obligatorio al crear."""
        account.validate()
        accounts = self.load()
        existing = next((i for i, a in enumerate(accounts) if a.id == account.id), None)
        if existing is None and not secret:
            raise ValueError("El secreto es obligatorio para una cuenta nueva")
        if secret:
            self.secrets.set(account.id, account.name, normalize_secret(secret))
        if existing is None:
            accounts.append(account)
        else:
            accounts[existing] = account
        self._save(accounts)
        return account

    def delete(self, account_id: str) -> None:
        self._save([a for a in self.load() if a.id != account_id])
        self.secrets.delete(account_id)

    def match(self, url: str) -> list[Account]:
        """Cuentas cuyo patrón encaja con ``url``."""
        return [a for a in self.load() if url_matches(a.url_pattern, url)]

    def code(self, account: Account) -> tuple[str, int]:
        """Devuelve ``(código, segundos_restantes)`` de la cuenta."""
        secret = self.secrets.get(account.id)
        if not secret:
            raise LookupError(f"No hay secreto en el llavero para '{account.name}'")
        return (
            totp(secret, digits=account.digits, period=account.period,
                 algorithm=account.algorithm),
            seconds_remaining(account.period),
        )
