"""Fondo de escritorio de la demo: degradado a pantalla completa (1280x720)."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import cairo  # noqa: E402
from gi.repository import Gdk, Gtk  # noqa: E402


def draw(_widget, ctx):
    grad = cairo.LinearGradient(0, 0, 1280, 720)
    grad.add_color_stop_rgb(0, 0.12, 0.16, 0.30)
    grad.add_color_stop_rgb(1, 0.05, 0.07, 0.14)
    ctx.set_source(grad)
    ctx.paint()


window = Gtk.Window(title="fondo")
window.set_default_size(1280, 720)
window.move(0, 0)
area = Gtk.DrawingArea()
area.connect("draw", draw)
window.add(area)
window.connect("destroy", Gtk.main_quit)
window.show_all()
# Sin gestor de ventanas el puntero por defecto es una «X»: flecha normal.
display = Gdk.Display.get_default()
Gdk.get_default_root_window().set_cursor(Gdk.Cursor.new_from_name(display, "default"))
window.get_window().set_cursor(Gdk.Cursor.new_from_name(display, "default"))
Gtk.main()
