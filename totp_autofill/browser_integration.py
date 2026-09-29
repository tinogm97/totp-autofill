"""Registro del host de Native Messaging en los navegadores del usuario.

Cada navegador busca un fichero JSON (``<HOST_NAME>.json``) en una carpeta
concreta que indica qué ejecutable lanzar y qué extensiones pueden usarlo.
"""

from __future__ import annotations

import json
from pathlib import Path

HOST_NAME = "com.github.tinogm97.totp_autofill"
DESCRIPTION = "TOTP Autofill - generador de códigos 2FA"

# ID fijo de la extensión en navegadores Chromium. Se deriva de la clave
# pública ("key") incluida en extension/manifest.json.
CHROME_EXTENSION_ID = "blnffoflcmdajflilndalbfcgeddaakd"
# ID de la extensión en Firefox (browser_specific_settings.gecko.id).
FIREFOX_EXTENSION_ID = "totp-autofill@tinogm97.github.io"

# Carpetas de datos estándar de navegadores Chromium (relativas a $HOME).
CHROMIUM_DATA_DIRS = [
    ".config/google-chrome",
    ".config/google-chrome-beta",
    ".config/google-chrome-unstable",
    ".config/chromium",
    ".config/BraveSoftware/Brave-Browser",
    ".config/microsoft-edge",
    ".config/vivaldi",
]
FIREFOX_HOST_DIR = ".mozilla/native-messaging-hosts"


def chromium_host_dirs(home: Path | None = None,
                       extra_data_dirs: list[Path] | None = None) -> list[Path]:
    """Carpetas ``NativeMessagingHosts`` de todos los navegadores Chromium.

    Chrome busca el host dentro de su carpeta de datos, así que un navegador
    lanzado con ``--user-data-dir`` (p. ej. un Chrome aparte para la VPN)
    necesita su propio registro. Además de las carpetas estándar, se detecta
    cualquier carpeta de ``~/.config`` con un perfil de navegador
    (``Local State`` + ``Default/Preferences``). Las apps Electron (VS Code,
    etc.) también tienen ``Local State`` pero no ``Default/``, y se ignoran.
    """
    home = home or Path.home()
    candidates = [home / d for d in CHROMIUM_DATA_DIRS]
    config = home / ".config"
    if config.is_dir():
        for pattern in ("*/Local State", "*/*/Local State"):
            candidates += sorted(p.parent for p in config.glob(pattern)
                                 if (p.parent / "Default" / "Preferences").is_file())
    candidates += list(extra_data_dirs or [])

    dirs: list[Path] = []
    for data_dir in candidates:
        target = data_dir / "NativeMessagingHosts"
        if data_dir.is_dir() and target not in dirs:
            dirs.append(target)
    return dirs


def _write_manifest(directory: Path, manifest: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{HOST_NAME}.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


def install(host_path: Path, extra_chrome_ids: list[str] | None = None,
            extra_data_dirs: list[Path] | None = None,
            home: Path | None = None) -> list[Path]:
    """Registra el host en todos los navegadores detectados.

    Se escribe el manifiesto si existe la carpeta de datos del navegador (es
    decir, si está instalado y se ha abierto alguna vez). ``extra_data_dirs``
    permite indicar carpetas ``--user-data-dir`` fuera de ``~/.config``.
    """
    home = home or Path.home()
    host_path = host_path.resolve()
    chrome_ids = [CHROME_EXTENSION_ID, *(extra_chrome_ids or [])]
    base = {"name": HOST_NAME, "description": DESCRIPTION,
            "path": str(host_path), "type": "stdio"}

    written = []
    for directory in chromium_host_dirs(home, extra_data_dirs):
        written.append(_write_manifest(directory, {
            **base,
            "allowed_origins": [f"chrome-extension://{i}/" for i in chrome_ids],
        }))
    firefox = home / FIREFOX_HOST_DIR
    if firefox.parent.exists():
        written.append(_write_manifest(firefox, {
            **base, "allowed_extensions": [FIREFOX_EXTENSION_ID],
        }))
    return written


def uninstall(extra_data_dirs: list[Path] | None = None,
              home: Path | None = None) -> list[Path]:
    """Elimina los manifiestos instalados."""
    home = home or Path.home()
    removed = []
    for directory in [*chromium_host_dirs(home, extra_data_dirs), home / FIREFOX_HOST_DIR]:
        target = directory / f"{HOST_NAME}.json"
        if target.exists():
            target.unlink()
            removed.append(target)
    return removed
