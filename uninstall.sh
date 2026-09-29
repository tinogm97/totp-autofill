#!/usr/bin/env bash
# Desinstala TOTP Autofill. Las cuentas y secretos NO se borran salvo que
# se pase --purge.
set -euo pipefail

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/totp-autofill"
BIN="$HOME/.local/bin/totp-autofill"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/io.github.tinogm97.TotpAutofill.Daemon.desktop"

if [ -x "$BIN" ]; then
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
  "$BIN" setup-shortcut --remove >/dev/null 2>&1 || true
  "$BIN" setup-chrome --undo || true
fi

pkill -f "python3 -m totp_autofill( daemon)?\$" 2>/dev/null || true
rm -rf "$PREFIX"
rm -f "$BIN" "$AUTOSTART" \
      "$DATA/applications/totp-autofill.desktop" \
      "$DATA/applications/io.github.tinogm97.TotpAutofill.desktop" \
      "$DATA"/icons/hicolor/*/apps/totp-autofill.png \
      "$DATA/icons/hicolor/scalable/apps/totp-autofill.svg"
echo "TOTP Autofill desinstalado."
