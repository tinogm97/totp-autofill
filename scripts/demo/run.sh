#!/usr/bin/env bash
# Graba y monta el vídeo demo (docs/demo.mp4) en una sesión aislada: pantalla
# virtual, D-Bus y accesibilidad propios, HOME temporal y secretos falsos en un
# fichero temporal. No toca tu escritorio, tu llavero ni tu webcam.
#
# Uso: scripts/demo/run.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHROME="${CHROME:-$(command -v google-chrome || command -v chromium)}"
WORK="$(mktemp -d)"
trap '[ -n "${DEMO_KEEP:-}" ] && cp -r "$WORK/out" "$DEMO_KEEP"; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/home" "$WORK/runtime" "$WORK/out"
chmod 700 "$WORK/runtime"

env -i PATH="$PATH" LANG=es_ES.UTF-8 CHROME="$CHROME" DEMO_OUT="$WORK/out" \
  HOME="$WORK/home" XDG_RUNTIME_DIR="$WORK/runtime" \
  XDG_CONFIG_HOME="$WORK/home/.config" XDG_DATA_HOME="$WORK/home/.local/share" \
  XDG_CACHE_HOME="$WORK/home/.cache" XDG_SESSION_TYPE=x11 \
  QT_ACCESSIBILITY=1 GTK_MODULES=gail:atk-bridge \
  TOTP_AUTOFILL_TESTING=1 TOTP_AUTOFILL_TEST_SECRETS="$WORK/secrets.json" \
  xvfb-run -a -s "-screen 0 1280x720x24" \
  dbus-run-session -- python3 "$HERE/record.py"

python3 "$HERE/cards.py" "$WORK/out"
python3 "$HERE/assemble.py" "$WORK/out" "$ROOT/docs"
