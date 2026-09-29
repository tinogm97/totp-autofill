"""Tecla en pantalla («Ctrl + Alt + 2») sin robar el foco: ventana POPUP."""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

CSS = b"""
.keys { background: rgba(20, 24, 34, 0.92); border-radius: 14px; padding: 14px 22px; }
.key { background: #f4f5f7; color: #1f2430; border-radius: 8px; padding: 6px 16px;
       font: bold 26px Ubuntu; box-shadow: 0 3px 0 #a9afbd; }
.plus { color: #cfd6e6; font: bold 24px Ubuntu; padding: 0 8px; }
"""
provider = Gtk.CssProvider()
provider.load_from_data(CSS)
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, 800)
window = Gtk.Window(type=Gtk.WindowType.POPUP)
box = Gtk.Box(spacing=0)
box.get_style_context().add_class("keys")
for i, key in enumerate(sys.argv[1].split("+")):
    if i:
        plus = Gtk.Label(label="+")
        plus.get_style_context().add_class("plus")
        box.add(plus)
    label = Gtk.Label(label=key.strip())
    label.get_style_context().add_class("key")
    box.add(label)
window.add(box)
window.show_all()
width, _ = window.get_size()
window.move((1280 - width) // 2, 540)
GLib.timeout_add(int(float(sys.argv[2]) * 1000), Gtk.main_quit)
Gtk.main()
