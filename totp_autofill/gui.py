"""Aplicación de escritorio (GTK 3) para gestionar las cuentas 2FA."""

from __future__ import annotations

import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from . import __version__, chrome_setup, keybinding  # noqa: E402
from .daemon import is_running, start_in_background  # noqa: E402
from .store import Account, AccountStore, Settings  # noqa: E402
from .totp import InvalidSecretError, parse_otpauth_uri  # noqa: E402

APP_TITLE = "TOTP Autofill"
APP_ID = "io.github.tinogm97.TotpAutofill"
# Nombre de programa y clase de ventana (WM_CLASS). Deben coincidir con
# StartupWMClass del .desktop para que el dock asocie la ventana a su icono.
PROGRAM_NAME = "totp-autofill"
ICONS_DIR = Path(__file__).parent / "icons"

CSS = b"""
.code { font-family: monospace; font-size: 22px; font-weight: bold; }
.dim { opacity: 0.65; }
.username { color: @theme_selected_bg_color; }
.statusbar { padding: 6px 12px; border-top: 1px solid alpha(currentColor, 0.15); }
"""


def _small(text: str) -> Gtk.Label:
    label = Gtk.Label(xalign=0, wrap=True, max_width_chars=64)
    label.set_markup(f"<small>{text}</small>")
    return label


class AccountDialog(Gtk.Dialog):
    """Formulario para crear o editar una cuenta."""

    def __init__(self, parent: Gtk.Window, account: Account | None = None) -> None:
        editing = account is not None
        super().__init__(title="Editar cuenta" if editing else "Nueva cuenta",
                         transient_for=parent, modal=True)
        self.account = account
        self.forget_titles = False
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                         "Guardar", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(520, -1)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=16)
        self.get_content_area().add(grid)

        self.name = Gtk.Entry(placeholder_text="Ej: VPN empresa", hexpand=True)
        self.username = Gtk.Entry(placeholder_text="Ej: tino@empresa.com",
                                  input_purpose=Gtk.InputPurpose.EMAIL)
        self.secret = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                                placeholder_text="Dejar vacío para no cambiarlo" if editing
                                else "Secreto Base32 o URI otpauth://totp/...")
        self.secret.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                            "view-reveal-symbolic")
        self.secret.connect("icon-press", self._toggle_secret)
        self.sites = Gtk.Entry(placeholder_text="Opcional. Ej: localhost:4200, *.empresa.com")
        self.auto_submit = Gtk.CheckButton(label="Pulsar Intro después de escribir el código")

        self.digits = Gtk.SpinButton.new_with_range(6, 8, 1)
        self.period = Gtk.SpinButton.new_with_range(15, 120, 15)
        self.algorithm = Gtk.ComboBoxText()
        for alg in ("SHA1", "SHA256", "SHA512"):
            self.algorithm.append(alg, alg)

        rows = [
            ("Nombre", self.name),
            ("Cuenta / email", self.username),
            ("Secreto", self.secret),
            ("Sitios", self.sites),
        ]
        for i, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
        row = len(rows)
        grid.attach(self.auto_submit, 1, row, 1, 1)
        grid.attach(_small(
            "El <b>secreto</b> es el texto que aparece bajo el QR al activar el 2FA "
            "(o la URI <i>otpauth://</i>). Los <b>sitios</b> son opcionales: si no "
            "los pones, la primera vez que uses la cuenta te preguntará y lo "
            "recordará. El <b>email</b> distingue varias cuentas del mismo sitio."),
            1, row + 1, 1, 1)
        row += 2

        acc = account or Account(name="")
        if acc.window_titles:
            titles = Gtk.Box(spacing=8)
            titles.add(_small(f"Recuerda {len(acc.window_titles)} ventana(s) donde la usaste."))
            forget = Gtk.Button(label="Olvidar")
            forget.connect("clicked", self._forget_titles, titles)
            titles.add(forget)
            grid.attach(titles, 1, row, 1, 1)
            row += 1

        advanced = Gtk.Expander(label="Opciones avanzadas")
        adv_grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_top=8)
        for i, (label, widget) in enumerate(
                [("Dígitos", self.digits), ("Periodo (s)", self.period),
                 ("Algoritmo", self.algorithm)]):
            adv_grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            adv_grid.attach(widget, 1, i, 1, 1)
        advanced.add(adv_grid)
        grid.attach(advanced, 1, row, 1, 1)

        self.name.set_text(acc.name)
        self.username.set_text(acc.username)
        self.sites.set_text(", ".join(acc.sites))
        self.auto_submit.set_active(acc.auto_submit)
        self.digits.set_value(acc.digits)
        self.period.set_value(acc.period)
        self.algorithm.set_active_id(acc.algorithm)
        self.show_all()

    def _toggle_secret(self, entry, *_args) -> None:
        entry.set_visibility(not entry.get_visibility())

    def _forget_titles(self, _button, box: Gtk.Box) -> None:
        self.forget_titles = True
        for child in box.get_children():
            box.remove(child)
        box.add(_small("Se olvidarán al guardar."))
        box.show_all()

    def result(self) -> tuple[Account, str | None]:
        """Construye la cuenta a partir del formulario. Puede lanzar ValueError."""
        secret = self.secret.get_text().strip() or None
        digits = int(self.digits.get_value())
        period = int(self.period.get_value())
        algorithm = self.algorithm.get_active_id()
        name = self.name.get_text().strip()
        username = self.username.get_text().strip()

        if secret and secret.lower().startswith("otpauth://"):
            info = parse_otpauth_uri(secret)
            secret, digits, period, algorithm = (
                info.secret, info.digits, info.period, info.algorithm)
            name = name or info.issuer or info.label
            username = username or info.account

        account = Account(
            name=name,
            username=username,
            sites=[s for s in self.sites.get_text().replace(";", ",").split(",") if s.strip()],
            window_titles=[] if self.forget_titles or self.account is None
            else list(self.account.window_titles),
            auto_submit=self.auto_submit.get_active(),
            digits=digits, period=period, algorithm=algorithm,
        )
        if self.account is not None:
            account.id = self.account.id
        return account, secret


class PreferencesDialog(Gtk.Dialog):
    """Modo automático, atajo de teclado y accesibilidad de los navegadores."""

    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(title="Preferencias", transient_for=parent, modal=True)
        self.add_buttons("Cerrar", Gtk.ResponseType.CLOSE)
        self.set_default_size(560, -1)
        self.settings = Settings.load()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
        self.get_content_area().add(box)

        # -- automático
        box.add(self._heading("Rellenado automático"))
        auto = Gtk.Switch(active=self.settings.auto_fill, valign=Gtk.Align.CENTER)
        auto.connect("notify::active", self._toggle_auto)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label="Escribir el código al entrar en un campo de código",
                                 xalign=0), True, True, 0)
        row.pack_end(auto, False, False, 0)
        box.add(row)
        box.add(_small("Necesita que el navegador exponga las páginas por accesibilidad "
                       "(ver abajo). Sin preguntar, solo escribe en sitios ya asociados a "
                       "una cuenta; en los demás te deja elegir la cuenta."))

        # -- atajo
        box.add(self._heading("Atajo de teclado"))
        row = Gtk.Box(spacing=8)
        self.binding = Gtk.Entry(text=keybinding.current() or self.settings.shortcut,
                                 placeholder_text="<Control><Alt>2", hexpand=True)
        apply = Gtk.Button(label="Aplicar")
        apply.connect("clicked", self._apply_shortcut)
        row.add(self.binding)
        row.add(apply)
        box.add(row)
        self.binding_status = _small("")
        box.add(self.binding_status)
        self._refresh_shortcut()

        # -- navegadores
        box.add(self._heading("Accesibilidad en Chrome / Chromium"))
        self.chrome_status = _small("")
        box.add(self.chrome_status)
        self.chrome_button = Gtk.Button(halign=Gtk.Align.START)
        self.chrome_button.connect("clicked", self._toggle_chrome)
        box.add(self.chrome_button)

        self.vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add(self.vpn_box)
        self._refresh_chrome()
        self.show_all()

    @staticmethod
    def _heading(text: str) -> Gtk.Label:
        label = Gtk.Label(xalign=0, margin_top=6)
        label.set_markup(f"<b>{text}</b>")
        return label

    def _toggle_auto(self, switch, _param) -> None:
        self.settings.auto_fill = switch.get_active()
        self.settings.save()

    def _refresh_shortcut(self) -> None:
        current = keybinding.current()
        if not keybinding.available():
            text = "No es GNOME: crea el atajo a mano con el comando <tt>totp-autofill fill</tt>."
        elif current:
            text = (f"Activo: <b>{GLib.markup_escape_text(keybinding.label(current))}</b> "
                    "escribe el código en el campo donde estés (en cualquier aplicación).")
        else:
            text = "Sin atajo configurado."
        self.binding_status.set_markup(f"<small>{text}</small>")

    def _apply_shortcut(self, _button) -> None:
        binding = self.binding.get_text().strip()
        try:
            keybinding.install(keybinding.fill_command(), binding)
        except (ValueError, RuntimeError) as exc:
            self.binding_status.set_markup(
                f"<small>⚠ {GLib.markup_escape_text(str(exc))}</small>")
            return
        self.settings.shortcut = binding
        self.settings.save()
        self._refresh_shortcut()

    def _refresh_chrome(self) -> None:
        enabled = chrome_setup.is_enabled()
        lines = [("✔ El lanzador de Chrome arranca con accesibilidad." if enabled else
                  "✘ Chrome arranca sin accesibilidad: el modo automático no funciona "
                  "(el atajo sí).")]
        for proc in chrome_setup.running_browsers():
            where = f" ({GLib.markup_escape_text(proc.user_data_dir)})" if proc.user_data_dir else ""
            if proc.accessible:
                lines.append(f"✔ {proc.exe}{where}: listo.")
            else:
                lines.append(f"⚠ {proc.exe}{where}: abierto sin accesibilidad; ciérralo del "
                             "todo y ábrelo otra vez.")
        self.chrome_status.set_markup("<small>" + "\n".join(lines) + "</small>")
        self.chrome_button.set_label("Desactivar en Chrome" if enabled else "Activar en Chrome")

        for child in self.vpn_box.get_children():
            self.vpn_box.remove(child)
        if fix := chrome_setup.vpn_script_fix():
            self.vpn_box.add(_small(
                "El <b>Chrome VPN</b> se lanza con su propio script "
                f"(<tt>{chrome_setup.VPN_SCRIPT}</tt>). Para activarle la accesibilidad, "
                "ejecuta en una terminal (pide tu contraseña):"))
            command = Gtk.Entry(text=fix, editable=False)
            copy = Gtk.Button(label="Copiar comando", halign=Gtk.Align.START)
            copy.connect("clicked", lambda *_: Gtk.Clipboard.get(
                Gdk.SELECTION_CLIPBOARD).set_text(fix, -1))
            self.vpn_box.add(command)
            self.vpn_box.add(copy)
        self.vpn_box.show_all()

    def _toggle_chrome(self, _button) -> None:
        if chrome_setup.is_enabled():
            chrome_setup.disable()
        else:
            chrome_setup.enable()
        self._refresh_chrome()


class AccountRow(Gtk.ListBoxRow):
    """Fila de la lista: nombre, sitios, código actual y acciones."""

    def __init__(self, window: "MainWindow", account: Account) -> None:
        super().__init__()
        self.account = account
        box = Gtk.Box(spacing=12, margin=10)
        self.add(box)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Box(spacing=8)
        title.add(Gtk.Label(label=account.name, attributes=_bold()))
        if account.username:
            user = Gtk.Label(label=account.username, ellipsize=Pango.EllipsizeMode.END)
            user.get_style_context().add_class("username")
            title.add(user)
        info.add(title)
        where = ", ".join(account.sites) or "Te preguntará dónde usarla la primera vez"
        if account.window_titles:
            where += f" · {len(account.window_titles)} ventana(s)"
        sites = Gtk.Label(label=where, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        sites.get_style_context().add_class("dim")
        info.add(sites)
        box.pack_start(info, True, True, 0)

        self.code = Gtk.Label(label="------")
        self.code.get_style_context().add_class("code")
        self.progress = Gtk.LevelBar(min_value=0, max_value=account.period,
                                     valign=Gtk.Align.CENTER, width_request=40)
        box.pack_start(self.code, False, False, 0)
        box.pack_start(self.progress, False, False, 0)

        for icon, tip, handler in (
            ("edit-copy-symbolic", "Copiar código", window.copy_code),
            ("document-edit-symbolic", "Editar", window.edit_account),
            ("user-trash-symbolic", "Eliminar", window.delete_account),
        ):
            button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            button.set_tooltip_text(tip)
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, h=handler: h(self.account))
            box.pack_start(button, False, False, 0)


def _bold() -> Pango.AttrList:
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
    return attrs


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, store: AccountStore) -> None:
        super().__init__(application=app, title=APP_TITLE)
        self.store = store
        self.set_default_size(680, 440)
        # id -> (contador TOTP, código o error de ese periodo)
        self._codes: dict[str, tuple[int, str | Exception]] = {}

        header = Gtk.HeaderBar(show_close_button=True, title=APP_TITLE,
                               subtitle="Códigos 2FA donde los necesites")
        add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add.set_tooltip_text("Añadir cuenta")
        add.connect("clicked", lambda _b: self.edit_account(None))
        header.pack_start(add)
        about = Gtk.Button.new_from_icon_name("help-about-symbolic", Gtk.IconSize.BUTTON)
        about.set_tooltip_text("Acerca de")
        about.connect("clicked", self._about)
        header.pack_end(about)
        prefs = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        prefs.set_tooltip_text("Preferencias")
        prefs.connect("clicked", self._preferences)
        header.pack_end(prefs)
        self.set_titlebar(header)

        self.stack = Gtk.Stack(vexpand=True)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.listbox)
        self.stack.add_named(scrolled, "list")

        empty = Gtk.Label(justify=Gtk.Justification.CENTER)
        empty.set_markup("<big>No hay cuentas</big>\n\nPulsa <b>+</b> y pega el secreto 2FA.\n"
                         "No hace falta indicar dónde se usa: te lo preguntará.")
        self.stack.add_named(empty, "empty")

        self.status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        status_box = Gtk.EventBox()
        status_box.add(self.status)
        status_box.get_style_context().add_class("statusbar")
        status_box.connect("button-press-event", lambda *_: self._preferences())

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layout.add(self.stack)
        layout.add(status_box)
        self.add(layout)

        self.reload()
        GLib.timeout_add_seconds(1, self._tick)
        GLib.timeout_add_seconds(5, self._refresh_status)

    # -- datos ---------------------------------------------------------

    def reload(self) -> None:
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        accounts = self.store.load()
        for account in accounts:
            self.listbox.add(AccountRow(self, account))
        self.listbox.show_all()
        self.stack.set_visible_child_name("list" if accounts else "empty")
        self._codes.clear()
        self._tick()
        self._refresh_status()

    def _refresh_status(self) -> bool:
        shortcut = keybinding.current()
        parts = [f"Atajo: <b>{GLib.markup_escape_text(keybinding.label(shortcut))}</b>"
                 if shortcut else "⚠ Sin atajo"]
        if not is_running():
            parts.append("⚠ Proceso en segundo plano parado")
        elif not Settings.load().auto_fill:
            parts.append("Automático: desactivado")
        elif any(p.accessible for p in chrome_setup.running_browsers()):
            parts.append("Automático: activo")
        elif chrome_setup.is_enabled():
            parts.append("Automático: reinicia Chrome para activarlo")
        else:
            parts.append("⚠ Automático: Chrome sin accesibilidad")
        self.status.set_markup("<small>" + "  ·  ".join(parts) +
                               "  ·  <u>Preferencias</u></small>")
        return True

    def _current_code(self, account: Account) -> str:
        """Código vigente. Se consulta el llavero una vez por periodo, también
        si falla, para no insistir cada segundo con un llavero bloqueado."""
        counter = int(time.time() // account.period)
        cached = self._codes.get(account.id)
        if cached and cached[0] == counter:
            result = cached[1]
        else:
            try:
                result, _ = self.store.code(account)
            except Exception as exc:  # noqa: BLE001 - llavero bloqueado, etc.
                result = exc
            self._codes[account.id] = (counter, result)
        if isinstance(result, Exception):
            raise result
        return result

    def _tick(self) -> bool:
        now = time.time()
        for row in self.listbox.get_children():
            acc = row.account
            try:
                row.code.set_text(self._current_code(acc))
            except Exception as exc:  # noqa: BLE001 - llavero bloqueado, etc.
                row.code.set_text("error")
                row.code.set_tooltip_text(str(exc))
            row.progress.set_value(acc.period - (now % acc.period))
        return True

    # -- acciones ------------------------------------------------------

    def copy_code(self, account: Account) -> None:
        try:
            code = self._current_code(account)
        except Exception as exc:  # noqa: BLE001
            self._error("No se pudo generar el código", str(exc))
            return
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(code, -1)

    def edit_account(self, account: Account | None) -> None:
        dialog = AccountDialog(self, account)
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                new_account, secret = dialog.result()
                self.store.save(new_account, secret)
            except (ValueError, InvalidSecretError) as exc:
                self._error("Datos no válidos", str(exc))
                continue
            break
        dialog.destroy()
        self.reload()

    def delete_account(self, account: Account) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"¿Eliminar la cuenta «{account.label}»?")
        dialog.format_secondary_text(
            "El secreto se borrará del llavero. Asegúrate de tenerlo también en tu "
            "móvil u otro autenticador para no perder el acceso.")
        if dialog.run() == Gtk.ResponseType.OK:
            self.store.delete(account.id)
            self.reload()
        dialog.destroy()

    def _preferences(self, *_args) -> None:
        dialog = PreferencesDialog(self)
        dialog.run()
        dialog.destroy()
        self._refresh_status()

    def _error(self, title: str, detail: str) -> None:
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def _about(self, _button) -> None:
        dialog = Gtk.AboutDialog(
            transient_for=self, modal=True, program_name=APP_TITLE,
            version=__version__, logo=_logo(),
            comments="Escribe tus códigos 2FA (TOTP) en el campo donde estés: "
                     "solo al entrar en él o con un atajo de teclado.",
            website="https://github.com/tinogm97/totp-autofill",
            license_type=Gtk.License.MIT_X11)
        dialog.run()
        dialog.destroy()


class App(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: MainWindow | None = None

    def do_activate(self) -> None:
        if self.window is None:
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            if not is_running():
                start_in_background(keybinding.command_path())
            self.window = MainWindow(self, AccountStore())
        self.window.show_all()
        self.window.present()


def _set_default_icon() -> None:
    """Icono de todas las ventanas, cargado del paquete.

    No se usa el tema de iconos porque su caché puede no incluir el icono
    recién instalado, y entonces GTK mostraría uno genérico.
    """
    pixbufs = [GdkPixbuf.Pixbuf.new_from_file(str(path))
               for size in (16, 24, 32, 48, 64, 128, 256)
               if (path := ICONS_DIR / f"{PROGRAM_NAME}-{size}.png").exists()]
    if pixbufs:
        Gtk.Window.set_default_icon_list(pixbufs)
    else:
        Gtk.Window.set_default_icon_name("dialog-password")


def _logo() -> GdkPixbuf.Pixbuf | None:
    path = ICONS_DIR / f"{PROGRAM_NAME}-128.png"
    return GdkPixbuf.Pixbuf.new_from_file(str(path)) if path.exists() else None


def run() -> int:
    GLib.set_prgname(PROGRAM_NAME)
    GLib.set_application_name(APP_TITLE)
    Gdk.set_program_class(PROGRAM_NAME)
    _set_default_icon()
    return App().run([])
