"""Activar la accesibilidad en navegadores Chromium para el modo automático.

Chrome solo expone las páginas por AT-SPI si arranca con
``--force-renderer-accessibility`` **y** con la variable de entorno
``QT_ACCESSIBILITY=1`` (Ubuntu la define en la sesión, pero no llega a los
navegadores lanzados con un entorno limpio, p. ej. vía ``pkexec``). Aquí se
crea, en el usuario, una copia del lanzador (``.desktop``) del navegador con
ambas cosas, que tiene prioridad sobre el del sistema. Se deshace con
``disable()``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

FLAG = "--force-renderer-accessibility"
ENV_PREFIX = "env QT_ACCESSIBILITY=1 "
MARKER_CREATED = "X-TotpAutofill-Created=true"
MARKER_MODIFIED = "X-TotpAutofill-Modified=true"
BROWSER_DESKTOP_FILES = (
    "google-chrome.desktop", "google-chrome-beta.desktop", "google-chrome-unstable.desktop",
    "chromium.desktop", "chromium-browser.desktop", "brave-browser.desktop",
    "microsoft-edge.desktop", "vivaldi-stable.desktop",
)
BROWSER_PROCESSES = ("chrome", "chromium", "chromium-browser", "brave", "msedge", "vivaldi-bin")
SYSTEM_DIRS = (Path("/usr/share/applications"), Path("/usr/local/share/applications"))


def user_apps_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "applications"


_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\S+')


def _add_flag(text: str) -> str:
    """En cada ``Exec=``: ``env QT_ACCESSIBILITY=1 <exe> --force-renderer-accessibility …``.

    Respeta rutas entre comillas y un ``env VAR=…`` que ya existiera.
    """
    def fix(match: re.Match) -> str:
        line = match.group(0)
        if FLAG in line:
            return line
        value = line[len("Exec="):]
        tokens = list(_TOKEN.finditer(value))
        if not tokens:
            return line
        i = 0
        has_env = tokens[0].group(0) == "env"
        if has_env:
            i = 1
            while i < len(tokens) and "=" in tokens[i].group(0) and not tokens[i].group(0).startswith("-"):
                i += 1
            if i >= len(tokens):
                return line
        exe_end = tokens[i].end()
        value = f"{value[:exe_end]} {FLAG}{value[exe_end:]}"
        if "QT_ACCESSIBILITY=" not in value:
            value = (f"env QT_ACCESSIBILITY=1 {value[4:]}" if has_env
                     else f"{ENV_PREFIX}{value}")
        return f"Exec={value}"
    return re.sub(r"^Exec=.*$", fix, text, flags=re.MULTILINE)


def _with_marker(text: str, marker: str) -> str:
    # El marcador va en el grupo [Desktop Entry], justo tras su cabecera.
    return text.replace("[Desktop Entry]\n", f"[Desktop Entry]\n{marker}\n", 1)


def _backup_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "totp-autofill" / "launcher-backups"


def enable(apps_dir: Path | None = None, system_dirs=SYSTEM_DIRS,
           backup_dir: Path | None = None) -> list[Path]:
    """Crea o ajusta los lanzadores de usuario de los navegadores instalados.

    Si ya existía un lanzador de usuario, se guarda una copia exacta para
    que ``disable()`` lo restaure tal cual.
    """
    apps_dir = apps_dir or user_apps_dir()
    backup_dir = backup_dir or _backup_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)
    changed = []
    for name in BROWSER_DESKTOP_FILES:
        user_file = apps_dir / name
        system_file = next((d / name for d in system_dirs if (d / name).is_file()), None)
        if user_file.is_file():
            original = user_file.read_text(encoding="utf-8")
            if MARKER_CREATED in original or MARKER_MODIFIED in original:
                text = original
            else:
                backup_dir.mkdir(parents=True, exist_ok=True)
                (backup_dir / name).write_text(original, encoding="utf-8")
                text = _with_marker(original, MARKER_MODIFIED)
        elif system_file is not None:
            original = ""
            text = _with_marker(system_file.read_text(encoding="utf-8"), MARKER_CREATED)
        else:
            continue
        new = _add_flag(text)
        if new != original:
            user_file.write_text(new, encoding="utf-8")
            changed.append(user_file)
    return changed


def disable(apps_dir: Path | None = None, backup_dir: Path | None = None) -> list[Path]:
    """Deshace ``enable``: borra las copias creadas y restaura las modificadas."""
    apps_dir = apps_dir or user_apps_dir()
    backup_dir = backup_dir or _backup_dir()
    changed = []
    for name in BROWSER_DESKTOP_FILES:
        user_file = apps_dir / name
        if not user_file.is_file():
            continue
        text = user_file.read_text(encoding="utf-8")
        backup = backup_dir / name
        if MARKER_CREATED in text:
            user_file.unlink()
        elif MARKER_MODIFIED in text and backup.is_file():
            user_file.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            backup.unlink()
        else:
            continue
        changed.append(user_file)
    return changed


def is_enabled(apps_dir: Path | None = None) -> bool:
    apps_dir = apps_dir or user_apps_dir()
    return any(FLAG in (apps_dir / n).read_text(encoding="utf-8")
               for n in BROWSER_DESKTOP_FILES if (apps_dir / n).is_file())


@dataclass
class BrowserProcess:
    pid: int
    exe: str
    user_data_dir: str
    accessible: bool


def running_browsers(proc: Path = Path("/proc")) -> list[BrowserProcess]:
    """Procesos principales de navegadores Chromium y si tienen el flag."""
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        args = [a.decode("utf-8", "replace") for a in args if a]
        if not args or os.path.basename(args[0]) not in BROWSER_PROCESSES:
            continue
        if any(a.startswith("--type=") for a in args):
            continue  # proceso auxiliar (renderer, gpu...)
        data_dir = next((a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir=")), "")
        found.append(BrowserProcess(int(entry.name), args[0], data_dir, FLAG in args))
    return found


VPN_SCRIPT = Path("/usr/local/bin/chrome-vpn-session")


def vpn_script_fix() -> str | None:
    """Si existe el lanzador de Chrome VPN sin accesibilidad, el comando que lo arregla.

    Ese script lanza Chrome con ``env -i`` y una lista fija de variables, así
    que hay que añadir ``QT_ACCESSIBILITY=1`` a esa lista y el flag a Chrome.
    """
    try:
        text = VPN_SCRIPT.read_text(encoding="utf-8")
    except OSError:
        return None
    edits = []
    if "QT_ACCESSIBILITY" not in text and 'DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME_DIR/bus"' in text:
        edits.append(r"-e 's|^\(\s*\)DBUS_SESSION_BUS_ADDRESS=\(.*\)$|&\n\1QT_ACCESSIBILITY=1|'")
    if FLAG not in text and '--user-data-dir="$USER_DATA_DIR"' in text:
        old = '--user-data-dir="$USER_DATA_DIR"'
        edits.append(f"-e 's|{old}|{old} {FLAG}|'")
    return f"sudo sed -i {' '.join(edits)} {VPN_SCRIPT}" if edits else None
