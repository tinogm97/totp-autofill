"""Proceso en segundo plano: rellenado automático y atajo de teclado.

- **Automático** (necesita accesibilidad en el navegador): escucha los cambios
  de foco por AT-SPI. Al entrar en un campo que parece de código 2FA en una
  página cuyo sitio ya está asociado a una cuenta, teclea el código. Si el
  sitio no está asociado, pregunta la cuenta (y la recuerda).
- **Atajo** (acción ``fill``, la lanza ``totp-autofill fill``): escribe el
  código en el campo con el foco, en cualquier aplicación. Usa lo que sepa
  por accesibilidad y, si no, el título de la ventana.

Se ejecuta como ``Gtk.Application`` con el id ``DAEMON_ID``: así solo hay una
instancia y la acción ``fill`` queda publicada en D-Bus.
"""

from __future__ import annotations

import logging
import time

import gi

gi.require_version("Atspi", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Atspi, Gio, GLib, Gtk  # noqa: E402

from . import a11y  # noqa: E402
from .detect import is_user_field, otp_confidence  # noqa: E402
from .filler import Filler, connect_x11, notify  # noqa: E402
from .picker import Picker  # noqa: E402
from .resolver import Context, Resolution, resolve  # noqa: E402
from .store import AccountStore, Settings, clean_title  # noqa: E402

DAEMON_ID = "io.github.tinogm97.TotpAutofill.Daemon"
DAEMON_PATH = "/io/github/tinogm97/TotpAutofill/Daemon"
RECENT_USER_TTL = 10 * 60  # s que se recuerda el usuario escrito en un sitio
USERS_CACHE_TTL = 5  # s que se cachea la lista de usuarios configurados
MAX_AUTO_FILLS = 2  # por campo y 5 minutos: evita bucles si el código falla
FIELD_MEMORY = 5 * 60
DISMISS_TTL = 10 * 60  # s sin volver a preguntar en un sitio tras pulsar Esc

# Nunca se registran códigos ni secretos: solo qué se detecta y se decide.
log = logging.getLogger("totp_autofill")


def picker_hint(where: str, *, learn: bool) -> str:
    if not where:
        return ""
    return f"Para {where}. La recordaré." if learn else f"Para {where}."


class Daemon:
    def __init__(self, app: Gtk.Application) -> None:
        self.app = app
        self.store = AccountStore()
        self.x11 = connect_x11()
        self.filler = Filler(self.store, self.x11)
        self.last_entry: Atspi.Accessible | None = None
        self.recent_users: dict[str, tuple[str, float]] = {}  # host -> (usuario, hora)
        self.fills: dict[tuple[str, str], list[float]] = {}  # campo -> horas de relleno
        self.dismissed: dict[str, float] = {}  # host -> hora en que se pulsó Esc
        self.busy_until = 0.0
        self.picker: Picker | None = None
        self._users: tuple[float, set[str]] = (0.0, set())

        Atspi.init()
        self._listener = Atspi.EventListener.new(self._on_focus)
        self._listener.register("object:state-changed:focused")
        # Lo que se escribe en campos de usuario, para saber con qué cuenta se
        # entra. Se lee al teclear (al perder el foco, en una SPA, el campo ya
        # puede haber desaparecido).
        self._text_listener = Atspi.EventListener.new(self._on_text)
        self._text_listener.register("object:text-changed:insert")
        self._text_listener.register("object:text-changed:delete")

    def _configured_users(self) -> set[str]:
        when, users = self._users
        if time.monotonic() - when > USERS_CACHE_TTL:
            users = {a.username.lower() for a in self.store.load() if a.username}
            self._users = (time.monotonic(), users)
        return users

    def _on_text(self, event) -> None:
        acc = event.source
        # Nunca se leen contraseñas: solo campos que parecen de usuario/email.
        if a11y.role(acc) != "entry" or not is_user_field(a11y.field_info(acc)):
            return
        value = a11y.field_text(acc).strip()
        host = a11y.document_host(a11y.document_of(acc))
        if not host:
            return
        # Solo se recuerda si es el usuario de alguna cuenta configurada. Si
        # se escribe otro, se olvida el anterior: no hay que usar la cuenta
        # de un login previo con un usuario distinto.
        if value.lower() not in self._configured_users():
            if self.recent_users.pop(host, None):
                log.debug("usuario en %s: otro (se olvida el anterior)", host)
            return
        if self.recent_users.get(host, ("",))[0] != value:
            self.recent_users[host] = (value, time.monotonic())
            log.debug("usuario escrito en %s: %r", host, value)

    # -- utilidades ------------------------------------------------------

    def _busy(self, seconds: float = 1.5) -> None:
        """Ignora eventos de foco un momento: al teclear en cajas de un dígito
        el foco salta de caja en caja y no hay que volver a rellenar."""
        self.busy_until = max(self.busy_until, time.monotonic() + seconds)

    def _type(self, account, *, window: int = 0, entry=None, activate: bool = False) -> None:
        """Teclea el código solo si, justo antes, el foco sigue donde estaba:
        la misma ventana activa y, si se conoce, el mismo campo enfocado."""
        def guard() -> bool:
            if self.x11 and window and self.x11.active_window() != window:
                return False
            return entry is None or a11y.is_focused(entry)

        self._busy(6)  # cubre la espera al siguiente código y el tecleo

        def typed(_ok: bool) -> None:
            # Terminado el tecleo, basta con 1,5 s más (cajas de un dígito).
            self.busy_until = time.monotonic() + 1.5

        self.filler.fill(account, window=window if activate else 0, guard=guard,
                         on_done=typed)

    def _dismissed(self, host: str) -> bool:
        when = self.dismissed.get(host)
        return when is not None and time.monotonic() - when < DISMISS_TTL

    def _active_window(self) -> tuple[int, str, int]:
        if not self.x11:
            return 0, "", 0
        window = self.x11.active_window()
        return window, self.x11.window_title(window), self.x11.window_pid(window)

    def _recent_user(self, host: str) -> str:
        user, when = self.recent_users.get(host, ("", 0.0))
        return user if time.monotonic() - when < RECENT_USER_TTL else ""

    def _context(self, entry: Atspi.Accessible | None, title: str) -> tuple[Context, Atspi.Accessible | None]:
        doc = a11y.document_of(entry) if entry is not None else None
        host = a11y.document_host(doc)
        return Context(host=host, title=title, recent_user=self._recent_user(host)), doc

    def _resolve(self, ctx: Context, doc) -> Resolution:
        accounts = self.store.load()
        res = resolve(accounts, ctx)
        if res.account is None and doc is not None and len(res.candidates) > 1:
            ctx.page_text = a11y.page_text(doc)  # buscar el email en la página
            res = resolve(accounts, ctx)
        log.debug("contexto host=%r título=%r usuario=%r → %s (%s), %d candidatas",
                  ctx.host, ctx.title, ctx.recent_user,
                  res.account.label if res.account else "sin decidir", res.via or "-",
                  len(res.candidates))
        return res

    def _ask(self, res: Resolution, ctx: Context, *, window: int, entry=None,
             near=None, remember_host: bool) -> None:
        """Muestra el selector; al elegir, aprende la asociación y escribe."""
        if self.picker is not None:
            self.picker.present()
            return
        known_site = bool(ctx.host) and any(a.matches_host(ctx.host) for a in res.candidates)
        hint = picker_hint(ctx.host or clean_title(ctx.title), learn=not known_site)

        def done(account, explicit):
            self.picker = None
            log.debug("selector: %s", account.label if account else
                      "cancelado" if explicit else "cerrado sin elegir")
            if account is None:
                if explicit and remember_host and ctx.host:
                    self.dismissed[ctx.host] = time.monotonic()
                return
            self.store.learn(account.id, host=ctx.host, title="" if ctx.host else ctx.title)
            # El selector tenía el foco: se devuelve a la ventana original.
            self._type(account, window=window, entry=entry, activate=True)

        self.picker = Picker(res.candidates, done, hint=hint, near=near)

    # -- automático --------------------------------------------------------

    def _on_focus(self, event) -> None:
        acc = event.source
        if not a11y.is_entry(acc):
            return
        if event.detail1:  # ha ganado el foco
            self.last_entry = acc
            log.debug("foco en campo %s", a11y.field_info(acc))
            if time.monotonic() >= self.busy_until and Settings.load().auto_fill:
                GLib.timeout_add(150, self._maybe_autofill, acc)

    def _maybe_autofill(self, acc) -> bool:
        if time.monotonic() < self.busy_until or not a11y.is_focused(acc):
            return False
        info = a11y.field_info(acc)
        confidence = otp_confidence(info)
        if not confidence or a11y.field_text(acc):
            return False
        log.debug("campo de código (confianza %d)", confidence)
        doc = a11y.document_of(acc)
        url = a11y.document_url(doc) if doc is not None else ""
        if not url:
            return False
        key = (url.split("#")[0], info.html_id or info.html_name or info.label)
        now = time.monotonic()
        recent = [t for t in self.fills.get(key, []) if now - t < FIELD_MEMORY]
        if len(recent) >= MAX_AUTO_FILLS:
            log.debug("ya se rellenó %d veces este campo; no insisto", len(recent))
            return False

        window, title, pid = self._active_window()
        if self.x11 and pid != a11y.process_id(acc):
            # El foco es de una ventana de Chrome en segundo plano: no se
            # teclea en la aplicación que está delante.
            log.debug("el campo no es de la ventana activa; no se escribe")
            return False
        ctx, doc = self._context(acc, title)
        res = self._resolve(ctx, doc)
        if res.trusted:
            self.fills[key] = [*recent, now]
            self._type(res.account, window=window, entry=acc)
        elif confidence == 2 and res.candidates and ctx.host and not self._dismissed(ctx.host):
            self.fills[key] = [*recent, now]
            self._ask(res, ctx, window=window, entry=acc, near=a11y.extents(acc),
                      remember_host=True)
        return False

    # -- atajo de teclado ----------------------------------------------------

    def fill_focused(self) -> None:
        window, title, pid = self._active_window()
        log.debug("atajo: ventana %#x pid=%d", window, pid)
        entry = self.last_entry
        if entry is None or a11y.process_id(entry) != pid or not a11y.is_focused(entry):
            entry = None
        ctx, doc = self._context(entry, title)
        res = self._resolve(ctx, doc)
        if res.account is not None:
            if res.via == "only":
                self.store.learn(res.account.id, host=ctx.host,
                                 title="" if ctx.host else ctx.title)
            self._type(res.account, window=window, entry=entry)
        elif res.candidates:
            near = a11y.extents(entry) if entry is not None else None
            self._ask(res, ctx, window=window, entry=entry, near=near, remember_host=False)
        else:
            notify("No hay cuentas", "Añade una en la app TOTP Autofill.")


def run(debug: bool = False) -> int:
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s")
    GLib.set_prgname("totp-autofill")
    app = Gtk.Application(application_id=DAEMON_ID,
                          flags=Gio.ApplicationFlags.FLAGS_NONE)
    state: dict[str, Daemon] = {}

    def startup(_app):
        state["daemon"] = Daemon(app)
        action = Gio.SimpleAction.new("fill", None)
        action.connect("activate", lambda *_: state["daemon"].fill_focused())
        app.add_action(action)
        app.hold()  # sin ventanas: que no se cierre

    app.connect("startup", startup)
    app.connect("activate", lambda _app: None)
    return app.run([])


def is_running() -> bool:
    """¿Está el daemon en marcha en esta sesión?"""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "NameHasOwner",
                              GLib.Variant("(s)", (DAEMON_ID,)), None,
                              Gio.DBusCallFlags.NONE, 2000, None)
        return bool(owner.unpack()[0])
    except GLib.Error:
        return False


def start_in_background(command: str) -> None:
    """Lanza ``command daemon`` desligado de este proceso."""
    import subprocess

    subprocess.Popen([command, "daemon"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def request_fill() -> bool:
    """Pide al daemon que rellene. ``False`` si no está en marcha."""
    if not is_running():
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(DAEMON_ID, DAEMON_PATH, "org.gtk.Actions", "Activate",
                      GLib.Variant("(sava{sv})", ("fill", [], {})), None,
                      Gio.DBusCallFlags.NONE, 2000, None)
        return True
    except GLib.Error:
        return False


def fill_standalone() -> int:
    """Atajo sin daemon: decide por el título de la ventana y pregunta si duda."""
    Gtk.init([])
    store = AccountStore()
    x11 = connect_x11()
    filler = Filler(store, x11)
    window = x11.active_window() if x11 else 0
    title = x11.window_title(window) if x11 else ""
    ctx = Context(title=title)
    res = resolve(store.load(), ctx)
    loop = GLib.MainLoop()
    # Sin X11 el código va al portapapeles: el proceso debe seguir vivo un
    # rato para que se pueda pegar si no hay gestor de portapapeles.
    linger_ms = 100 if x11 else 30_000
    finish = lambda *_: GLib.timeout_add(linger_ms, loop.quit)  # noqa: E731
    same_window = lambda: not x11 or x11.active_window() == window  # noqa: E731

    if res.account is not None:
        if res.via == "only":
            store.learn(res.account.id, title=title)
        filler.fill(res.account, on_done=finish, guard=same_window)
    elif res.candidates:
        def done(account, _explicit):
            if account is None:
                finish()
                return
            store.learn(account.id, title=title)
            filler.fill(account, window=window, on_done=finish, guard=same_window)

        Picker(res.candidates, done, hint=picker_hint(clean_title(title), learn=True))
    else:
        notify("No hay cuentas", "Añade una en la app TOTP Autofill.")
        return 1
    loop.run()
    return 0
