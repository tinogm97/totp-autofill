"""Acceso mínimo a X11 con ctypes: ventana activa y pulsaciones con XTest.

Solo funciona en sesiones X11 (en Wayland las apps no pueden simular
teclas ni ver otras ventanas; ahí se usa el portapapeles como alternativa).
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import (CFUNCTYPE, POINTER, Structure, byref, c_int, c_long, c_uint, c_ulong,
                    c_void_p)

_ANY_PROPERTY_TYPE = 0
_SUBSTRUCTURE_MASK = (1 << 19) | (1 << 20)  # SubstructureNotify | Redirect
_CLIENT_MESSAGE = 33
_MODIFIERS = ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
              "Meta_L", "Meta_R", "Super_L", "Super_R", "ISO_Level3_Shift")


class _ClientMessage(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int),
                ("display", c_void_p), ("window", c_ulong), ("message_type", c_ulong),
                ("format", c_int), ("data", c_long * 5),
                ("_pad", c_long * 24)]  # XEvent ocupa 24 longs


class X11Error(RuntimeError):
    pass


# Por defecto, Xlib termina el proceso (exit) ante cualquier error del
# protocolo, p. ej. BadWindow si una ventana se cierra justo al consultarla.
# Este manejador lo ignora; las funciones devuelven valores vacíos.
_ERROR_HANDLER_TYPE = CFUNCTYPE(c_int, c_void_p, c_void_p)
_ignore_errors = _ERROR_HANDLER_TYPE(lambda _display, _event: 0)


class X11:
    """Conexión a la pantalla X. Lanza ``X11Error`` si no está disponible."""

    def __init__(self) -> None:
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" and not os.environ.get("DISPLAY"):
            raise X11Error("Sesión Wayland sin X11")
        try:
            self._x = ctypes.cdll.LoadLibrary("libX11.so.6")
            self._xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
        except OSError as exc:
            raise X11Error(f"Faltan librerías X11: {exc}") from exc
        x = self._x
        x.XOpenDisplay.restype = c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = c_ulong
        x.XDefaultRootWindow.argtypes = [c_void_p]
        x.XInternAtom.restype = c_ulong
        x.XInternAtom.argtypes = [c_void_p, ctypes.c_char_p, c_int]
        x.XGetWindowProperty.argtypes = [
            c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong,
            POINTER(c_ulong), POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong),
            POINTER(ctypes.POINTER(ctypes.c_ubyte))]
        x.XFree.argtypes = [c_void_p]
        x.XStringToKeysym.restype = c_ulong
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [c_void_p, c_ulong]
        x.XKeycodeToKeysym.restype = c_ulong
        x.XKeycodeToKeysym.argtypes = [c_void_p, c_uint, c_int]  # KeyCode ancho
        x.XQueryKeymap.argtypes = [c_void_p, ctypes.c_char * 32]
        x.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, c_void_p]
        x.XFlush.argtypes = [c_void_p]
        x.XGetInputFocus.argtypes = [c_void_p, POINTER(c_ulong), POINTER(c_int)]
        x.XSetInputFocus.argtypes = [c_void_p, c_ulong, c_int, c_ulong]
        x.XRaiseWindow.argtypes = [c_void_p, c_ulong]
        x.XQueryTree.argtypes = [c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong),
                                 POINTER(POINTER(c_ulong)), POINTER(c_uint)]
        self._xtst.XTestFakeKeyEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
        self._xtst.XTestFakeMotionEvent.argtypes = [c_void_p, c_int, c_int, c_int, c_ulong]
        self._xtst.XTestFakeButtonEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
        self._xtst.XTestQueryExtension.argtypes = [c_void_p] + [POINTER(c_int)] * 4

        x.XSetErrorHandler.argtypes = [_ERROR_HANDLER_TYPE]
        x.XSetErrorHandler(_ignore_errors)
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise X11Error("No se puede abrir la pantalla X (¿DISPLAY?)")
        dummy = [c_int() for _ in range(4)]
        if not self._xtst.XTestQueryExtension(self.dpy, *map(byref, dummy)):
            raise X11Error("El servidor X no tiene la extensión XTest")
        self.root = x.XDefaultRootWindow(self.dpy)

    # -- propiedades de ventanas -------------------------------------------

    def _atom(self, name: str) -> int:
        return self._x.XInternAtom(self.dpy, name.encode(), 0)

    def _property(self, window: int, name: str) -> bytes | None:
        actual_type, actual_format = c_ulong(), c_int()
        nitems, after = c_ulong(), c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        status = self._x.XGetWindowProperty(
            self.dpy, window, self._atom(name), 0, 1024, 0, _ANY_PROPERTY_TYPE,
            byref(actual_type), byref(actual_format), byref(nitems), byref(after),
            byref(data))
        if status != 0 or not data:
            return None
        try:
            size = nitems.value * (8 if actual_format.value == 32 else actual_format.value // 8)
            return ctypes.string_at(data, size)
        finally:
            self._x.XFree(data)

    def has_window_manager(self) -> bool:
        """¿Hay un gestor de ventanas EWMH (GNOME, KDE, XFCE...)?"""
        return bool(self._property(self.root, "_NET_SUPPORTING_WM_CHECK"))

    def active_window(self) -> int:
        raw = self._property(self.root, "_NET_ACTIVE_WINDOW")
        window = int.from_bytes(raw[:8], "little") if raw else 0
        if window:
            return window
        # Sin gestor de ventanas: la ventana con el foco del teclado.
        focus, revert = c_ulong(), c_int()
        self._x.XGetInputFocus(self.dpy, byref(focus), byref(revert))
        return focus.value if focus.value > 1 else 0  # 0/1 = None/PointerRoot

    def window_title(self, window: int) -> str:
        raw = self._property(window, "_NET_WM_NAME") or self._property(window, "WM_NAME")
        return raw.decode("utf-8", "replace") if raw else ""

    def window_pid(self, window: int) -> int:
        raw = self._property(window, "_NET_WM_PID")
        return int.from_bytes(raw[:8], "little") if raw else 0

    def windows_of_pid(self, pid: int) -> list[int]:
        """Ventanas de primer nivel que declaran ``_NET_WM_PID == pid``."""
        root, parent = c_ulong(), c_ulong()
        children, count = POINTER(c_ulong)(), c_uint()
        if not self._x.XQueryTree(self.dpy, self.root, byref(root), byref(parent),
                                  byref(children), byref(count)):
            return []
        try:
            windows = [children[i] for i in range(count.value)]
        finally:
            if children:
                self._x.XFree(children)
        return [w for w in windows if self.window_pid(w) == pid]

    def activate(self, window: int) -> None:
        """Pide al gestor de ventanas que active ``window`` (EWMH)."""
        if not self.has_window_manager():
            self._x.XRaiseWindow(self.dpy, window)
            self._x.XSetInputFocus(self.dpy, window, 2, 0)  # RevertToParent, CurrentTime
            self._x.XFlush(self.dpy)
            return
        ev = _ClientMessage()
        ev.type = _CLIENT_MESSAGE
        ev.send_event = 1
        ev.display = self.dpy
        ev.window = window
        ev.message_type = self._atom("_NET_ACTIVE_WINDOW")
        ev.format = 32
        ev.data[0] = 2  # petición de un "pager": el WM la acepta siempre
        self._x.XSendEvent(self.dpy, self.root, 0, _SUBSTRUCTURE_MASK, byref(ev))
        self._x.XFlush(self.dpy)

    # -- teclado -------------------------------------------------------------

    def _keycode(self, keysym_name: str) -> tuple[int, bool]:
        """Keycode de una tecla y si necesita Mayúsculas (p. ej. AZERTY)."""
        keysym = self._x.XStringToKeysym(keysym_name.encode())
        keycode = self._x.XKeysymToKeycode(self.dpy, keysym)
        if not keysym or not keycode:
            raise X11Error(f"La distribución de teclado no tiene la tecla {keysym_name!r}")
        shifted = (self._x.XKeycodeToKeysym(self.dpy, keycode, 0) != keysym and
                   self._x.XKeycodeToKeysym(self.dpy, keycode, 1) == keysym)
        return keycode, shifted

    def _fake(self, keycode: int, down: bool) -> None:
        self._xtst.XTestFakeKeyEvent(self.dpy, keycode, 1 if down else 0, 0)

    def wait_modifiers_released(self, timeout: float = 3.0) -> None:
        """Espera a que se suelten Ctrl/Alt/Mayús (del atajo que nos lanzó).

        Si se tecleara con Ctrl+Alt aún pulsadas, cada dígito sería otro atajo.
        """
        codes = []
        for name in _MODIFIERS:
            keysym = self._x.XStringToKeysym(name.encode())
            if keysym and (code := self._x.XKeysymToKeycode(self.dpy, keysym)):
                codes.append(code)
        keys = (ctypes.c_char * 32)()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._x.XQueryKeymap(self.dpy, keys)
            pressed = bytes(keys)
            if not any(pressed[c // 8] & (1 << (c % 8)) for c in codes):
                return
            time.sleep(0.02)

    def press(self, keysym_name: str) -> None:
        keycode, shifted = self._keycode(keysym_name)
        shift = self._keycode("Shift_L")[0] if shifted else 0
        if shift:
            self._fake(shift, True)
        self._fake(keycode, True)
        self._fake(keycode, False)
        if shift:
            self._fake(shift, False)
        self._x.XFlush(self.dpy)

    def click(self, x: int, y: int) -> None:
        """Clic izquierdo en coordenadas de pantalla."""
        self._xtst.XTestFakeMotionEvent(self.dpy, -1, x, y, 0)
        self._xtst.XTestFakeButtonEvent(self.dpy, 1, 1, 0)
        self._xtst.XTestFakeButtonEvent(self.dpy, 1, 0, 0)
        self._x.XFlush(self.dpy)

    def type_digits(self, digits: str, delay: float = 0.02) -> None:
        for ch in digits:
            if not ch.isdigit():
                raise ValueError("Solo se teclean dígitos")
            self.press(ch)
            time.sleep(delay)
