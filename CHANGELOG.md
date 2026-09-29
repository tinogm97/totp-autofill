# Changelog

## 1.2.1 — 2026-09-29

- **Icono de la app**: la ventana se identificaba como `__main__.py` y usaba
  un icono genérico, así que el dock no mostraba el de la app. Ahora fija su
  clase de ventana (`totp-autofill`), carga el icono del propio paquete, el
  `.desktop` se llama como el application_id y se instalan todos los tamaños
  (16–512 px y SVG), regenerando la caché de iconos si existe.

## 1.2.0 — 2026-09-29

- **Instalador remoto** `get.sh`: instala o actualiza con
  `curl -fsSL https://raw.githubusercontent.com/tinogm97/totp-autofill/main/get.sh | bash`,
  sin clonar el repositorio. Admite `--version`, `--main`, `--uninstall` y
  `--purge`.
- `install.sh` deja el desinstalador y un fichero `VERSION` en
  `~/.local/share/totp-autofill/`, y cierra la app si estaba abierta para
  que se reabra con la versión nueva.

## 1.1.1 — 2026-09-29

- El instalador registra el host también en navegadores Chromium lanzados
  con `--user-data-dir` (cualquier carpeta de `~/.config` con perfil de
  navegador) y admite `--browser-dir` para carpetas en otro sitio. Antes, un
  Chrome con carpeta de datos propia mostraba "Specified native messaging
  host not found".

## 1.1.0 — 2026-09-29

- Las cuentas tienen **email/usuario** (campo «Cuenta / email» en la app,
  `--user` en la CLI, se rellena solo desde URIs `otpauth://`).
- **Varias cuentas en la misma URL**: la extensión usa la del usuario con el
  que se inicia sesión (en la misma página, en una anterior de la pestaña o
  mostrado en la página) y, si no lo sabe, muestra un selector junto al campo.
- Patrones de **solo host** (`localhost:4200`) abarcan todo el sitio.
- La app impide duplicar cuentas con la misma URL y usuario.
- `totp-autofill code` acepta también el email/usuario.
- Popup: muestra el email de cada cuenta y marca la detectada.
- Demo con dos usuarios y modo multipágina; test e2e ampliado.

## 1.0.0 — 2026-09-29

Primera versión.

- App de escritorio GTK 3 para gestionar cuentas 2FA con cuenta atrás y copia
  al portapapeles.
- Secretos en el llavero del sistema (libsecret).
- Extensión Manifest V3 para Chrome/Chromium/Brave/Edge/Firefox: detección
  automática del campo (incluidos formularios de 6 cajas y SPA), selector CSS
  opcional, envío automático, popup y atajo `Alt+Shift+2`.
- Host de Native Messaging con verificación de URL por cuenta.
- CLI: `list`, `add`, `code`, `delete`, `install-browser`, `uninstall-browser`.
- Instalador sin `sudo`.
