"""Test end-to-end sin extensión: Chromium real + daemon real + teclado simulado.

Lo lanza ``tests/e2e/run.sh`` dentro de una sesión aislada (Xvfb, D-Bus y
bus de accesibilidad propios), así que no toca el escritorio. Los secretos
van a un fichero temporal, nunca al llavero real.
Maneja la página demo como una persona: clic en los campos y tecleo.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from totp_autofill.store import AccountStore, Settings  # noqa: E402
from totp_autofill.totp import seconds_remaining, totp  # noqa: E402
from totp_autofill.x11 import X11  # noqa: E402

CHROME = os.environ["CHROME"]
PORT = 8765
DEMO = f"http://localhost:{PORT}/demo-2fa.html"
S_ANA, S_LUIS, S_OTRA = "JBSWY3DPEHPK3PXP", "GEZDGNBVGY3TQOJQ", "MFRGGZDFMZTWQ2LK"
KEYSYMS = {"@": "at", ".": "period", "-": "minus", "_": "underscore"}

WORK = Path(tempfile.mkdtemp(prefix="totp-e2e-"))
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "XDG_CONFIG_HOME": str(WORK / "config"),
       "TOTP_AUTOFILL_TEST_SECRETS": str(WORK / "secrets.json"), "TOTP_AUTOFILL_TESTING": "1"}
os.environ.update({k: ENV[k] for k in ("XDG_CONFIG_HOME", "TOTP_AUTOFILL_TEST_SECRETS",
                                       "TOTP_AUTOFILL_TESTING")})
x11 = X11()
results: list[tuple[str, bool, str]] = []


def cli(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "totp_autofill", *args], env=ENV,
                          capture_output=True, text=True, check=kw.pop("check", True), **kw)


# -- accesibilidad ----------------------------------------------------------

def find(node, pred, depth=0):
    if node is None or depth > 60:
        return None
    try:
        if pred(node):
            return node
        for i in range(node.get_child_count()):
            if (found := find(node.get_child_at_index(i), pred, depth + 1)) is not None:
                return found
    except Exception:  # noqa: BLE001
        return None
    return None


def document(timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None or "hrom" not in (app.get_name() or ""):
                continue
            doc = find(app, lambda n: n.get_role_name() == "document web")
            if doc is not None:
                return doc
        time.sleep(0.3)
    raise TimeoutError("Chromium no expone la página por accesibilidad")


def element(role: str, name: str, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        node = find(document(), lambda n: n.get_role_name() == role
                    and (n.get_name() or "").startswith(name))
        if node is not None:
            return node
        time.sleep(0.2)
    raise TimeoutError(f"No aparece {role} {name!r}")


def click(node) -> None:
    rect = node.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
    x11.click(rect.x + rect.width // 2, rect.y + rect.height // 2)
    time.sleep(0.4)


def type_text(text: str) -> None:
    for ch in text:
        x11.press(KEYSYMS.get(ch, ch))
        time.sleep(0.02)


def received(timeout=12.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        name = document().get_name() or ""
        if name.startswith("Recibido "):
            return name.split(" ", 1)[1]
        time.sleep(0.2)
    return "(nada)"


# -- escenarios -------------------------------------------------------------

class Browser:
    def __init__(self, query: str = "") -> None:
        profile = WORK / "profile"
        # Sin la burbuja de "¿Traducir?": roba el foco del teclado a la página.
        (profile / "Default").mkdir(parents=True, exist_ok=True)
        prefs = profile / "Default" / "Preferences"
        if not prefs.exists():
            prefs.write_text('{"translate": {"enabled": false}, '
                             '"intl": {"accept_languages": "es-ES,es"}}')
        self.proc = subprocess.Popen(
            [CHROME, "--no-sandbox", "--no-first-run", "--no-default-browser-check",
             "--password-store=basic", "--lang=es-ES",
             "--force-renderer-accessibility", f"--user-data-dir={profile}",
             "--window-position=0,0", "--window-size=1200,850", DEMO + query],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        element("entry", "Email", timeout=25)
        # En Xvfb no hay gestor de ventanas que dé el foco al hacer clic, y
        # Chrome solo emite eventos de foco si su ventana lo tiene.
        windows = x11.windows_of_pid(self.proc.pid)
        if windows:
            x11.activate(windows[-1])
            time.sleep(0.3)

    def login(self, email: str) -> None:
        click(element("entry", "Email"))
        type_text(email)
        click(element("push button", "Continuar"))

    def close(self) -> None:
        self.proc.terminate()
        self.proc.wait(10)
        time.sleep(0.5)


def expect(label: str, secret: str, got: str) -> None:
    want = totp(secret)
    ok = got == want
    results.append((label, ok, f"recibido={got} esperado={want}"))
    print(f"{'OK   ' if ok else 'FALLO'} {label}: recibido={got} esperado={want}", flush=True)


def wait_fresh_code() -> None:
    """Evita cruzar un cambio de periodo entre teclear y comprobar."""
    if seconds_remaining() < 8:
        time.sleep(seconds_remaining() + 0.5)


def scenario(label: str, query: str, email: str, secret: str, *, then=None) -> None:
    wait_fresh_code()
    browser = Browser(query)
    try:
        browser.login(email)
        if then:
            then()
        expect(label, secret, received())
    except Exception as exc:  # noqa: BLE001
        results.append((label, False, str(exc)))
        print(f"FALLO {label}: {exc}", flush=True)
    finally:
        browser.close()


def choose_second_in_picker() -> None:
    time.sleep(1.5)  # que aparezca el selector
    x11.press("Down")
    x11.press("Return")


def run_fill() -> None:
    time.sleep(1.0)
    cli("fill", timeout=20)


def run_fill_and_choose_second() -> None:
    time.sleep(1.0)
    proc = subprocess.Popen([sys.executable, "-m", "totp_autofill", "fill"], env=ENV)
    choose_second_in_picker()
    proc.wait(20)


def main() -> int:
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT),
                               "--directory", str(ROOT / "examples")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    daemon = None
    try:
        cli("add", "Demo", "--user", "ana@demo.com", "--site", f"localhost:{PORT}",
            "--secret", S_ANA, "--auto-submit")
        cli("add", "Demo", "--user", "luis@demo.com", "--site", f"localhost:{PORT}",
            "--secret", S_LUIS, "--auto-submit")
        daemon = subprocess.Popen([sys.executable, "-m", "totp_autofill", "daemon"], env=ENV)
        time.sleep(2)

        print("== Modo automático (accesibilidad)", flush=True)
        scenario("mismo sitio, entra luis → código de Luis", "", "luis@demo.com", S_LUIS)
        scenario("6 cajas, entra ana → código de Ana", "?split=1", "ana@demo.com", S_ANA)
        scenario("multipágina, entra luis → código de Luis", "?multipage=1", "luis@demo.com", S_LUIS)
        scenario("email desconocido → selector → 2ª cuenta (Luis)", "", "otro@demo.com", S_LUIS,
                 then=choose_second_in_picker)

        print("== Atajo de teclado", flush=True)
        Settings(auto_fill=False).save()
        scenario("atajo con daemon, entra ana → código de Ana", "", "ana@demo.com", S_ANA,
                 then=run_fill)

        daemon.terminate()
        daemon.wait(10)
        daemon = None
        store = AccountStore()
        for account in store.load():
            store.delete(account.id)
        cli("add", "Uno", "--secret", S_ANA, "--auto-submit")
        cli("add", "Otra", "--secret", S_OTRA, "--auto-submit")
        scenario("atajo sin daemon ni sitio → selector → 2ª cuenta (Otra)", "", "x@demo.com",
                 S_OTRA, then=run_fill_and_choose_second)
        learned = [a.window_titles for a in AccountStore().load() if a.name == "Otra"][0]
        print(f"   ventana aprendida: {learned}", flush=True)
        scenario("atajo sin daemon, ventana ya aprendida → Otra sin preguntar", "", "x@demo.com",
                 S_OTRA, then=run_fill)
    finally:
        if daemon:
            daemon.terminate()
        server.terminate()
        store = AccountStore()
        for account in store.load():
            store.delete(account.id)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} escenarios correctos")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
