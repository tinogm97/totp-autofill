"""Ventanita para elegir la cuenta cuando no se puede decidir sola."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .store import Account  # noqa: E402

CSS = b"""
.totp-picker { border: 1px solid alpha(currentColor, 0.25); }
.totp-picker .title { font-weight: bold; }
.totp-picker .hint { opacity: 0.7; font-size: small; }
.totp-picker .user { opacity: 0.75; font-size: small; }
"""
_css_loaded = False


class Picker(Gtk.Window):
    """Lista de cuentas. Intro o clic eligen; Esc o perder el foco cancelan.

    ``on_done(account, explicit)`` recibe la cuenta elegida, o ``None`` si se
    cancela; ``explicit`` es ``True`` si el usuario pulsó Esc (y no si solo
    perdió el foco o caducó).
    """

    TIMEOUT_S = 60  # se cierra solo si nadie lo usa (p. ej. si nunca obtuvo el foco)

    def __init__(self, accounts: list[Account], on_done: Callable[[Account | None], None],
                 *, hint: str = "", near: tuple[int, int, int, int] | None = None) -> None:
        super().__init__(title="TOTP Autofill", decorated=False, resizable=False,
                         skip_taskbar_hint=True, skip_pager_hint=True,
                         type_hint=Gdk.WindowTypeHint.DIALOG)
        _load_css()
        self.get_style_context().add_class("totp-picker")
        self.set_keep_above(True)
        self._on_done = on_done
        self._done = False
        self._accounts = accounts

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        self.add(box)
        title = Gtk.Label(label="¿Qué cuenta uso?", xalign=0)
        title.get_style_context().add_class("title")
        box.add(title)
        if hint:
            label = Gtk.Label(label=hint, xalign=0,
                              ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=40)
            label.get_style_context().add_class("hint")
            box.add(label)

        self.search = Gtk.SearchEntry(placeholder_text="Buscar…")
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.search.connect("activate", lambda *_: self._choose_selected())
        if len(accounts) > 5:
            box.add(self.search)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE)
        self.listbox.set_filter_func(self._filter)
        self.listbox.connect("row-activated", lambda _l, row: self._finish(row.account))
        for account in accounts:
            row = Gtk.ListBoxRow()
            row.account = account
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
            inner.add(Gtk.Label(label=account.name, xalign=0))
            if account.username:
                user = Gtk.Label(label=account.username, xalign=0)
                user.get_style_context().add_class("user")
                inner.add(user)
            row.add(inner)
            self.listbox.add(row)
        scrolled = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=360,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.add(self.listbox)
        box.add(scrolled)
        keys = Gtk.Label(label="Intro: usar · Esc: cancelar", xalign=0)
        keys.get_style_context().add_class("hint")
        box.add(keys)

        self.connect("key-press-event", self._on_key)
        self.connect("focus-out-event", lambda *_: self._finish(None))
        GLib.timeout_add_seconds(self.TIMEOUT_S, lambda: self._finish(None))
        self.set_size_request(300, -1)
        self.show_all()
        self.listbox.select_row(self.listbox.get_row_at_index(0))
        self._place(near)
        self.present_with_time(Gdk.CURRENT_TIME)
        (self.search if len(accounts) > 5 else self.listbox.get_row_at_index(0)).grab_focus()

    def _filter(self, row: Gtk.ListBoxRow) -> bool:
        query = self.search.get_text().lower()
        return not query or query in row.account.label.lower()

    def _place(self, near: tuple[int, int, int, int] | None) -> None:
        if near:
            x, y, _w, h = near
            self.move(x, y + h + 6)
        else:
            self.set_position(Gtk.WindowPosition.MOUSE)

    def _on_key(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self._finish(None, explicit=True)
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not self.search.has_focus():
            self._choose_selected()
            return True
        return False

    def _choose_selected(self) -> None:
        row = self.listbox.get_selected_row()
        visible = [r for r in self.listbox.get_children() if r.get_child_visible()]
        if row is None or not row.get_child_visible():
            row = visible[0] if visible else None
        if row is not None:
            self._finish(row.account)

    def _finish(self, account: Account | None, explicit: bool = False) -> bool:
        if self._done:
            return False
        self._done = True
        self.hide()
        self._on_done(account, explicit)
        self.destroy()
        return False


def _load_css() -> None:
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True
