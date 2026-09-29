"""Genera los iconos PNG de la extensión y de la app (requiere pycairo).

Uso: python3 scripts/make_icons.py
"""

import math
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parent.parent


def draw(size: int, target: Path) -> None:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    s = size

    # Fondo: cuadrado redondeado azul.
    r = s * 0.22
    ctx.new_sub_path()
    ctx.arc(s - r, r, r, -math.pi / 2, 0)
    ctx.arc(s - r, s - r, r, 0, math.pi / 2)
    ctx.arc(r, s - r, r, math.pi / 2, math.pi)
    ctx.arc(r, r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()
    grad = cairo.LinearGradient(0, 0, 0, s)
    grad.add_color_stop_rgb(0, 0.23, 0.51, 0.96)
    grad.add_color_stop_rgb(1, 0.11, 0.31, 0.85)
    ctx.set_source(grad)
    ctx.fill()

    # Arco de cuenta atrás (3/4 de círculo).
    ctx.set_source_rgba(1, 1, 1, 0.9)
    ctx.set_line_width(max(1.5, s * 0.07))
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.arc(s / 2, s / 2, s * 0.36, -math.pi / 2, math.pi)
    ctx.stroke()

    # Texto central.
    ctx.set_source_rgb(1, 1, 1)
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(s * 0.30)
    ext = ctx.text_extents("2FA")
    ctx.move_to(s / 2 - ext.width / 2 - ext.x_bearing, s / 2 - ext.height / 2 - ext.y_bearing)
    ctx.show_text("2FA")

    surface.write_to_png(str(target))


if __name__ == "__main__":
    for size in (16, 32, 48, 128):
        draw(size, ROOT / "extension" / "icons" / f"icon-{size}.png")
    draw(256, ROOT / "data" / "totp-autofill.png")
    print("Iconos generados.")
