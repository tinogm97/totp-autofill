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
ICON_THEME="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
DESKTOP_ID="io.github.tinogm97.TotpAutofill"  # = application_id de la app GTK

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
# Si la app está abierta, se cierra para que la próxima vez use el código nuevo.
pkill -f "python3 -m totp_autofill\$" 2>/dev/null && echo "    (app abierta cerrada; vuelve a abrirla)" || true
rm -rf "$PREFIX/totp_autofill" "$PREFIX/extension"
mkdir -p "$PREFIX" "$BIN_DIR" "$APPS_DIR"
cp -r "$SRC/totp_autofill" "$SRC/extension" "$PREFIX/"
cp "$SRC/uninstall.sh" "$PREFIX/uninstall.sh"
chmod 755 "$PREFIX/uninstall.sh"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +
PYTHONPATH="$PREFIX" python3 -c "import totp_autofill; print(totp_autofill.__version__)" \
  > "$PREFIX/VERSION"

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

echo "==> Registrando el host nativo en los navegadores"
"$BIN_DIR/totp-autofill" install-browser --host-path "$PREFIX/totp-autofill-host" || \
  echo "    (No se detectó ningún navegador; vuelve a ejecutar install.sh tras abrir uno)"

cat <<MSG

Instalación completada.

Siguiente paso: carga la extensión en tu navegador desde
  $PREFIX/extension
(instrucciones: https://github.com/tinogm97/totp-autofill#instalar-la-extensión).

Abre la app desde el menú («TOTP Autofill») o con: totp-autofill
Para desinstalar: $PREFIX/uninstall.sh
MSG
