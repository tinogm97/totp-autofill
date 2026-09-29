"""Lectura de códigos QR con libzbar (ctypes), sin dependencias de Python.

En Ubuntu la librería viene en el paquete ``libzbar0`` (suele estar ya
instalada como dependencia de otras aplicaciones).
"""

from __future__ import annotations

import ctypes
from ctypes import c_char_p, c_int, c_uint, c_ulong, c_void_p

_FOURCC_Y800 = 0x30303859  # 'Y800': escala de grises, 1 byte por píxel
_ZBAR_QRCODE = 64
_ZBAR_CFG_ENABLE = 0
_lib = None


class QrUnavailable(RuntimeError):
    pass


def _zbar():
    global _lib
    if _lib is not None:
        return _lib
    try:
        lib = ctypes.cdll.LoadLibrary("libzbar.so.0")
    except OSError as exc:
        raise QrUnavailable(
            "Falta la librería para leer QR. Instálala con: sudo apt install libzbar0"
        ) from exc
    lib.zbar_image_scanner_create.restype = c_void_p
    lib.zbar_image_scanner_set_config.argtypes = [c_void_p, c_int, c_int, c_int]
    lib.zbar_image_scanner_destroy.argtypes = [c_void_p]
    lib.zbar_image_create.restype = c_void_p
    lib.zbar_image_set_format.argtypes = [c_void_p, c_ulong]
    lib.zbar_image_set_size.argtypes = [c_void_p, c_uint, c_uint]
    lib.zbar_image_set_data.argtypes = [c_void_p, c_void_p, c_ulong, c_void_p]
    lib.zbar_image_destroy.argtypes = [c_void_p]
    lib.zbar_scan_image.argtypes = [c_void_p, c_void_p]
    lib.zbar_image_first_symbol.restype = c_void_p
    lib.zbar_image_first_symbol.argtypes = [c_void_p]
    lib.zbar_symbol_next.restype = c_void_p
    lib.zbar_symbol_next.argtypes = [c_void_p]
    lib.zbar_symbol_get_data.restype = c_void_p
    lib.zbar_symbol_get_data.argtypes = [c_void_p]
    lib.zbar_symbol_get_data_length.restype = c_uint
    lib.zbar_symbol_get_data_length.argtypes = [c_void_p]
    _lib = lib
    return lib


def available() -> bool:
    try:
        _zbar()
        return True
    except QrUnavailable:
        return False


def decode_gray(width: int, height: int, pixels: bytes) -> list[str]:
    """Textos de los QR de una imagen en escala de grises (1 byte por píxel)."""
    lib = _zbar()
    if len(pixels) < width * height:
        raise ValueError("La imagen es más pequeña de lo que indican sus dimensiones")
    scanner = lib.zbar_image_scanner_create()
    image = lib.zbar_image_create()
    buffer = ctypes.create_string_buffer(bytes(pixels[: width * height]), width * height)
    try:
        lib.zbar_image_scanner_set_config(scanner, 0, _ZBAR_CFG_ENABLE, 0)  # todo off
        lib.zbar_image_scanner_set_config(scanner, _ZBAR_QRCODE, _ZBAR_CFG_ENABLE, 1)
        lib.zbar_image_set_format(image, _FOURCC_Y800)
        lib.zbar_image_set_size(image, width, height)
        lib.zbar_image_set_data(image, buffer, width * height, None)
        results = []
        if lib.zbar_scan_image(scanner, image) > 0:
            symbol = lib.zbar_image_first_symbol(image)
            while symbol:
                size = lib.zbar_symbol_get_data_length(symbol)
                data = ctypes.string_at(lib.zbar_symbol_get_data(symbol), size)
                results.append(data.decode("utf-8", "replace"))
                symbol = lib.zbar_symbol_next(symbol)
        return results
    finally:
        lib.zbar_image_destroy(image)
        lib.zbar_image_scanner_destroy(scanner)


def to_gray(pixbuf) -> tuple[int, int, bytes]:
    """Un ``GdkPixbuf`` (RGB/RGBA) a escala de grises.

    Se usa el canal verde: para leer un QR basta y, recortando con slices en
    vez de píxel a píxel, es muy rápido incluso con fotos grandes.
    """
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels, stride = pixbuf.get_n_channels(), pixbuf.get_rowstride()
    data = pixbuf.get_pixels()
    rows = (data[y * stride + 1: y * stride + width * channels: channels] for y in range(height))
    return width, height, b"".join(rows)


def decode_file(path: str, max_side: int = 1600) -> list[str]:
    """Lee los QR de una imagen (PNG, JPEG…). Las fotos grandes se reducen."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib

    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    except GLib.Error as exc:
        raise ValueError(f"No se puede abrir la imagen {path}: {exc.message}") from exc
    pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
    scale = min(1.0, max_side / max(pixbuf.get_width(), pixbuf.get_height()))
    if scale < 1.0:
        pixbuf = pixbuf.scale_simple(int(pixbuf.get_width() * scale),
                                     int(pixbuf.get_height() * scale),
                                     GdkPixbuf.InterpType.BILINEAR)
    return decode_gray(*to_gray(pixbuf))
