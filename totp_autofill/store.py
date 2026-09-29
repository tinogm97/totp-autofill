"""Almacenamiento de cuentas y preferencias.

- Los **metadatos** (nombre, usuario, sitios...) se guardan en
  ``~/.config/totp-autofill/accounts.json`` (permisos 600).
- Los **secretos TOTP** se guardan en el llavero del sistema (GNOME Keyring /
  KWallet vía libsecret) y nunca se escriben en disco en claro.
- Las **preferencias** van en ``~/.config/totp-autofill/settings.json``.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .totp import ALGORITHMS, normalize_secret, seconds_remaining, totp

APP_ID = "totp-autofill"
MAX_LEARNED_TITLES = 20


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_ID


def _write_private_json(path: Path, data: dict) -> None:
    """Escritura atómica con permisos 600."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Sitios
# --------------------------------------------------------------------------


def normalize_site(value: str) -> str:
    """Reduce una URL, patrón o host a ``host[:puerto]`` en minúsculas.

    ``https://sso.empresa.com/mfa*`` → ``sso.empresa.com``;
    ``localhost:4200`` → ``localhost:4200``; ``*.empresa.com`` se conserva.
    """
    value = value.strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = value.split("://", 1)[1]
    return value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]


def host_of(url: str) -> str:
    """``host[:puerto]`` de una URL (vacío si no es http/https)."""
    parts = urlsplit(url)
    return parts.netloc.lower() if parts.scheme in ("http", "https") else ""


def site_matches(site: str, host: str) -> bool:
    """``site`` puede llevar ``*`` como comodín (``*.empresa.com``)."""
    site, host = normalize_site(site), host.lower()
    if not site or not host:
        return False
    regex = ".*".join(re.escape(part) for part in site.split("*"))
    return re.fullmatch(regex, host) is not None


def clean_title(title: str) -> str:
    """Quita el sufijo del navegador de un título de ventana.

    ``Verificación - MiApp - Google Chrome`` → ``Verificación - MiApp``.
    """
    title = title.strip()
    for suffix in (" - Google Chrome for Testing", " - Google Chrome", " - Chromium", " — Mozilla Firefox",
                   " - Mozilla Firefox", " - Brave", " - Microsoft Edge", " - Vivaldi"):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


# --------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------


@dataclass
class Account:
    """Una cuenta 2FA.

    ``sites`` y ``window_titles`` indican dónde se usa. No son obligatorios:
    si faltan, la app pregunta la primera vez y los aprende.
    """

    name: str
    username: str = ""  # email o usuario; distingue cuentas del mismo sitio
    sites: list[str] = field(default_factory=list)  # hosts, admiten *
    window_titles: list[str] = field(default_factory=list)  # aprendidos
    auto_submit: bool = False  # pulsar Intro tras escribir el código
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self) -> None:
        self.name, self.username = self.name.strip(), self.username.strip()
        self.sites = list(dict.fromkeys(s for s in map(normalize_site, self.sites) if s))
        if not self.name:
            raise ValueError("El nombre es obligatorio")
        if self.digits not in (6, 7, 8):
            raise ValueError("Los dígitos deben ser 6, 7 u 8")
        if self.period <= 0:
            raise ValueError("El periodo debe ser positivo")
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"Algoritmo no soportado: {self.algorithm}")

    def matches_host(self, host: str) -> bool:
        return any(site_matches(site, host) for site in self.sites)

    @property
    def label(self) -> str:
        return f"{self.name} <{self.username}>" if self.username else self.name

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        data = dict(data)
        # v1.x: "url_pattern" se convierte en un sitio.
        legacy = data.pop("url_pattern", "")
        if legacy and not data.get("sites"):
            site = normalize_site(legacy)
            data["sites"] = [site] if site and site != "*" else []
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Settings:
    auto_fill: bool = True  # rellenar al entrar en un campo (modo accesibilidad)
    shortcut: str = "<Control><Alt>2"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        _write_private_json(path or config_dir() / "settings.json", asdict(self))


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


class FileBackend(MemoryBackend):
    """Secretos en un fichero JSON **en claro**. Solo para tests automáticos.

    Se activa con ``TOTP_AUTOFILL_TESTING=1`` **y**
    ``TOTP_AUTOFILL_TEST_SECRETS=/ruta/fichero.json``, para no depender del
    llavero del escritorio (ni tocarlo) en los tests.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def set(self, account_id: str, label: str, secret: str) -> None:
        super().set(account_id, label, secret)
        _write_private_json(self.path, self.data)

    def delete(self, account_id: str) -> None:
        super().delete(account_id)
        _write_private_json(self.path, self.data)


def default_secret_backend() -> SecretBackend:
    test_file = os.environ.get("TOTP_AUTOFILL_TEST_SECRETS")
    # Hacen falta las dos variables, para que no se active por descuido.
    if test_file and os.environ.get("TOTP_AUTOFILL_TESTING") == "1":
        import sys

        print(f"AVISO: secretos en {test_file} (en claro, solo para tests)", file=sys.stderr)
        return FileBackend(Path(test_file))
    return LibsecretBackend()


# --------------------------------------------------------------------------
# Almacén
# --------------------------------------------------------------------------


class AccountStore:
    """Punto de acceso único a cuentas y secretos."""

    def __init__(
        self, path: Path | None = None, secrets: SecretBackend | None = None
    ) -> None:
        self.path = path or config_dir() / "accounts.json"
        self.secrets = secrets or default_secret_backend()

    def load(self) -> list[Account]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return [Account.from_dict(item) for item in data.get("accounts", [])]

    def _save(self, accounts: list[Account]) -> None:
        _write_private_json(
            self.path, {"version": 2, "accounts": [asdict(a) for a in accounts]})

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self.load() if a.id == account_id), None)

    def save(self, account: Account, secret: str | None = None) -> Account:
        """Crea o actualiza ``account``. ``secret`` es obligatorio al crear."""
        account.validate()
        accounts = self.load()
        existing = next((i for i, a in enumerate(accounts) if a.id == account.id), None)
        duplicate = next((a for a in accounts if a.id != account.id
                          and a.name.lower() == account.name.lower()
                          and a.username.lower() == account.username.lower()), None)
        if duplicate:
            who = f"el usuario «{account.username}»" if account.username else "sin usuario"
            raise ValueError(
                f"Ya existe la cuenta «{duplicate.name}» con {who}. "
                "Indica un email o usuario distinto para diferenciarlas.")
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

    def learn(self, account_id: str, *, host: str = "", title: str = "") -> None:
        """Recuerda que ``account_id`` se usa en ``host`` o en la ventana ``title``."""
        accounts = self.load()
        account = next((a for a in accounts if a.id == account_id), None)
        if account is None:
            return
        host, title = normalize_site(host), clean_title(title)
        if host and not account.matches_host(host):
            account.sites.append(host)
        elif title and not host and title not in account.window_titles:
            account.window_titles = [title, *account.window_titles][:MAX_LEARNED_TITLES]
        else:
            return
        self._save(accounts)

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
