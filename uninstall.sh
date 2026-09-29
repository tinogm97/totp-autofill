#!/usr/bin/env bash
# Desinstala TOTP Autofill. Las cuentas y secretos NO se borran salvo que
# se pase --purge.
set -euo pipefail

PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/totp-autofill"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

if [ -x "$HOME/.local/bin/totp-autofill" ]; then
  if [ "${1:-}" = "--purge" ]; then
    echo "==> Borrando cuentas y secretos del llavero"
    PYTHONPATH="$PREFIX" python3 - <<'PY'
from totp_autofill.store import AccountStore
store = AccountStore()
for account in store.load():
    store.delete(account.id)
PY
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/totp-autofill"
  fi
  "$HOME/.local/bin/totp-autofill" uninstall-browser
fi

pkill -f "python3 -m totp_autofill\$" 2>/dev/null || true
rm -rf "$PREFIX"
rm -f "$HOME/.local/bin/totp-autofill" \
      "$DATA/applications/totp-autofill.desktop" \
      "$DATA/icons/hicolor/256x256/apps/totp-autofill.png"
echo "TOTP Autofill desinstalado. Recuerda quitar la extensión del navegador."
