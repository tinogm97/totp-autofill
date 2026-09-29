"""Graba las escenas de la demo en una sesión aislada (lo lanza run.sh).

Cada escena se graba aparte con ffmpeg (x11grab) mientras este script maneja
la app y un Google Chrome real como lo haría una persona: ratón que se
desplaza, tecleo a velocidad humana. Todas las cuentas y secretos son falsos.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from totp_autofill.store import Account, AccountStore, Settings  # noqa: E402
from totp_autofill.x11 import X11  # noqa: E402

OUT = Path(os.environ["DEMO_OUT"])
CHROME = os.environ["CHROME"]
PORT = 8765
DISPLAY = os.environ["DISPLAY"]
KEYSYMS = {"@": "at", ".": "period", ":": "colon", "/": "slash", "-": "minus"}
x11 = X11()
procs: list[subprocess.Popen] = []


def spawn(*args, **kw) -> subprocess.Popen:
    proc = subprocess.Popen(list(args), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kw)
    procs.append(proc)
    return proc


# -- ratón y teclado ----------------------------------------------------------

mouse = [640, 360]


def move(x: int, y: int, duration: float = 0.6) -> None:
    """Desplaza el ratón con aceleración suave, como una mano."""
    x0, y0 = mouse
    steps = max(8, int(duration * 60))
    for i in range(1, steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)
        x11._xtst.XTestFakeMotionEvent(x11.dpy, -1, int(x0 + (x - x0) * ease),
                                       int(y0 + (y - y0) * ease), 0)
        x11._x.XFlush(x11.dpy)
        time.sleep(duration / steps)
    mouse[:] = [x, y]


def click_at(x: int, y: int, duration: float = 0.6) -> None:
    move(x, y, duration)
    time.sleep(0.15)
    x11.click(x, y)
    time.sleep(0.25)


def type_text(text: str) -> None:
    for ch in text:
        x11.press(KEYSYMS.get(ch, ch))
        time.sleep(random.uniform(0.05, 0.11))


# -- accesibilidad ------------------------------------------------------------

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


def find_all(node, pred, depth=0, out=None):
    out = [] if out is None else out
    if node is None or depth > 60:
        return out
    try:
        if pred(node):
            out.append(node)
        for i in range(node.get_child_count()):
            find_all(node.get_child_at_index(i), pred, depth + 1, out)
    except Exception:  # noqa: BLE001
        pass
    return out


def apps(name_part: str):
    desktop = Atspi.get_desktop(0)
    return [a for i in range(desktop.get_child_count())
            if (a := desktop.get_child_at_index(i)) and name_part in (a.get_name() or "")]


def wait_for(pred, timeout=15.0, where="hrom"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for app in apps(where):
            if (node := find(app, pred)) is not None:
                return node
        time.sleep(0.2)
    raise TimeoutError("No aparece el elemento esperado")


def center(node) -> tuple[int, int]:
    r = node.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
    return r.x + r.width // 2, r.y + r.height // 2


def element(role: str, name: str, where="hrom", timeout=15.0):
    return wait_for(lambda n: n.get_role_name() == role and (n.get_name() or "").startswith(name),
                    timeout, where)


def page_title_starts(prefix: str, timeout=12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = wait_for(lambda n: n.get_role_name() == "document web")
        if (doc.get_name() or "").startswith(prefix):
            return True
        time.sleep(0.2)
    return False


# -- grabación ----------------------------------------------------------------

class Scene:
    def __init__(self, name: str) -> None:
        self.path = OUT / f"{name}.mp4"

    def __enter__(self):
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "1",
             "-framerate", "30", "-video_size", "1280x720", "-i", DISPLAY,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
             str(self.path)], stdin=subprocess.PIPE)
        time.sleep(0.6)
        return self

    def __exit__(self, *exc):
        time.sleep(0.4)
        self.proc.communicate(b"q", timeout=20)
        print(f"   grabada {self.path.name}", flush=True)
        return False


def open_url(url: str) -> None:
    """Abre la URL en la pestaña actual de Chrome (fuera de cámara)."""
    x11.press("F6")
    time.sleep(0.3)
    for ch in url:
        x11.press(KEYSYMS.get(ch, ch))
    x11.press("Return")
    element("entry", "Email")
    time.sleep(0.8)


def login(email: str) -> None:
    click_at(*center(element("entry", "Email")), 0.7)
    type_text(email)
    time.sleep(0.3)
    click_at(*center(element("push button", "Continuar")), 0.6)


# -- escenas ------------------------------------------------------------------

def main() -> int:
    store = AccountStore()
    secrets = ["JBSWY3DPEHPK3PXP", "GEZDGNBVGY3TQOJQ", "MFRGGZDFMZTWQ2LK", "KRUGS4ZANFZSAYJA"]
    store.save(Account("Portal dev", username="ana@empresa.com", sites=[f"localhost:{PORT}"],
                       auto_submit=True), secrets[0])
    # Sin envío automático: en la escena 3 se ve el código escrito en el campo.
    store.save(Account("Portal dev", username="admin@empresa.com", sites=[f"localhost:{PORT}"]),
               secrets[1])
    store.save(Account("VPN Empresa", username="t.garcia@empresa.com", auto_submit=True), secrets[2])
    store.save(Account("GitLab", username="tino"), secrets[3])
    Settings(auto_fill=True).save()

    spawn(sys.executable, "-m", "http.server", str(PORT), "--directory", str(ROOT / "examples"))
    spawn(sys.executable, str(HERE / "background.py"))
    time.sleep(1.5)
    spawn(sys.executable, "-m", "totp_autofill", "daemon", env={**os.environ, "PYTHONPATH": str(ROOT)})
    spawn(sys.executable, str(HERE / "demo_app.py"))
    time.sleep(3)

    print("1. La app", flush=True)
    move(900, 600, 0.1)
    with Scene("1-app"):
        time.sleep(0.8)
        move(620, 300, 1.2)
        time.sleep(0.8)
        move(760, 380, 0.9)
        time.sleep(1.4)

    print("2. Importar", flush=True)
    import_button = wait_for(
        lambda n: n.get_role_name() == "push button"
        and "Importar desde Google" in (n.get_description() or n.get_name() or ""), where="")
    with Scene("2-import"):
        time.sleep(0.5)
        click_at(*center(import_button), 0.8)
        time.sleep(1.0)
        click_at(*center(element("push button", "Escanear", where="")), 0.8)
        importar = element("push button", "Importar 4", where="", timeout=20)
        time.sleep(1.8)
        click_at(*center(importar), 0.9)
        ok = element("push button", "Aceptar", where="", timeout=8)
        time.sleep(2.4)  # que se lea el resumen
        click_at(*center(ok), 0.6)
        time.sleep(1.2)

    print("3. Automático", flush=True)
    profile = OUT / "chrome-profile"
    (profile / "Default").mkdir(parents=True, exist_ok=True)
    (profile / "Default" / "Preferences").write_text(
        '{"translate": {"enabled": false}, "intl": {"accept_languages": "es-ES,es"},'
        ' "browser": {"has_seen_welcome_page": true}}')
    chrome = spawn(CHROME, "--no-first-run", "--no-default-browser-check",
                   "--password-store=basic", "--lang=es-ES", "--force-renderer-accessibility",
                   "--disable-infobars", "--hide-crash-restore-bubble",
                   f"--user-data-dir={profile}", "--window-position=90,20",
                   "--window-size=1100,620", f"http://localhost:{PORT}/demo-2fa.html")
    element("entry", "Email", timeout=40)
    windows = x11.windows_of_pid(chrome.pid)
    if windows:
        x11.activate(windows[-1])
    time.sleep(1.5)
    with Scene("3-auto"):
        time.sleep(0.6)
        login("admin@empresa.com")
        code_field = element("entry", "Código")
        deadline = time.monotonic() + 10
        while len(Atspi.Text.get_text(code_field, 0, -1)) < 6 and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(1.6)  # el código, a la vista en el campo
        click_at(*center(element("push button", "Verificar")), 0.7)
        page_title_starts("Recibido")
        time.sleep(2.2)

    print("4. Selector", flush=True)
    open_url(f"127.0.0.1:{PORT}/demo-2fa.html")
    with Scene("4-picker"):
        time.sleep(0.6)
        login("t.garcia@empresa.com")
        time.sleep(2.4)  # el selector aparece, con la cuenta de ese email primero
        x11.press("Return")
        page_title_starts("Recibido")
        time.sleep(2.5)

    print("5. Atajo", flush=True)
    Settings(auto_fill=False).save()
    open_url(f"localhost:{PORT}/demo-2fa.html")
    with Scene("5-shortcut"):
        time.sleep(0.6)
        login("ana@empresa.com")
        time.sleep(1.4)
        spawn(sys.executable, str(HERE / "overlay.py"), "Ctrl + Alt + 2", "2.6")
        time.sleep(1.3)  # que la tecla se vea antes de que aparezca el código
        subprocess.run([sys.executable, "-m", "totp_autofill", "fill"],
                       env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=20)
        page_title_starts("Recibido")
        time.sleep(2.5)

    for proc in procs:
        proc.terminate()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
