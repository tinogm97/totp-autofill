#!/usr/bin/env bash
# Test end-to-end: carga la extensión en Chromium (Playwright), usa el host
# nativo real y el llavero real, y comprueba que la página demo recibe el
# código correcto de la cuenta correcta cuando dos usuarios comparten URL:
# campo único, 6 cajas, paso del código en otra página y selector de cuentas.
#
# Requisitos: node >= 18 y un Chromium de Playwright
#   (npx playwright install chromium). Chrome de marca no sirve: desde la
#   v137 ignora --load-extension.
#
# Uso: tests/e2e/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
PORT=8765
SECRET_ANA=JBSWY3DPEHPK3PXP
SECRET_LUIS=GEZDGNBVGY3TQOJQ
export XDG_CONFIG_HOME="$WORK/config" PYTHONPATH="$ROOT"

cleanup() {
  python3 -c "
from totp_autofill.store import AccountStore
s = AccountStore()
for a in s.load(): s.delete(a.id)" || true
  [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# Host nativo apuntando a la configuración temporal.
cat > "$WORK/host.sh" <<SH
#!/bin/sh
XDG_CONFIG_HOME="$XDG_CONFIG_HOME" PYTHONPATH="$ROOT" exec python3 -m totp_autofill host
SH
chmod +x "$WORK/host.sh"
mkdir -p "$WORK/profile/NativeMessagingHosts"
cat > "$WORK/profile/NativeMessagingHosts/com.github.tinogm97.totp_autofill.json" <<JSON
{"name": "com.github.tinogm97.totp_autofill", "description": "e2e", "type": "stdio",
 "path": "$WORK/host.sh",
 "allowed_origins": ["chrome-extension://blnffoflcmdajflilndalbfcgeddaakd/"]}
JSON

# Dos cuentas con la misma URL (solo host:puerto), distinguidas por usuario.
python3 -m totp_autofill add "Demo Ana" "localhost:$PORT" --user ana@demo.com \
  --secret "$SECRET_ANA" --auto-submit
python3 -m totp_autofill add "Demo Luis" "localhost:$PORT" --user luis@demo.com \
  --secret "$SECRET_LUIS" --auto-submit

python3 -m http.server "$PORT" --directory "$ROOT/examples" >/dev/null 2>&1 &
SERVER_PID=$!

(cd "$WORK" && npm init -y >/dev/null && npm i playwright-core >/dev/null 2>&1)
cp "$ROOT/tests/e2e/e2e.mjs" "$WORK/"
(cd "$WORK" && ROOT="$ROOT" PROFILE="$WORK/profile" PORT="$PORT" \
  SECRET_ANA="$SECRET_ANA" SECRET_LUIS="$SECRET_LUIS" node e2e.mjs)
