"""Lectura de páginas web mediante accesibilidad (AT-SPI).

Chrome/Chromium solo exponen el contenido de las páginas por AT-SPI si
arrancan con ``--force-renderer-accessibility`` (ver ``chrome_setup``).
Nunca se escribe por aquí: Chrome no lo permite, así que el código se
teclea con XTest (``x11``).
"""

from __future__ import annotations

import time
import warnings

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

from .detect import FieldInfo  # noqa: E402
from .store import host_of  # noqa: E402

ENTRY_ROLES = {"entry", "password text", "spin button"}
TEXT_LIMIT = 20_000  # caracteres de la página que se leen, como mucho
NODE_LIMIT = 3_000
# Firefox rellena su caché de accesibilidad bajo demanda: la primera consulta
# de atributos o posición de un campo devuelve vacío y la siguiente, ya bien.
LAZY_RETRIES = 3
LAZY_DELAY_S = 0.15


def bus_available() -> bool:
    """¿Se puede conectar al bus de accesibilidad?

    Hay que comprobarlo antes de ``Atspi.init()``: si el bus no responde, la
    librería aborta el proceso entero en vez de devolver un error.
    """
    from gi.repository import Gio, GLib

    try:
        session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        address = session.call_sync(
            "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress", None,
            GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        connection = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        connection.close_sync(None)
        return True
    except GLib.Error:
        return False


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - el objeto puede desaparecer en cualquier momento
        return default


def role(acc: Atspi.Accessible) -> str:
    return _safe(acc.get_role_name, "") or ""


def is_entry(acc: Atspi.Accessible) -> bool:
    return role(acc) in ENTRY_ROLES


def _retry(fetch, valid):
    """Repite ``fetch`` si el resultado no es válido (caché perezosa de Firefox)."""
    result = fetch()
    for _ in range(LAZY_RETRIES):
        if valid(result):
            break
        time.sleep(LAZY_DELAY_S)
        result = fetch()
    return result


def field_info(acc: Atspi.Accessible) -> FieldInfo:
    attrs = _retry(lambda: _safe(acc.get_attributes, {}) or {}, bool)
    return FieldInfo.from_atspi(_safe(acc.get_name, "") or "", attrs)


def group_size(acc: Atspi.Accessible) -> int:
    """Campos de texto hermanos (mismo contenedor), incluido este."""
    parent = _safe(acc.get_parent)
    if parent is None:
        return 0
    count = _safe(parent.get_child_count, 0) or 0
    if count > 20:
        return 0
    children = (_safe(lambda i=i: parent.get_child_at_index(i)) for i in range(count))
    return sum(1 for child in children if child is not None and role(child) == "entry")


def field_text(acc: Atspi.Accessible) -> str:
    return _safe(lambda: Atspi.Text.get_text(acc, 0, -1), "") or ""


def process_id(acc: Atspi.Accessible) -> int:
    return _safe(acc.get_process_id, 0) or 0


def is_focused(acc: Atspi.Accessible) -> bool:
    return bool(_safe(lambda: acc.get_state_set().contains(Atspi.StateType.FOCUSED)))


def document_of(acc: Atspi.Accessible) -> Atspi.Accessible | None:
    """Documento web que contiene ``acc`` (o ``None`` si no está en una web)."""
    node = acc
    for _ in range(80):
        if node is None:
            return None
        if role(node) == "document web":
            return node
        node = _safe(node.get_parent)
    return None


def document_url(doc: Atspi.Accessible) -> str:
    """URL de la página. Chrome la da en ``URI``; Firefox solo responde a la
    consulta de un atributo suelto (``DocURL``), no a la de todos a la vez."""
    attrs = _safe(lambda: Atspi.Document.get_document_attributes(doc), {}) or {}
    url = attrs.get("URI") or attrs.get("DocURL")
    if not url:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            url = _safe(lambda: Atspi.Document.get_document_attribute_value(doc, "DocURL"))
    return url or ""


def document_host(doc: Atspi.Accessible | None) -> str:
    return host_of(document_url(doc)) if doc is not None else ""


def page_text(doc: Atspi.Accessible) -> str:
    """Texto visible de la página (y valores de los campos), para buscar emails."""
    parts: list[str] = []
    size = 0
    stack = [doc]
    visited = 0
    while stack and visited < NODE_LIMIT and size < TEXT_LIMIT:
        node = stack.pop()
        visited += 1
        name = _safe(node.get_name, "") or ""
        # Solo campos de texto normales: nunca "password text".
        text = field_text(node) if role(node) == "entry" else ""
        for chunk in (name, text):
            if chunk:
                parts.append(chunk)
                size += len(chunk)
        count = _safe(node.get_child_count, 0) or 0
        stack.extend(c for c in (_safe(lambda i=i: node.get_child_at_index(i))
                                 for i in reversed(range(count))) if c is not None)
    return "\n".join(parts)


def extents(acc: Atspi.Accessible) -> tuple[int, int, int, int] | None:
    """Posición del objeto en pantalla: ``(x, y, ancho, alto)``."""
    rect = _retry(
        lambda: _safe(lambda: acc.get_component_iface().get_extents(Atspi.CoordType.SCREEN)),
        lambda r: r is not None and r.width > 0 and r.height > 0)
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return None  # sin posición: el selector se abre junto al ratón
    return (rect.x, rect.y, rect.width, rect.height)


def chrome_exposes_pages() -> list[str]:
    """Nombres de las apps de navegador que están exponiendo páginas web."""
    desktop = Atspi.get_desktop(0)
    names = []
    for i in range(_safe(desktop.get_child_count, 0) or 0):
        app = _safe(lambda i=i: desktop.get_child_at_index(i))
        if app is None:
            continue
        name = _safe(app.get_name, "") or ""
        if not any(b in name.lower() for b in ("chrome", "chromium", "brave", "edge", "vivaldi", "firefox")):
            continue
        if _find_role(app, "document web", depth=12):
            names.append(name)
    return names


def _find_role(acc: Atspi.Accessible, wanted: str, depth: int) -> bool:
    if depth < 0 or acc is None:
        return False
    if role(acc) == wanted:
        return True
    count = _safe(acc.get_child_count, 0) or 0
    return any(_find_role(_safe(lambda i=i: acc.get_child_at_index(i)), wanted, depth - 1)
               for i in range(min(count, 30)))
