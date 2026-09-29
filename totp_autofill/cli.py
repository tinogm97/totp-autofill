"""Interfaz de línea de comandos: ``totp-autofill <comando>``.

Sin argumentos abre la aplicación gráfica.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import __version__


def _store():
    from .store import AccountStore

    return AccountStore()


def _find(store, name_or_id: str):
    accounts = store.load()
    for account in accounts:
        if account.id == name_or_id:
            return account
    matches = [a for a in accounts if a.name.lower() == name_or_id.lower()]
    if len(matches) != 1:
        sys.exit(f"No se encontró una única cuenta llamada '{name_or_id}'")
    return matches[0]


def cmd_gui(_args) -> int:
    from .gui import run

    return run()


def cmd_host(_args) -> int:
    from .native_host import main

    return main()


def cmd_list(_args) -> int:
    store = _store()
    accounts = store.load()
    if not accounts:
        print("No hay cuentas configuradas.")
    for a in accounts:
        extra = f"  selector={a.selector}" if a.selector else ""
        auto = "  [auto-envío]" if a.auto_submit else ""
        print(f"{a.name}\n    {a.url_pattern}{extra}{auto}\n    id={a.id}")
    return 0


def cmd_add(args) -> int:
    from .store import Account
    from .totp import parse_otpauth_uri

    secret = args.secret
    digits, period, algorithm = args.digits, args.period, args.algorithm
    if args.uri:
        info = parse_otpauth_uri(args.uri)
        secret, digits, period, algorithm = (
            info.secret, info.digits, info.period, info.algorithm)
    if not secret:
        secret = getpass.getpass("Secreto Base32 (no se mostrará): ")

    account = Account(name=args.name, url_pattern=args.url, selector=args.selector,
                      auto_submit=args.auto_submit, digits=digits, period=period,
                      algorithm=algorithm)
    _store().save(account, secret)
    print(f"Cuenta '{account.name}' guardada (id={account.id}).")
    return 0


def cmd_code(args) -> int:
    store = _store()
    code, remaining = store.code(_find(store, args.account))
    print(code if args.quiet else f"{code}  (válido {remaining}s)")
    return 0


def cmd_delete(args) -> int:
    store = _store()
    account = _find(store, args.account)
    store.delete(account.id)
    print(f"Cuenta '{account.name}' eliminada.")
    return 0


def cmd_install_browser(args) -> int:
    from .browser_integration import install

    written = install(Path(args.host_path), args.extension_id)
    if not written:
        print("No se detectó ningún navegador compatible.", file=sys.stderr)
        return 1
    for path in written:
        print(f"Registrado: {path}")
    return 0


def cmd_uninstall_browser(_args) -> int:
    from .browser_integration import uninstall

    for path in uninstall():
        print(f"Eliminado: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="totp-autofill",
        description="Autocompletado de códigos 2FA (TOTP) en formularios web.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="abrir la aplicación gráfica (por defecto)"
                   ).set_defaults(func=cmd_gui)
    sub.add_parser("host", help="modo Native Messaging (lo lanza el navegador)"
                   ).set_defaults(func=cmd_host)
    sub.add_parser("list", help="listar cuentas").set_defaults(func=cmd_list)

    add = sub.add_parser("add", help="añadir una cuenta")
    add.add_argument("name", help="nombre descriptivo")
    add.add_argument("url", help="patrón de URL del formulario, admite *")
    src = add.add_mutually_exclusive_group()
    src.add_argument("--secret", help="secreto Base32 (si no, se pide por teclado)")
    src.add_argument("--uri", help="URI otpauth://totp/... del código QR")
    add.add_argument("--selector", default="", help="selector CSS del campo")
    add.add_argument("--auto-submit", action="store_true",
                     help="enviar el formulario tras rellenar")
    add.add_argument("--digits", type=int, default=6)
    add.add_argument("--period", type=int, default=30)
    add.add_argument("--algorithm", default="SHA1",
                     choices=["SHA1", "SHA256", "SHA512"])
    add.set_defaults(func=cmd_add)

    code = sub.add_parser("code", help="mostrar el código actual de una cuenta")
    code.add_argument("account", help="nombre o id")
    code.add_argument("-q", "--quiet", action="store_true", help="solo el código")
    code.set_defaults(func=cmd_code)

    delete = sub.add_parser("delete", help="eliminar una cuenta")
    delete.add_argument("account", help="nombre o id")
    delete.set_defaults(func=cmd_delete)

    inst = sub.add_parser("install-browser",
                          help="registrar el host nativo en los navegadores")
    inst.add_argument("--host-path", required=True,
                      help="ruta absoluta al ejecutable totp-autofill-host")
    inst.add_argument("--extension-id", action="append", default=[],
                      help="ID adicional de extensión Chromium permitido")
    inst.set_defaults(func=cmd_install_browser)

    sub.add_parser("uninstall-browser", help="eliminar el registro del host nativo"
                   ).set_defaults(func=cmd_uninstall_browser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", cmd_gui)
    try:
        return func(args)
    except (ValueError, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
