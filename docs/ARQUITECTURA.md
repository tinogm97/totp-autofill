# Arquitectura

TOTP Autofill escribe códigos TOTP en el campo con el foco **sin extensión de
navegador**. Se apoya en dos servicios del escritorio Linux:

| Servicio | Para qué | Módulo |
|---|---|---|
| **AT-SPI** (accesibilidad) | Saber en qué campo estás, qué es, en qué página (URL) y qué email escribiste | `a11y.py` |
| **XTest** (X11) | Teclear el código como si fuera el teclado | `x11.py` |

Chrome no permite escribir en campos por accesibilidad (no implementa
`EditableText`), así que la lectura va por AT-SPI y la escritura por XTest.

## Procesos

```
 sesión ──autostart──► totp-autofill daemon     (Gtk.Application, id …TotpAutofill.Daemon)
                          ├─ escucha AT-SPI: object:state-changed:focused
                          │                  object:text-changed:{insert,delete}
                          └─ acción D-Bus "fill"  ◄── totp-autofill fill ◄── Ctrl+Alt+2 (GNOME)

 menú ─────────────────► totp-autofill          (GUI: cuentas y preferencias)
```

- El daemon es una `Gtk.Application`: una sola instancia por sesión y la
  acción `fill` publicada en D-Bus (`org.gtk.Actions` en
  `/io/github/tinogm97/TotpAutofill/Daemon`).
- `totp-autofill fill` llama a esa acción. Si el daemon no está en marcha,
  hace lo mismo por su cuenta, solo con el título de la ventana
  (`daemon.fill_standalone`).
- La GUI arranca el daemon si no lo encuentra.

## Flujo automático

1. **Foco en un campo** (`_on_focus`): se guarda como último campo y, si el
   modo automático está activo, 150 ms después se evalúa (`_maybe_autofill`).
2. **¿Es un campo de código?** `detect.otp_confidence` sobre lo que expone
   Chrome (`FieldInfo.from_atspi`: etiqueta, `id`, `html-input-name`,
   `text-input-type`, `maxlength`, `placeholder-text`):
   - **2**: `autocomplete=one-time-code` o etiqueta/id que habla de código
     (`otp`, `2fa`, `código`, `verification`…) sin pistas de lo contrario
     (email, contraseña, postal, cupón…);
   - **1**: sin pistas pero con `maxlength` 1 (cajas de un dígito) o 6-8;
   - **0**: no.
3. **Contexto**: host del documento (`Atspi.Document` → `URI`), título de la
   ventana activa (EWMH) y usuario escrito recientemente en ese host.
4. **Resolución** (`resolver.resolve`), ver abajo. Si hay varias candidatas,
   se lee el texto de la página (`a11y.page_text`) para buscar el email.
5. **Acción**:
   - cuenta decidida **por el sitio** (`Resolution.trusted`) → se teclea;
   - si no, y la confianza es 2 y el host no se canceló antes → selector bajo
     el campo; lo elegido se aprende (`AccountStore.learn`) y se teclea;
   - en otro caso, nada (el atajo sigue disponible).

Protecciones: el campo no se rellena si ya tiene texto; como mucho 2 veces
por campo cada 5 minutos (evita bucles si el servicio rechaza el código);
tras teclear se ignoran eventos de foco 1,5 s (en las cajas de un dígito el
foco salta de caja en caja).

## Flujo del atajo

`fill_focused`: toma la ventana activa y, si el último campo con foco es de
esa misma aplicación (mismo PID) y sigue enfocado, usa su host y el usuario
escrito. Resuelve igual que el automático, pero **acepta** también la
decisión por título de ventana o por ser la única cuenta, porque lo ha pedido
el usuario. Si pregunta, al elegir se reactiva la ventana original antes de
teclear.

## Resolución de la cuenta

```
por sitio (host)  ──►  ¿una?  ──sí──►  cuenta  (via="site", de confianza)
     │ varias            │no
     ▼                   ▼
  por usuario escrito / email en la página ──► ¿una? ──► cuenta (via="site")
     │ ninguna
     ▼
por título de ventana aprendido ──► (misma lógica)  ──► cuenta (via="title")
     │ ninguna
     ▼
¿solo hay una cuenta? ──► cuenta (via="only")
     │ no
     ▼
selector con candidatas ordenadas (las del sitio/usuario primero)
```

`via="site"` es la única de confianza para escribir sin preguntar: el host lo
fija el navegador, mientras que el título de la ventana lo decide la página.

## Usuario que inicia sesión

`_on_text` escucha cambios de texto en campos que `detect.is_user_field`
reconoce como de usuario/email (nunca en contraseñas: se exige rol `entry`).
Se lee al teclear porque en una SPA el campo ya no existe cuando pierde el
foco. Solo se guarda si coincide con el usuario de alguna cuenta (en memoria,
por host, 10 minutos); si se escribe otro distinto, se olvida el anterior
para no usar la cuenta de un login previo.

## Datos

- `~/.config/totp-autofill/accounts.json` (600, escritura atómica):

  ```json
  {
    "version": 2,
    "accounts": [{
      "name": "Portal dev", "username": "ana@empresa.com",
      "sites": ["localhost:4200"], "window_titles": [],
      "auto_submit": false, "digits": 6, "period": 30, "algorithm": "SHA1",
      "id": "3f1c…"
    }]
  }
  ```

  Los ficheros de la v1 (`url_pattern`, `selector`) se migran al leerlos: el
  host del patrón pasa a `sites`.
- `~/.config/totp-autofill/settings.json`: `auto_fill`, `shortcut`.
- Llavero (libsecret): un elemento por cuenta, esquema
  `com.github.tinogm97.TotpAutofill`, atributo `account_id`.
- `TOTP_AUTOFILL_TEST_SECRETS=/fichero.json` cambia el llavero por un fichero
  **en claro**; existe solo para los tests automáticos.

## Accesibilidad en Chrome

Comprobado en Chrome/Chromium 151–154 sobre Ubuntu 24.04 (X11):

| Condición | ¿Expone las páginas? |
|---|---|
| Nada | No |
| `ACCESSIBILITY_ENABLED=1`, `toolkit-accessibility`, `org.a11y.Status.IsEnabled` | No |
| `org.a11y.Status.ScreenReaderEnabled=true` | Sí, pero **arranca Orca** (lector de pantalla con voz): descartado |
| `--force-renderer-accessibility` **y** `QT_ACCESSIBILITY=1` | **Sí** |

Ubuntu define `QT_ACCESSIBILITY=1` en la sesión, pero no llega a navegadores
lanzados con entorno limpio (p. ej. vía `pkexec`). `chrome_setup` crea un
lanzador de usuario con `env QT_ACCESSIBILITY=1 … --force-renderer-accessibility`
(marcado para poder deshacerlo) y genera el `sed` para el script del Chrome
VPN.

Además, Chrome solo emite eventos de foco si **su ventana tiene el foco del
teclado**; en un escritorio normal lo da el gestor de ventanas. En el test
e2e (Xvfb sin gestor) se da explícitamente con `XSetInputFocus`.

## Tecleo (`x11.py`)

ctypes sobre `libX11` y `libXtst`, sin dependencias:

- `wait_modifiers_released()`: espera a que se suelten Ctrl/Alt del atajo
  (si no, cada dígito sería otro atajo).
- `_keycode()`: si la distribución de teclado pone los dígitos con Mayúsculas
  (AZERTY), las pulsa.
- `activate()`: `_NET_ACTIVE_WINDOW` (EWMH) o, sin gestor de ventanas,
  `XSetInputFocus`.

## Importación desde Google Authenticator

- `migration.py` decodifica `otpauth-migration://offline?data=…`: base64 de un
  protobuf `MigrationPayload` que se lee a mano (varints y campos de
  longitud). Secreto en bytes → Base32; `Emisor:cuenta` → nombre y usuario;
  algoritmo y dígitos según los enums de Google. HOTP y MD5 se descartan con
  aviso. Cada QR trae `batch_index`/`batch_size`/`batch_id`, lo que permite
  decir qué QR de la exportación faltan (`missing_batches`).
- `qr.py` lee QR con `libzbar` por ctypes, sobre imágenes en escala de grises
  (canal verde, recortado con slices para que sea rápido).
- `camera.py`: `fuente ! videoconvert ! tee` → rama con `gtksink` (visor) y
  rama `queue leaky ! GRAY8 ! appsink` que se escanea cada 150 ms. Las cámaras
  se listan con `Gst.DeviceMonitor` (V4L2 primero, con su `/dev/videoN`).
- `migration.import_accounts` omite las cuentas cuyo secreto ya existe.

## Decisiones descartadas

- **Extensión de navegador (v1):** funcionaba, pero exigía instalarla en cada
  navegador y configurar URLs. La accesibilidad da la misma información desde
  fuera.
- **Activar el "lector de pantalla" del sistema** para que Chrome exponga las
  páginas: arranca Orca.
- **Leer contraseñas o todo lo que se teclea:** solo se leen campos de
  usuario/email y solo se guardan usuarios configurados.
- **Dependencias como `pyotp`, `keyring`, `python-xlib` o `xdotool`:** TOTP son
  10 líneas con `hmac`; libsecret, AT-SPI y XTest ya están en Ubuntu.
