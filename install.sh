#!/usr/bin/env bash
# Instala TOTP Autofill para el usuario actual (no necesita sudo).
#
#   - Copia la app a ~/.local/share/totp-autofill y crea ~/.local/bin/totp-autofill
#   - Añade el lanzador al menú de aplicaciones
#   - Arranca el proceso en segundo plano y lo añade al inicio de sesión
#   - Registra el atajo Ctrl+Alt+2 en GNOME            (--no-shortcut para omitirlo)
#   - Crea un lanzador de Chrome con accesibilidad     (--no-chrome para omitirlo)
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/totp-autofill"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA/applications"
ICON_THEME="$DATA/icons/hicolor"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP_ID="io.github.tinogm97.TotpAutofill"  # = application_id de la app GTK

SETUP_SHORTCUT=1
SETUP_CHROME=1
for arg in "$@"; do
  case "$arg" in
    --no-shortcut) SETUP_SHORTCUT=0 ;;
    --no-chrome) SETUP_CHROME=0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

echo "==> Comprobando dependencias"
if ! python3 - <<'PY' 2>/dev/null
import ctypes
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Secret", "1")
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, Gtk, Secret
ctypes.cdll.LoadLibrary("libXtst.so.6")
PY
then
  echo "Faltan dependencias del sistema. Instálalas con:" >&2
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-secret-1 gir1.2-atspi-2.0 \\" >&2
  echo "                   at-spi2-core libxtst6 gnome-keyring libnotify-bin" >&2
  exit 1
fi
# Opcionales: importar desde Google Authenticator (leer QR y usar la cámara).
if ! python3 - <<'PY' 2>/dev/null
import ctypes, gi
ctypes.cdll.LoadLibrary("libzbar.so.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo
Gst.init(None)
assert Gst.ElementFactory.find("gtksink")
PY
then
  echo "    (Para importar desde Google Authenticator con la cámara instala:"
  echo "     sudo apt install libzbar0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-gtk3 gstreamer1.0-plugins-good)"
fi

echo "==> Copiando la aplicación en $PREFIX"
# Se paran la app y el proceso en segundo plano para que usen el código nuevo.
pkill -f "python3 -m totp_autofill( daemon)?\$" 2>/dev/null || true
rm -rf "$PREFIX/totp_autofill"
mkdir -p "$PREFIX" "$BIN_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
cp -r "$SRC/totp_autofill" "$PREFIX/"
cp "$SRC/uninstall.sh" "$PREFIX/uninstall.sh"
chmod 755 "$PREFIX/uninstall.sh"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +
PYTHONPATH="$PREFIX" python3 -c "import totp_autofill; print(totp_autofill.__version__)" \
  > "$PREFIX/VERSION"

cat > "$BIN_DIR/totp-autofill" <<SH
#!/bin/sh
PYTHONPATH="$PREFIX" exec /usr/bin/python3 -m totp_autofill "\$@"
SH
chmod 755 "$BIN_DIR/totp-autofill"

# Restos de la v1 (extensión de navegador + Native Messaging).
if [ -e "$PREFIX/extension" ] || [ -e "$PREFIX/totp-autofill-host" ]; then
  echo "==> Quitando la integración con la extensión de la versión 1"
  rm -rf "$PREFIX/extension" "$PREFIX/totp-autofill-host"
  find "$HOME/.config" "$HOME/.mozilla" -maxdepth 5 \
    -name 'com.github.tinogm97.totp_autofill.json' -path '*ative*essaging*' \
    -delete 2>/dev/null || true
  echo "    Quita también la extensión «TOTP Autofill» de tu navegador: ya no hace falta."
fi

echo "==> Añadiendo lanzador al menú de aplicaciones"
for png in "$SRC"/totp_autofill/icons/totp-autofill-*.png; do
  size="${png##*-}"; size="${size%.png}"
  install -Dm644 "$png" "$ICON_THEME/${size}x${size}/apps/totp-autofill.png"
done
install -Dm644 "$SRC/totp_autofill/icons/totp-autofill.svg" \
  "$ICON_THEME/scalable/apps/totp-autofill.svg"
# El .desktop se llama como el application_id para que GNOME asocie la
# ventana con su lanzador (y su icono) en el dock.
rm -f "$APPS_DIR/totp-autofill.desktop"  # nombre usado hasta la v1.2
sed "s|@BIN@|$BIN_DIR/totp-autofill|" "$SRC/data/totp-autofill.desktop" \
  > "$APPS_DIR/$DESKTOP_ID.desktop"
update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
# Si existe una caché de iconos (p. ej. creada por Chrome), hay que
# regenerarla o GTK no verá el icono nuevo. -t: no exige index.theme.
if [ -f "$ICON_THEME/icon-theme.cache" ]; then
  gtk-update-icon-cache -f -t -q "$ICON_THEME" >/dev/null 2>&1 || \
    rm -f "$ICON_THEME/icon-theme.cache"
fi

echo "==> Proceso en segundo plano (se inicia con la sesión)"
sed "s|@BIN@|$BIN_DIR/totp-autofill|" "$SRC/data/totp-autofill-daemon.desktop" \
  > "$AUTOSTART_DIR/$DESKTOP_ID.Daemon.desktop"
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  setsid "$BIN_DIR/totp-autofill" daemon </dev/null >/dev/null 2>&1 &
fi

if [ "$SETUP_SHORTCUT" = 1 ]; then
  echo "==> Atajo de teclado"
  "$BIN_DIR/totp-autofill" setup-shortcut || \
    echo "    (No se pudo registrar; configúralo a mano con el comando «totp-autofill fill»)"
fi

if [ "$SETUP_CHROME" = 1 ]; then
  echo "==> Accesibilidad en Chrome (para el modo automático)"
  "$BIN_DIR/totp-autofill" setup-chrome || true
fi

cat <<MSG

Instalación completada.

- Atajo: pon el cursor en el campo del código y pulsa Ctrl+Alt+2.
- Automático: reinicia Chrome por completo; al entrar en un campo de código
  se escribirá solo.
- Añade tus cuentas en la app «TOTP Autofill» (menú de aplicaciones).
- Comprueba que todo está listo con: totp-autofill status

Para desinstalar: $PREFIX/uninstall.sh
MSG
