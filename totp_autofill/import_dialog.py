"""Ventana de importación desde Google Authenticator.

Fuentes: la webcam (Android no deja hacer capturas de la pantalla de
exportación), imágenes con los QR y texto con enlaces ``otpauth-migration://``
u ``otpauth://``. Antes de importar se muestran las cuentas con casillas.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import qr  # noqa: E402
from .migration import (  # noqa: E402
    ImportedAccount, accounts_from_uris, find_uris, import_accounts, missing_batches,
)
from .store import AccountStore  # noqa: E402

HELP = ("En el móvil, abre <b>Google Authenticator</b> → menú <b>⋮</b> → "
        "<b>Transferir cuentas</b> → <b>Exportar</b>, elige las cuentas y enseña los QR "
        "a la cámara (si salen varios, uno detrás de otro). También puedes abrir "
        "fotos o capturas de esos QR.")


def _markup(label: Gtk.Label, text: str) -> Gtk.Label:
    label.set_markup(text)
    return label


class ImportDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, store: AccountStore) -> None:
        super().__init__(title="Importar desde Google Authenticator",
                         transient_for=parent, modal=True)
        self.store = store
        self.uris: list[str] = []
        self.scanner = None
        self.checks: list[tuple[Gtk.CheckButton, ImportedAccount]] = []
        self.known_secrets = {s.upper() for a in store.load()
                              if (s := store.secrets.get(a.id))}
        self.set_default_size(640, 720)
        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.import_button = self.add_button("Importar", Gtk.ResponseType.OK)
        self.import_button.get_style_context().add_class("suggested-action")
        self.import_button.set_sensitive(False)
        self.connect("destroy", lambda *_: self._stop_camera())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14)
        self.get_content_area().pack_start(box, True, True, 0)
        box.add(_markup(Gtk.Label(xalign=0, wrap=True, max_width_chars=70), HELP))

        # -- cámara
        cam_row = Gtk.Box(spacing=8)
        self.camera_combo = Gtk.ComboBoxText()
        self.cameras = []
        self.camera_button = Gtk.Button(label="Escanear con la cámara")
        self.camera_button.connect("clicked", self._toggle_camera)
        cam_row.pack_start(self.camera_combo, True, True, 0)
        cam_row.add(self.camera_button)
        box.add(cam_row)
        self.viewer = Gtk.Box(height_request=0)
        box.add(self.viewer)

        # -- imágenes y texto
        row = Gtk.Box(spacing=8)
        images = Gtk.Button(label="Abrir imágenes de los QR…")
        images.connect("clicked", self._open_images)
        paste = Gtk.Button(label="Pegar enlaces…")
        paste.connect("clicked", self._paste_text)
        row.add(images)
        row.add(paste)
        box.add(row)

        self.status = Gtk.Label(xalign=0, wrap=True)
        box.add(self.status)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=160)
        scrolled.add(self.listbox)
        box.pack_start(scrolled, True, True, 0)
        self.warnings = Gtk.Label(xalign=0, wrap=True)
        box.add(self.warnings)

        self._fill_cameras()
        self._refresh()
        self.show_all()

    # -- cámara ------------------------------------------------------------

    def _fill_cameras(self) -> None:
        try:
            from .camera import list_cameras

            self.cameras = list_cameras()
        except Exception:  # noqa: BLE001 - sin GStreamer: solo imágenes y texto
            self.cameras = []
        for name, _device in self.cameras:
            self.camera_combo.append_text(name)
        if self.cameras:
            self.camera_combo.set_active(0)
        else:
            self.camera_combo.append_text("No se encontró ninguna cámara")
            self.camera_combo.set_active(0)
            self.camera_button.set_sensitive(False)
        if not qr.available():
            self.camera_button.set_sensitive(False)

    def _toggle_camera(self, _button) -> None:
        if self.scanner is not None:
            self._stop_camera()
            return
        from .camera import CameraError, CameraScanner

        device = self.cameras[self.camera_combo.get_active()][1]
        try:
            self.scanner = CameraScanner(self._add_uris_from_codes, device=device)
            self.scanner.on_error = lambda msg: GLib.idle_add(self._camera_failed, msg)
            self.viewer.pack_start(self.scanner.widget, True, True, 0)
            self.scanner.widget.set_size_request(-1, 300)
            self.viewer.show_all()
            self.scanner.start()
        except CameraError as exc:
            self._camera_failed(str(exc))
            return
        self.camera_button.set_label("Detener cámara")
        self.camera_combo.set_sensitive(False)

    def _camera_failed(self, message: str) -> bool:
        self._stop_camera()
        self._set_status(f"⚠ Cámara: {GLib.markup_escape_text(message)}. Prueba con la otra "
                         "cámara de la lista o abre una foto de los QR.")
        return False

    def _stop_camera(self) -> None:
        if self.scanner is None:
            return
        self.scanner.stop()
        for child in self.viewer.get_children():
            self.viewer.remove(child)
        self.scanner = None
        self.camera_button.set_label("Escanear con la cámara")
        self.camera_combo.set_sensitive(True)

    # -- otras fuentes -----------------------------------------------------

    def _open_images(self, _button) -> None:
        chooser = Gtk.FileChooserNative(title="Imágenes con los QR", transient_for=self,
                                        action=Gtk.FileChooserAction.OPEN,
                                        select_multiple=True)
        images = Gtk.FileFilter()
        images.set_name("Imágenes")
        images.add_mime_type("image/*")
        chooser.add_filter(images)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            codes, failed = [], []
            for path in chooser.get_filenames():
                try:
                    found = qr.decode_file(path)
                except (ValueError, qr.QrUnavailable) as exc:
                    failed.append(str(exc))
                    continue
                if not found:
                    failed.append(f"{GLib.path_get_basename(path)}: no se ve ningún QR")
                codes += found
            self._add_uris_from_codes(codes)
            if failed:
                self._set_status("⚠ " + GLib.markup_escape_text("; ".join(failed)))
        chooser.destroy()

    def _paste_text(self, _button) -> None:
        dialog = Gtk.Dialog(title="Pegar enlaces", transient_for=self, modal=True)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Añadir", Gtk.ResponseType.OK)
        dialog.set_default_size(520, 260)
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.CHAR)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.add(view)
        area = dialog.get_content_area()
        area.set_spacing(6)
        area.add(Gtk.Label(label="Pega uno o varios enlaces otpauth-migration:// u otpauth://",
                           xalign=0, margin=8))
        area.pack_start(scrolled, True, True, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            buffer = view.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
            uris = find_uris(text)
            if uris:
                self._add_uris_from_codes(uris)
            else:
                self._set_status("⚠ No hay ningún enlace otpauth en el texto pegado.")
        dialog.destroy()

    # -- resultados --------------------------------------------------------

    def _add_uris_from_codes(self, codes: list[str]) -> bool:
        new = [u for code in codes for u in find_uris(code) if u not in self.uris]
        if new:
            self.uris += new
            self._refresh()
        return False

    def _set_status(self, markup: str) -> None:
        self.status.set_markup(markup)

    def _refresh(self) -> None:
        accounts, skipped, batches = accounts_from_uris(self.uris)
        previous = {a.secret: c.get_active() for c, a in self.checks}
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.checks = []
        for account in accounts:
            exists = account.secret.upper() in self.known_secrets
            check = Gtk.CheckButton(active=not exists and previous.get(account.secret, True),
                                    sensitive=not exists, margin=6)
            label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            user = f"  <span alpha='70%'>{GLib.markup_escape_text(account.username)}</span>" \
                if account.username else ""
            tag = "  <small>(ya la tienes)</small>" if exists else ""
            label.set_markup(f"<b>{GLib.markup_escape_text(account.name)}</b>{user}{tag}")
            check.add(label)
            check.connect("toggled", lambda *_: self._update_button())
            self.listbox.add(check)
            self.checks.append((check, account))
        self.listbox.show_all()

        if not self.uris:
            self._set_status("Esperando QR…")
        else:
            missing = missing_batches(batches)
            total = sum(1 for _ in accounts)
            text = f"{total} cuenta(s) encontradas"
            if missing:
                text += (f" · <b>faltan los QR {', '.join(map(str, missing))}</b> de la "
                         "exportación: pasa al siguiente en el móvil")
            elif batches:
                text += " · exportación completa ✔"
            self._set_status(text)
        self.warnings.set_markup(
            "<small>No se importarán:\n" + "\n".join(
                "• " + GLib.markup_escape_text(s) for s in skipped) + "</small>"
            if skipped else "")
        self._update_button()

    def _update_button(self) -> None:
        count = sum(1 for check, _ in self.checks if check.get_active() and check.get_sensitive())
        self.import_button.set_label(f"Importar {count} cuenta(s)" if count else "Importar")
        self.import_button.set_sensitive(count > 0)

    def selected(self) -> list[ImportedAccount]:
        return [a for check, a in self.checks if check.get_active() and check.get_sensitive()]

    def run_import(self):
        self._stop_camera()
        return import_accounts(self.store, self.selected())
