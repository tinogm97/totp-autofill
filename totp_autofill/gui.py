"""Aplicación de escritorio (GTK 3) para gestionar las cuentas 2FA."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .store import Account, AccountStore  # noqa: E402
from .totp import InvalidSecretError, parse_otpauth_uri  # noqa: E402

APP_TITLE = "TOTP Autofill"

CSS = b"""
.code { font-family: monospace; font-size: 22px; font-weight: bold; }
.pattern { opacity: 0.65; }
"""


class AccountDialog(Gtk.Dialog):
    """Formulario para crear o editar una cuenta."""

    def __init__(self, parent: Gtk.Window, account: Account | None = None) -> None:
        editing = account is not None
        super().__init__(title="Editar cuenta" if editing else "Nueva cuenta",
                         transient_for=parent, modal=True)
        self.account = account
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                         "Guardar", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(520, -1)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=16)
        self.get_content_area().add(grid)

        self.name = Gtk.Entry(placeholder_text="Ej: VPN empresa", hexpand=True)
        self.url = Gtk.Entry(placeholder_text="https://login.empresa.com/mfa*")
        self.secret = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                                placeholder_text="Dejar vacío para no cambiarlo" if editing
                                else "Secreto Base32 o URI otpauth://totp/...")
        self.secret.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                            "view-reveal-symbolic")
        self.secret.connect("icon-press", self._toggle_secret)
        self.selector = Gtk.Entry(placeholder_text="Opcional. Ej: input#otp")
        self.auto_submit = Gtk.CheckButton(label="Enviar el formulario automáticamente")

        self.digits = Gtk.SpinButton.new_with_range(6, 8, 1)
        self.period = Gtk.SpinButton.new_with_range(15, 120, 15)
        self.algorithm = Gtk.ComboBoxText()
        for alg in ("SHA1", "SHA256", "SHA512"):
            self.algorithm.append(alg, alg)

        rows = [
            ("Nombre", self.name),
            ("URL del formulario", self.url),
            ("Secreto", self.secret),
            ("Selector CSS", self.selector),
        ]
        for i, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
        grid.attach(self.auto_submit, 1, len(rows), 1, 1)

        hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        hint.set_markup(
            "<small>Usa <b>*</b> como comodín en la URL. El secreto es el texto que "
            "aparece bajo el QR al activar el 2FA (o la URI <i>otpauth://</i>). "
            "Si no indicas selector, el campo se detecta automáticamente.</small>")
        grid.attach(hint, 1, len(rows) + 1, 1, 1)

        advanced = Gtk.Expander(label="Opciones avanzadas")
        adv_grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_top=8)
        for i, (label, widget) in enumerate(
                [("Dígitos", self.digits), ("Periodo (s)", self.period),
                 ("Algoritmo", self.algorithm)]):
            adv_grid.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
            adv_grid.attach(widget, 1, i, 1, 1)
        advanced.add(adv_grid)
        grid.attach(advanced, 1, len(rows) + 2, 1, 1)

        acc = account or Account(name="", url_pattern="")
        self.name.set_text(acc.name)
        self.url.set_text(acc.url_pattern)
        self.selector.set_text(acc.selector)
        self.auto_submit.set_active(acc.auto_submit)
        self.digits.set_value(acc.digits)
        self.period.set_value(acc.period)
        self.algorithm.set_active_id(acc.algorithm)
        self.show_all()

    def _toggle_secret(self, entry, *_args) -> None:
        entry.set_visibility(not entry.get_visibility())

    def result(self) -> tuple[Account, str | None]:
        """Construye la cuenta a partir del formulario. Puede lanzar ValueError."""
        secret = self.secret.get_text().strip() or None
        digits = int(self.digits.get_value())
        period = int(self.period.get_value())
        algorithm = self.algorithm.get_active_id()
        name = self.name.get_text().strip()

        if secret and secret.lower().startswith("otpauth://"):
            info = parse_otpauth_uri(secret)
            secret, digits, period, algorithm = (
                info.secret, info.digits, info.period, info.algorithm)
            name = name or info.issuer or info.label

        account = Account(
            name=name,
            url_pattern=self.url.get_text().strip(),
            selector=self.selector.get_text().strip(),
            auto_submit=self.auto_submit.get_active(),
            digits=digits, period=period, algorithm=algorithm,
        )
        if self.account is not None:
            account.id = self.account.id
        return account, secret


class AccountRow(Gtk.ListBoxRow):
    """Fila de la lista: nombre, patrón, código actual y acciones."""

    def __init__(self, window: "MainWindow", account: Account) -> None:
        super().__init__()
        self.account = account
        box = Gtk.Box(spacing=12, margin=10)
        self.add(box)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        info.add(Gtk.Label(label=account.name, xalign=0,
                           attributes=_bold()))
        pattern = Gtk.Label(label=account.url_pattern, xalign=0,
                            ellipsize=Pango.EllipsizeMode.END)
        pattern.get_style_context().add_class("pattern")
        info.add(pattern)
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
        self.set_default_size(640, 420)
        self.set_icon_name(
            "totp-autofill" if Gtk.IconTheme.get_default().has_icon("totp-autofill")
            else "dialog-password")
        # id -> (contador TOTP, código o error de ese periodo)
        self._codes: dict[str, tuple[int, str | Exception]] = {}

        header = Gtk.HeaderBar(show_close_button=True, title=APP_TITLE,
                               subtitle="Autocompletado de códigos 2FA")
        add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add.set_tooltip_text("Añadir cuenta")
        add.connect("clicked", lambda _b: self.edit_account(None))
        header.pack_start(add)
        about = Gtk.Button.new_from_icon_name("help-about-symbolic", Gtk.IconSize.BUTTON)
        about.connect("clicked", self._about)
        header.pack_end(about)
        self.set_titlebar(header)

        self.stack = Gtk.Stack()
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.listbox)
        self.stack.add_named(scrolled, "list")

        empty = Gtk.Label(justify=Gtk.Justification.CENTER)
        empty.set_markup("<big>No hay cuentas</big>\n\nPulsa <b>+</b> para añadir la "
                         "primera: indica la URL del formulario\ny el secreto 2FA.")
        self.stack.add_named(empty, "empty")
        self.add(self.stack)

        self.reload()
        GLib.timeout_add_seconds(1, self._tick)

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
            text=f"¿Eliminar la cuenta «{account.name}»?")
        dialog.format_secondary_text(
            "El secreto se borrará del llavero. Asegúrate de tenerlo también en tu "
            "móvil u otro autenticador para no perder el acceso.")
        if dialog.run() == Gtk.ResponseType.OK:
            self.store.delete(account.id)
            self.reload()
        dialog.destroy()

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
            version=__version__, logo_icon_name=self.get_icon_name(),
            comments="Rellena automáticamente los códigos 2FA (TOTP) en los "
                     "formularios web que configures.",
            website="https://github.com/tinogm97/totp-autofill",
            license_type=Gtk.License.MIT_X11)
        dialog.run()
        dialog.destroy()


class App(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="io.github.tinogm97.TotpAutofill")
        self.window: MainWindow | None = None

    def do_activate(self) -> None:
        if self.window is None:
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.window = MainWindow(self, AccountStore())
        self.window.show_all()
        self.window.present()


def run() -> int:
    GLib.set_prgname("totp-autofill")  # coincide con StartupWMClass del .desktop
    return App().run([])
