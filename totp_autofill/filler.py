"""Escribe el código en el campo que tiene el foco.

En X11 se teclea con XTest, como si fuera el teclado. En Wayland (sin XTest)
se copia al portapapeles y se avisa con una notificación.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .store import Account, AccountStore  # noqa: E402
from .x11 import X11, X11Error  # noqa: E402

log = logging.getLogger("totp_autofill")
MIN_VALIDITY = 3  # segundos: si al código le quedan menos, se espera al siguiente


def notify(title: str, body: str = "") -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "TOTP Autofill", "-i", "totp-autofill",
                          title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def connect_x11() -> X11 | None:
    try:
        return X11()
    except X11Error:
        return None


class Filler:
    def __init__(self, store: AccountStore, x11: X11 | None) -> None:
        self.store = store
        self.x11 = x11

    def fill(self, account: Account, *, window: int = 0,
             on_done=lambda ok: None, guard=None) -> None:
        """Escribe el código de ``account``. Si ``window``, la activa antes.

        ``guard()`` se evalúa justo antes de teclear (tras las esperas): si
        devuelve ``False`` no se teclea, p. ej. porque el usuario ha cambiado
        de ventana mientras tanto. No bloquea: las esperas van por GLib.
        """
        try:
            _code, remaining = self.store.code(account)
        except LookupError as exc:
            notify("No se pudo generar el código", str(exc))
            on_done(False)
            return
        delay_ms = int((remaining + 0.3) * 1000) if remaining < MIN_VALIDITY else 0
        if window and self.x11:
            self.x11.activate(window)
            delay_ms = max(delay_ms, 250)  # que el gestor de ventanas le dé el foco
        GLib.timeout_add(delay_ms, self._type, account, on_done, guard)

    def _type(self, account: Account, on_done, guard) -> bool:
        code, _ = self.store.code(account)
        if self.x11 is None:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(code, -1)
            clipboard.store()
            notify(f"Código de {account.label} copiado", "Pégalo con Ctrl+V.")
            on_done(True)
            return False
        self.x11.wait_modifiers_released()
        if guard is not None and not guard():
            log.debug("el foco ha cambiado antes de teclear: no se escribe nada")
            on_done(False)
            return False
        log.debug("tecleando el código de %s%s", account.label,
                  " + Intro" if account.auto_submit else "")
        self.x11.type_digits(code)
        if account.auto_submit:
            time.sleep(0.15)
            self.x11.press("Return")
        on_done(True)
        return False
