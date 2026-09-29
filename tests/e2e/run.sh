#!/usr/bin/env bash
# Test end-to-end del modo automático y del atajo, sin extensión.
#
# Todo ocurre en una sesión aislada: pantalla virtual (Xvfb), D-Bus y bus de
# accesibilidad propios y secretos en un fichero temporal; no toca tu
# escritorio ni tu llavero.
#
# Requisitos: xvfb, dbus, at-spi2-core y un Chromium o Chrome.
# Por defecto usa el último Chromium de Playwright (npx playwright install
# chromium); otro navegador con: CHROME=/ruta/al/chrome tests/e2e/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -z "${CHROME:-}" ]; then
  CHROME="$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux64/chrome 2>/dev/null \
    | sort -t- -k2 -n | tail -1)"
  CHROME="${CHROME:-$(command -v chromium || command -v google-chrome || true)}"
fi
[ -x "$CHROME" ] || { echo "No encuentro Chromium; indica CHROME=/ruta" >&2; exit 1; }
export CHROME

# Primero la pantalla y luego el bus: así los servicios que arranca el bus
# (p. ej. el registro de accesibilidad) conocen DISPLAY.
# Aislamiento total del escritorio real:
# - HOME y XDG_* temporales: si algo arranca un llavero, portal, etc. dentro
#   de la sesión de prueba, trabaja sobre carpetas vacías y no sobre las tuyas.
# - Chrome con --password-store=basic (en e2e.py): no usa ningún llavero.
# - QT_ACCESSIBILITY y GTK_MODULES como en una sesión de Ubuntu: sin
#   QT_ACCESSIBILITY=1 Chrome no se conecta a la accesibilidad.
# - Los secretos de las cuentas de prueba van a un fichero temporal
#   (TOTP_AUTOFILL_TEST_SECRETS), nunca al llavero.
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/home" "$SANDBOX/runtime"
chmod 700 "$SANDBOX/runtime"
env -i PATH="$PATH" LANG="${LANG:-C.UTF-8}" CHROME="$CHROME" \
  HOME="$SANDBOX/home" XDG_RUNTIME_DIR="$SANDBOX/runtime" \
  XDG_CONFIG_HOME="$SANDBOX/home/.config" XDG_DATA_HOME="$SANDBOX/home/.local/share" \
  XDG_CACHE_HOME="$SANDBOX/home/.cache" XDG_SESSION_TYPE=x11 \
  QT_ACCESSIBILITY=1 GTK_MODULES=gail:atk-bridge \
  TOTP_AUTOFILL_DEBUG="${TOTP_AUTOFILL_DEBUG:-}" \
  xvfb-run -a -s "-screen 0 1280x900x24" \
  dbus-run-session -- python3 "$ROOT/tests/e2e/e2e.py"
