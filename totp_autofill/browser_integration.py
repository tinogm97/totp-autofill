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

_HOME = Path.home()
CHROMIUM_DIRS = {
    "Google Chrome": _HOME / ".config/google-chrome/NativeMessagingHosts",
    "Chromium": _HOME / ".config/chromium/NativeMessagingHosts",
    "Brave": _HOME / ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
    "Microsoft Edge": _HOME / ".config/microsoft-edge/NativeMessagingHosts",
    "Vivaldi": _HOME / ".config/vivaldi/NativeMessagingHosts",
}
FIREFOX_DIRS = {
    "Firefox": _HOME / ".mozilla/native-messaging-hosts",
}


def _write_manifest(directory: Path, manifest: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{HOST_NAME}.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


def install(host_path: Path, extra_chrome_ids: list[str] | None = None) -> list[Path]:
    """Registra el host en todos los navegadores detectados.

    Se escribe el manifiesto si existe la carpeta de configuración del
    navegador (es decir, si el navegador está instalado y se ha abierto).
    """
    host_path = host_path.resolve()
    chrome_ids = [CHROME_EXTENSION_ID, *(extra_chrome_ids or [])]
    base = {"name": HOST_NAME, "description": DESCRIPTION,
            "path": str(host_path), "type": "stdio"}

    written = []
    for directory in CHROMIUM_DIRS.values():
        if directory.parent.exists():
            written.append(_write_manifest(directory, {
                **base,
                "allowed_origins": [f"chrome-extension://{i}/" for i in chrome_ids],
            }))
    for directory in FIREFOX_DIRS.values():
        if directory.parent.exists():
            written.append(_write_manifest(directory, {
                **base, "allowed_extensions": [FIREFOX_EXTENSION_ID],
            }))
    return written


def uninstall() -> list[Path]:
    """Elimina los manifiestos instalados."""
    removed = []
    for directory in [*CHROMIUM_DIRS.values(), *FIREFOX_DIRS.values()]:
        target = directory / f"{HOST_NAME}.json"
        if target.exists():
            target.unlink()
            removed.append(target)
    return removed
