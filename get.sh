#!/usr/bin/env bash
# Instalador remoto de TOTP Autofill: descarga la última versión publicada y
# la instala para el usuario actual, sin clonar el repositorio ni usar sudo.
#
#   curl -fsSL https://raw.githubusercontent.com/tinogm97/totp-autofill/main/get.sh | bash
#
# Opciones (tras «bash -s --» si se usa con curl):
#   --version vX.Y.Z   instala esa versión en vez de la última
#   --main             instala la rama main (en desarrollo)
#   --uninstall        desinstala (conserva cuentas y secretos)
#   --purge            desinstala y borra cuentas y secretos del llavero
#
# Ejemplo: curl -fsSL …/get.sh | bash -s -- --version v1.2.0
#
# Volver a ejecutarlo actualiza a la última versión.
set -euo pipefail

REPO="tinogm97/totp-autofill"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/totp-autofill"

VERSION=""
ACTION="install"
UNINSTALL_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:?Falta la versión tras --version}"; shift 2 ;;
    --main) VERSION="main"; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --purge) ACTION="uninstall"; UNINSTALL_ARGS=(--purge); shift ;;
    -h|--help)
      echo "Uso: get.sh [--version vX.Y.Z | --main] [--uninstall | --purge]"
      exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then BLUE=$'\033[1;34m' RED=$'\033[1;31m' RESET=$'\033[0m'; else BLUE="" RED="" RESET=""; fi
say() { printf '%s==>%s %s\n' "$BLUE" "$RESET" "$*"; }
die() { printf '%sError:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

if command -v curl >/dev/null; then
  fetch() { curl -fsSL "$1"; }
  final_url() { curl -fsSLI -o /dev/null -w '%{url_effective}' "$1"; }
elif command -v wget >/dev/null; then
  fetch() { wget -qO- "$1"; }
  final_url() { wget -S --spider "$1" 2>&1 | awk '/^  Location: /{u=$2} END{print u}'; }
else
  die "Necesitas curl o wget."
fi
command -v tar >/dev/null || die "Necesitas tar."
command -v python3 >/dev/null || die "Necesitas python3 (sudo apt install python3)."

# Desinstalar con la copia instalada, si existe.
if [ "$ACTION" = "uninstall" ] && [ -x "$PREFIX/uninstall.sh" ]; then
  exec "$PREFIX/uninstall.sh" "${UNINSTALL_ARGS[@]}"
fi

# Versión a descargar: la indicada, o la última release (o main si no hay).
if [ -z "$VERSION" ]; then
  latest="$(final_url "https://github.com/$REPO/releases/latest" || true)"
  case "$latest" in
    */releases/tag/*) VERSION="${latest##*/}" ;;
    *) VERSION="main" ;;
  esac
fi
if [ "$VERSION" = "main" ]; then
  url="https://github.com/$REPO/archive/refs/heads/main.tar.gz"
else
  url="https://github.com/$REPO/archive/refs/tags/$VERSION.tar.gz"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say "Descargando TOTP Autofill $VERSION"
fetch "$url" | tar -xz -C "$TMP" --strip-components=1 \
  || die "No se pudo descargar $url"

if [ "$ACTION" = "uninstall" ]; then
  bash "$TMP/uninstall.sh" "${UNINSTALL_ARGS[@]}"
  exit 0
fi

INSTALLED="$(cat "$PREFIX/VERSION" 2>/dev/null || true)"
bash "$TMP/install.sh"

if [ -n "$INSTALLED" ]; then
  cat <<MSG

Actualizado de $INSTALLED a $(cat "$PREFIX/VERSION").
Reinicia Chrome por completo para el modo automático y comprueba con:
  totp-autofill status
MSG
fi
