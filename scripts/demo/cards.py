"""Rótulos de inicio y final de la demo (PNG 1280x720)."""
import sys
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "totp_autofill" / "icons" / "totp-autofill-256.png"
W, H = 1280, 720


def background(ctx):
    grad = cairo.LinearGradient(0, 0, W, H)
    grad.add_color_stop_rgb(0, 0.12, 0.16, 0.30)
    grad.add_color_stop_rgb(1, 0.05, 0.07, 0.14)
    ctx.set_source(grad)
    ctx.paint()


def text(ctx, s, y, size, weight=cairo.FONT_WEIGHT_NORMAL, rgb=(1, 1, 1), family="Ubuntu"):
    ctx.select_font_face(family, cairo.FONT_SLANT_NORMAL, weight)
    ctx.set_font_size(size)
    ext = ctx.text_extents(s)
    ctx.move_to((W - ext.width) / 2 - ext.x_bearing, y)
    ctx.set_source_rgb(*rgb)
    ctx.show_text(s)
    return ext


def icon(ctx, size, y):
    img = cairo.ImageSurface.create_from_png(str(ICON))
    ctx.save()
    ctx.translate((W - size) / 2, y)
    ctx.scale(size / img.get_width(), size / img.get_height())
    ctx.set_source_surface(img, 0, 0)
    ctx.paint()
    ctx.restore()


def intro(path):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    background(ctx)
    icon(ctx, 150, 150)
    text(ctx, "TOTP Autofill", 390, 64, cairo.FONT_WEIGHT_BOLD)
    text(ctx, "Tus códigos 2FA, escritos solos en Ubuntu", 450, 30, rgb=(0.78, 0.84, 0.95))
    text(ctx, "Sin extensiones  ·  Sin configurar URLs  ·  Código abierto", 510, 22,
         rgb=(0.55, 0.62, 0.76))
    s.write_to_png(path)


def outro(path):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    background(ctx)
    icon(ctx, 110, 110)
    text(ctx, "Instálalo con un solo comando", 290, 40, cairo.FONT_WEIGHT_BOLD)
    cmd = "curl -fsSL https://raw.githubusercontent.com/tinogm97/totp-autofill/main/get.sh | bash"
    ctx.select_font_face("Ubuntu Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(21)
    ext = ctx.text_extents(cmd)
    x0, y0 = (W - ext.width) / 2 - 24, 335
    ctx.set_source_rgba(0, 0, 0, 0.45)
    ctx.rectangle(x0, y0, ext.width + 48, 58)
    ctx.fill()
    text(ctx, cmd, y0 + 37, 21, rgb=(0.62, 0.95, 0.72), family="Ubuntu Mono")
    text(ctx, "github.com/tinogm97/totp-autofill", 480, 34, cairo.FONT_WEIGHT_BOLD,
         rgb=(0.78, 0.84, 0.95))
    text(ctx, "Licencia MIT  ·  Ubuntu 22.04 / 24.04  ·  Chrome, Chromium y cualquier app",
         540, 21, rgb=(0.55, 0.62, 0.76))
    s.write_to_png(path)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    intro(str(out / "intro.png"))
    outro(str(out / "outro.png"))
