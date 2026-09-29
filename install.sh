#!/usr/bin/env bash
# Instala TOTP Autofill para el usuario actual (no necesita sudo).
#
#   - Copia la app a ~/.local/share/totp-autofill
#   - Crea el comando ~/.local/bin/totp-autofill
#   - Añade el lanzador al menú de aplicaciones
#   - Registra el host de Native Messaging en Chrome/Chromium/Brave/Edge/Firefox
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/totp-autofill"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

echo "==> Comprobando dependencias"
if ! python3 - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Secret", "1")
from gi.repository import Gtk, Secret
PY
then
  echo "Faltan dependencias del sistema. Instálalas con:" >&2
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-secret-1 gnome-keyring" >&2
  exit 1
fi

echo "==> Copiando la aplicación en $PREFIX"
rm -rf "$PREFIX/totp_autofill" "$PREFIX/extension"
mkdir -p "$PREFIX" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
cp -r "$SRC/totp_autofill" "$SRC/extension" "$PREFIX/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$PREFIX/totp-autofill-host" <<SH
#!/bin/sh
# Lanzado por el navegador (Native Messaging). Ignora los argumentos que añade.
PYTHONPATH="$PREFIX" exec /usr/bin/python3 -m totp_autofill host
SH
chmod 755 "$PREFIX/totp-autofill-host"

cat > "$BIN_DIR/totp-autofill" <<SH
#!/bin/sh
PYTHONPATH="$PREFIX" exec /usr/bin/python3 -m totp_autofill "\$@"
SH
chmod 755 "$BIN_DIR/totp-autofill"

echo "==> Añadiendo lanzador al menú de aplicaciones"
cp "$SRC/data/totp-autofill.png" "$ICON_DIR/totp-autofill.png"
sed "s|@BIN@|$BIN_DIR/totp-autofill|" "$SRC/data/totp-autofill.desktop" \
  > "$APPS_DIR/totp-autofill.desktop"
update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
gtk-update-icon-cache -q "${ICON_DIR%/256x256/apps}" >/dev/null 2>&1 || true

echo "==> Registrando el host nativo en los navegadores"
"$BIN_DIR/totp-autofill" install-browser --host-path "$PREFIX/totp-autofill-host" || \
  echo "    (No se detectó ningún navegador; vuelve a ejecutar install.sh tras abrir uno)"

cat <<MSG

Instalación completada.

Siguiente paso: carga la extensión en tu navegador desde
  $PREFIX/extension
(ver README.md, sección «Instalar la extensión»).

Abre la app desde el menú («TOTP Autofill») o con: totp-autofill
MSG
