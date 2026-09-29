"""Atajo de teclado global en GNOME (Ajustes → Teclado → Atajos personalizados).

Se registra como atajo personalizado de gnome-settings-daemon, así que el
usuario lo ve y puede cambiarlo desde los Ajustes del sistema.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk  # noqa: E402

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/totp-autofill/"
NAME = "TOTP Autofill: escribir código 2FA"


def command_path() -> str:
    """Ruta absoluta del comando ``totp-autofill``.

    Los atajos de GNOME se ejecutan con el PATH de la sesión, que a menudo no
    incluye ``~/.local/bin``: por eso nunca se usa el nombre a secas.
    """
    import shutil
    from pathlib import Path

    installed = Path.home() / ".local" / "bin" / "totp-autofill"
    if installed.is_file():
        return str(installed)
    return shutil.which("totp-autofill") or str(installed)


def fill_command() -> str:
    """Orden del atajo; entrecomillada por si la ruta tiene espacios."""
    import shlex

    return f"{shlex.quote(command_path())} fill"


def available() -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(MEDIA_KEYS, True) is not None


def validate(binding: str) -> None:
    key, mods = Gtk.accelerator_parse(binding)
    if not key:
        raise ValueError(f"Atajo no válido: {binding!r} (ejemplo: <Control><Alt>2)")


def install(command: str, binding: str) -> None:
    if not available():
        raise RuntimeError("No es GNOME: configura el atajo a mano (ver README)")
    validate(binding)
    custom = Gio.Settings.new_with_path(CUSTOM, PATH)
    custom.set_string("name", NAME)
    custom.set_string("command", command)
    custom.set_string("binding", binding)
    media = Gio.Settings.new(MEDIA_KEYS)
    paths = list(media.get_strv("custom-keybindings"))
    if PATH not in paths:
        media.set_strv("custom-keybindings", [*paths, PATH])
    Gio.Settings.sync()


def uninstall() -> None:
    if not available():
        return
    media = Gio.Settings.new(MEDIA_KEYS)
    paths = [p for p in media.get_strv("custom-keybindings") if p != PATH]
    media.set_strv("custom-keybindings", paths)
    custom = Gio.Settings.new_with_path(CUSTOM, PATH)
    for key in ("name", "command", "binding"):
        custom.reset(key)
    Gio.Settings.sync()


def current() -> str:
    if not available():
        return ""
    media = Gio.Settings.new(MEDIA_KEYS)
    if PATH not in media.get_strv("custom-keybindings"):
        return ""
    return Gio.Settings.new_with_path(CUSTOM, PATH).get_string("binding")


def label(binding: str) -> str:
    """``<Control><Alt>2`` → ``Ctrl+Alt+2``."""
    key, mods = Gtk.accelerator_parse(binding)
    return Gtk.accelerator_get_label(key, mods) if key else binding
