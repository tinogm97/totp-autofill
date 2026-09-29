"""Interfaz de línea de comandos: ``totp-autofill <comando>``.

Sin argumentos abre la aplicación gráfica.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__


def _store():
    from .store import AccountStore

    return AccountStore()


def _find(store, name_or_id: str):
    accounts = store.load()
    for account in accounts:
        if account.id == name_or_id:
            return account
    key = name_or_id.lower()
    matches = [a for a in accounts if a.name.lower() == key] or \
              [a for a in accounts if a.username.lower() == key]
    if len(matches) != 1:
        sys.exit(f"No se encontró una única cuenta con nombre o usuario '{name_or_id}' "
                 "(usa el id que muestra 'list')")
    return matches[0]


def cmd_gui(_args) -> int:
    from .gui import run

    return run()


def cmd_daemon(args) -> int:
    import os

    from .daemon import run

    return run(debug=args.debug or bool(os.environ.get("TOTP_AUTOFILL_DEBUG")))


def cmd_fill(_args) -> int:
    from .daemon import fill_standalone, request_fill

    return 0 if request_fill() else fill_standalone()


def cmd_list(_args) -> int:
    accounts = _store().load()
    if not accounts:
        print("No hay cuentas configuradas.")
    for a in accounts:
        print(a.label)
        print(f"    sitios: {', '.join(a.sites) or '(se preguntará la primera vez)'}")
        if a.window_titles:
            print(f"    ventanas aprendidas: {len(a.window_titles)}")
        if a.auto_submit:
            print("    pulsa Intro tras escribir el código")
        print(f"    id={a.id}")
    return 0


def cmd_add(args) -> int:
    from .store import Account
    from .totp import parse_otpauth_uri

    secret, username = args.secret, args.user
    digits, period, algorithm = args.digits, args.period, args.algorithm
    if args.uri:
        info = parse_otpauth_uri(args.uri)
        secret, digits, period, algorithm = (
            info.secret, info.digits, info.period, info.algorithm)
        username = username or info.account
    if not secret:
        secret = getpass.getpass("Secreto Base32 (no se mostrará): ")

    account = Account(name=args.name, username=username, sites=args.site,
                      auto_submit=args.auto_submit, digits=digits, period=period,
                      algorithm=algorithm)
    _store().save(account, secret)
    print(f"Cuenta '{account.label}' guardada (id={account.id}).")
    return 0


def cmd_import(args) -> int:
    from . import qr
    from .migration import accounts_from_uris, find_uris, import_accounts, missing_batches

    uris: list[str] = []
    for source in args.sources:
        if source == "-":
            uris += find_uris(sys.stdin.read())
        elif source.lower().startswith("otpauth"):
            uris += find_uris(source)
        else:
            try:
                with open(source, encoding="utf-8") as fh:
                    uris += find_uris(fh.read())  # fichero de texto con enlaces
                continue
            except (UnicodeDecodeError, IsADirectoryError):
                pass
            found = qr.decode_file(source)  # imagen con QR
            if not found:
                print(f"Aviso: no se ve ningún QR en {source}", file=sys.stderr)
            for code in found:
                uris += find_uris(code)
    if not uris:
        print("No se encontró ninguna exportación ni enlace otpauth.", file=sys.stderr)
        return 1

    accounts, skipped, batches = accounts_from_uris(uris)
    for reason in skipped:
        print(f"No se importa: {reason}", file=sys.stderr)
    if missing := missing_batches(batches):
        print(f"Aviso: faltan los QR {', '.join(map(str, missing))} de la exportación.",
              file=sys.stderr)
    print(f"{len(accounts)} cuenta(s) encontradas:")
    for account in accounts:
        print(f"  {account.label}")
    if not args.yes and input("¿Importarlas? [s/N] ").strip().lower() not in ("s", "si", "sí", "y"):
        return 1
    result = import_accounts(_store(), accounts)
    print(f"Importadas: {len(result.imported)}. Ya las tenías: {len(result.existing)}.")
    for error in result.errors:
        print(f"Error: {error}", file=sys.stderr)
    print("Si hiciste fotos o capturas de los QR, bórralas: contienen tus secretos.")
    return 0 if not result.errors else 1


def cmd_code(args) -> int:
    store = _store()
    code, remaining = store.code(_find(store, args.account))
    print(code if args.quiet else f"{code}  (válido {remaining}s)")
    return 0


def cmd_delete(args) -> int:
    store = _store()
    account = _find(store, args.account)
    store.delete(account.id)
    print(f"Cuenta '{account.label}' eliminada.")
    return 0


def cmd_setup_chrome(args) -> int:
    from . import chrome_setup

    if args.undo:
        for path in chrome_setup.disable():
            print(f"Restaurado: {path}")
        return 0
    changed = chrome_setup.enable()
    for path in changed:
        print(f"Lanzador con accesibilidad: {path}")
    if not changed and not chrome_setup.is_enabled():
        print("No se encontró ningún navegador compatible instalado.", file=sys.stderr)
        return 1
    print("Cierra los navegadores por completo y vuelve a abrirlos para que tenga efecto.")
    if fix := chrome_setup.vpn_script_fix():
        print(f"\nPara el Chrome VPN (necesita sudo):\n  {fix}")
    return 0


def cmd_setup_shortcut(args) -> int:
    from . import keybinding
    from .store import Settings

    if args.remove:
        keybinding.uninstall()
        print("Atajo eliminado.")
        return 0
    settings = Settings.load()
    binding = args.binding or settings.shortcut
    keybinding.install(keybinding.fill_command(), binding)
    settings.shortcut = binding
    settings.save()
    print(f"Atajo {keybinding.label(binding)} → escribir el código 2FA.")
    return 0


def cmd_status(_args) -> int:
    from . import chrome_setup, keybinding
    from .daemon import is_running
    from .x11 import X11, X11Error

    ok = lambda b: "✔" if b else "✘"  # noqa: E731
    try:
        X11()
        x11 = True
    except X11Error:
        x11 = False
    print(f"{ok(x11)} Teclear en X11 (XTest)" + ("" if x11 else ": se usará el portapapeles"))

    running = is_running()
    print(f"{ok(running)} Proceso en segundo plano (totp-autofill daemon)")

    shortcut = keybinding.current()
    print(f"{ok(shortcut)} Atajo de teclado: {keybinding.label(shortcut) if shortcut else 'sin configurar'}")

    print(f"{ok(chrome_setup.is_enabled())} Lanzadores de los navegadores con accesibilidad")
    for proc in chrome_setup.running_browsers():
        where = f" ({proc.user_data_dir})" if proc.user_data_dir else ""
        print(f"   {ok(proc.accessible)} {proc.exe}{where}: "
              + ("modo automático disponible" if proc.accessible
                 else "sin accesibilidad (reinícialo desde el lanzador)"))
    if fix := chrome_setup.vpn_script_fix():
        print(f"   ✘ Chrome VPN sin accesibilidad. Arréglalo con:\n     {fix}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="totp-autofill",
        description="Escribe códigos 2FA (TOTP) en el campo donde estés.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="abrir la aplicación gráfica (por defecto)"
                   ).set_defaults(func=cmd_gui)
    daemon = sub.add_parser("daemon", help="proceso en segundo plano (se inicia con la sesión)")
    daemon.add_argument("--debug", action="store_true",
                        help="mostrar qué detecta y decide (nunca muestra códigos)")
    daemon.set_defaults(func=cmd_daemon)
    sub.add_parser("fill", help="escribir el código en el campo con el foco "
                                "(lo lanza el atajo de teclado)").set_defaults(func=cmd_fill)
    sub.add_parser("list", help="listar cuentas").set_defaults(func=cmd_list)

    add = sub.add_parser("add", help="añadir una cuenta")
    add.add_argument("name", help="nombre descriptivo")
    add.add_argument("-u", "--user", default="",
                     help="email o usuario (distingue varias cuentas del mismo sitio)")
    add.add_argument("-s", "--site", action="append", default=[],
                     help="sitio donde se usa, p. ej. localhost:4200 o *.empresa.com "
                          "(opcional y repetible; si falta, se pregunta y se aprende)")
    src = add.add_mutually_exclusive_group()
    src.add_argument("--secret", help="secreto Base32 (si no, se pide por teclado)")
    src.add_argument("--uri", help="URI otpauth://totp/... del código QR")
    add.add_argument("--auto-submit", action="store_true",
                     help="pulsar Intro tras escribir el código")
    add.add_argument("--digits", type=int, default=6)
    add.add_argument("--period", type=int, default=30)
    add.add_argument("--algorithm", default="SHA1",
                     choices=["SHA1", "SHA256", "SHA512"])
    add.set_defaults(func=cmd_add)

    imp = sub.add_parser(
        "import", help="importar desde Google Authenticator (imágenes de los QR o enlaces)",
        description="Importa cuentas desde la exportación de Google Authenticator "
                    "(⋮ → Transferir cuentas → Exportar). Acepta imágenes de los QR, "
                    "ficheros de texto y enlaces otpauth-migration:// u otpauth://; "
                    "'-' lee de la entrada estándar. Para usar la cámara, abre la app.")
    imp.add_argument("sources", nargs="+", metavar="FUENTE")
    imp.add_argument("-y", "--yes", action="store_true", help="no pedir confirmación")
    imp.set_defaults(func=cmd_import)

    code = sub.add_parser("code", help="mostrar el código actual de una cuenta")
    code.add_argument("account", help="nombre, usuario o id")
    code.add_argument("-q", "--quiet", action="store_true", help="solo el código")
    code.set_defaults(func=cmd_code)

    delete = sub.add_parser("delete", help="eliminar una cuenta")
    delete.add_argument("account", help="nombre, usuario o id")
    delete.set_defaults(func=cmd_delete)

    chrome = sub.add_parser("setup-chrome",
                            help="activar la accesibilidad en Chrome, Brave, Edge, Firefox… (modo automático)")
    chrome.add_argument("--undo", action="store_true", help="deshacer")
    chrome.set_defaults(func=cmd_setup_chrome)

    shortcut = sub.add_parser("setup-shortcut", help="configurar el atajo de teclado en GNOME")
    shortcut.add_argument("--binding", help="p. ej. '<Control><Alt>2' (por defecto)")
    shortcut.add_argument("--remove", action="store_true", help="quitar el atajo")
    shortcut.set_defaults(func=cmd_setup_shortcut)

    sub.add_parser("status", help="comprobar que todo está listo").set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", cmd_gui)
    try:
        return func(args)
    except (ValueError, LookupError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
