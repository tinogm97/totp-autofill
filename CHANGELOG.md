# Changelog

## 2.0.1 — 2026-09-29

- El proceso en segundo plano ya no se cae si el bus de accesibilidad de la
  sesión no está disponible (la librería AT-SPI abortaba el proceso): arranca
  en modo solo-atajo y reintenta conectar cada 30 s.
- Revisión de seguridad: antes de teclear se comprueba que la ventana y el
  campo con el foco siguen siendo los mismos; no se escribe si el campo es de
  una ventana en segundo plano; nunca se lee el texto de campos de
  contraseña; un error de X11 ya no cierra el proceso; el selector solo deja
  de preguntar en un sitio tras pulsar Esc (y durante 10 minutos).
- Lanzador de Chrome: se guarda una copia exacta del lanzador de usuario que
  existiera y se restaura al desactivar; respeta `env` y rutas con espacios.
- El almacén de secretos en fichero para tests exige `TOTP_AUTOFILL_TESTING=1`.

## 2.0.0 — 2026-09-29

**Sin extensión de navegador y sin URLs que configurar.**

- **Modo automático** por accesibilidad (AT-SPI): al entrar en un campo de
  código de una web, se escribe el código solo, tecleándolo con XTest. Solo
  escribe sin preguntar en sitios ya asociados a una cuenta.
- **Atajo `Ctrl+Alt+2`** (GNOME): escribe el código en el campo con el foco,
  en cualquier aplicación. Funciona también sin accesibilidad.
- **Aprendizaje**: si no sabe qué cuenta usar, muestra un selector junto al
  campo y recuerda la respuesta (sitio o, sin accesibilidad, título de la
  ventana). Los sitios de cada cuenta son opcionales.
- Varias cuentas en el mismo sitio: elige por el email que escribes al
  iniciar sesión (solo se recuerda si es de una cuenta configurada) o el que
  aparece en la página.
- Proceso en segundo plano (`totp-autofill daemon`) que arranca con la sesión.
- `totp-autofill setup-chrome`: lanzador de Chrome con
  `--force-renderer-accessibility` y `QT_ACCESSIBILITY=1`; indica el comando
  para el Chrome VPN.
- Preferencias en la app (automático, atajo, estado de Chrome) y
  `totp-autofill status`.
- Wayland: copia el código al portapapeles y avisa.
- Test end-to-end en sesión aislada (Xvfb) con Chromium real, también en CI.
- **Eliminado**: la extensión de navegador, el host de Native Messaging y los
  patrones de URL / selectores CSS. Al actualizar se migran los patrones a
  sitios y se limpia el registro del host; quita la extensión del navegador.

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
