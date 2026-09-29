"""Host de *Native Messaging* para la extensión del navegador.

El navegador lanza este proceso y se comunica por stdin/stdout con mensajes
JSON precedidos por su longitud (entero de 32 bits, orden de bytes nativo).

Mensajes admitidos (campo ``type``):

``ping``
    Comprueba la conexión. Respuesta: ``{"ok": true, "version": "..."}``.
``patterns``
    Patrones de URL y usuarios configurados (sin secretos). La extensión los
    usa como filtro previo para no consultar al host en cada página, y para
    reconocer qué usuario se está autenticando.
    Respuesta: ``{"ok": true, "patterns": ["https://.../mfa*"], "users": ["ana@x.com"]}``.
``match`` (``url``)
    Cuentas configuradas para esa URL, **sin secretos**.
    Respuesta: ``{"ok": true, "accounts": [{id, name, username, selector, autoSubmit, digits}]}``.
``code`` (``url``, ``id``)
    Código TOTP actual de la cuenta ``id``. Solo se entrega si el patrón de
    la cuenta encaja con ``url``, de modo que una página nunca puede obtener
    el código de una cuenta configurada para otra dirección.
    Respuesta: ``{"ok": true, "code": "123456", "remaining": 17}``.

Cualquier error se devuelve como ``{"ok": false, "error": "mensaje"}``.
"""

from __future__ import annotations

import json
import struct
import sys
from typing import BinaryIO

from . import __version__
from .store import AccountStore, url_matches

MAX_MESSAGE_BYTES = 1024 * 1024


def read_message(stream: BinaryIO) -> dict | None:
    """Lee un mensaje. Devuelve ``None`` cuando el navegador cierra stdin."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("=I", header)
    if length > MAX_MESSAGE_BYTES:
        raise ValueError(f"Mensaje demasiado grande ({length} bytes)")
    return json.loads(stream.read(length).decode("utf-8"))


def write_message(stream: BinaryIO, message: dict) -> None:
    data = json.dumps(message).encode("utf-8")
    stream.write(struct.pack("=I", len(data)))
    stream.write(data)
    stream.flush()


def handle(message: dict, store: AccountStore) -> dict:
    """Procesa un mensaje y devuelve la respuesta."""
    kind = message.get("type")
    url = str(message.get("url", ""))

    if kind == "ping":
        return {"ok": True, "version": __version__}

    if kind == "patterns":
        accounts = store.load()
        return {
            "ok": True,
            "patterns": [a.url_pattern for a in accounts],
            "users": sorted({a.username for a in accounts if a.username}),
        }

    if kind == "match":
        return {"ok": True, "accounts": [a.public_info() for a in store.match(url)]}

    if kind == "code":
        account = store.get(str(message.get("id", "")))
        if account is None:
            return {"ok": False, "error": "Cuenta no encontrada"}
        if not url_matches(account.url_pattern, url):
            return {"ok": False, "error": "La URL no corresponde a esta cuenta"}
        code, remaining = store.code(account)
        return {"ok": True, "code": code, "remaining": remaining}

    return {"ok": False, "error": f"Tipo de mensaje desconocido: {kind!r}"}


def main() -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    # Cualquier print accidental corrompería el protocolo: lo mandamos a stderr.
    sys.stdout = sys.stderr
    store = AccountStore()
    while True:
        try:
            message = read_message(stdin)
        except (ValueError, json.JSONDecodeError) as exc:
            write_message(stdout, {"ok": False, "error": f"Mensaje inválido: {exc}"})
            return 1
        if message is None:
            return 0
        try:
            response = handle(message, store)
        except Exception as exc:  # noqa: BLE001 - se informa al navegador
            response = {"ok": False, "error": str(exc)}
        write_message(stdout, response)
