# TOTP Autofill

Aplicación de escritorio para **Ubuntu** que **rellena automáticamente los
códigos 2FA (TOTP)** en los formularios web que tú configures. Le dices "en
esta URL me piden el código del Authenticator" y, cada vez que aparezca el
formulario, el código se escribe solo (y, si quieres, se envía), sin tener que
mirar el móvil.

![Ventana principal](docs/screenshot-main.png)

- 🔐 **Secretos en el llavero de GNOME** (libsecret), nunca en texto plano ni
  en el navegador.
- 🌐 **Extensión para Chrome, Chromium, Brave, Edge y Firefox** que detecta el
  campo del código, incluidos formularios que aparecen tras el login (SPA) y
  los de "6 cajitas".
- ⚙️ **Configuración por URL** con comodines (`https://sso.empresa.com/mfa*`),
  selector CSS opcional y envío automático.
- 🧩 **Sin dependencias externas**: Python 3 + GTK 3 del sistema; el TOTP
  (RFC 6238) está implementado con la librería estándar.
- ⌨️ **App gráfica, CLI, popup y atajo de teclado** (`Alt+Shift+2`).

> ⚠️ **Aviso de seguridad:** tener el segundo factor en el mismo ordenador que
> la contraseña debilita el 2FA (deja de ser "algo que tienes" separado de
> "algo que sabes"). Úsalo en tu equipo personal, con disco cifrado y sesión
> bloqueada, y conserva el secreto también en tu autenticador del móvil. Ver
> [Seguridad](#seguridad).

---

## Índice

1. [Cómo funciona](#cómo-funciona)
2. [Requisitos](#requisitos)
3. [Instalación](#instalación)
4. [Instalar la extensión](#instalar-la-extensión)
5. [Configurar una cuenta](#configurar-una-cuenta)
6. [Patrones de URL](#patrones-de-url)
7. [Detección del campo del código](#detección-del-campo-del-código)
8. [Uso diario](#uso-diario)
9. [Línea de comandos](#línea-de-comandos)
10. [Seguridad](#seguridad)
11. [Solución de problemas](#solución-de-problemas)
12. [Desarrollo](#desarrollo)
13. [Desinstalar](#desinstalar)

---

## Cómo funciona

```
┌──────────────── Navegador ──────────────┐        ┌──────── Escritorio ──────┐
│                                         │        │                          │
│  Página web (p. ej. sso.empresa.com/mfa)│        │  totp-autofill host      │
│   └─ content.js                         │ Native │   ├─ accounts.json       │
│       1. ¿esta URL tiene cuenta?  ──────┼───────►│   │  (URLs, selectores)  │
│       2. busca el campo del código      │Messag- │   └─ Llavero GNOME       │
│       3. pide el código ◄───────────────┤  ing   │      (secretos TOTP)     │
│       4. lo escribe (y envía)           │        │                          │
│  background.js (puente + prefiltro)     │        │  App GTK: gestiona cuentas│
└─────────────────────────────────────────┘        └──────────────────────────┘
```

1. En la app de escritorio configuras una cuenta: **nombre**, **URL del
   formulario** y **secreto TOTP** (el mismo que escaneaste con el QR).
2. Al cargar una página, la extensión comprueba si su URL encaja con algún
   patrón configurado. Si no, no hace nada más.
3. Si encaja, busca el campo del código (o espera a que aparezca) y pide el
   código actual a la app de escritorio mediante
   [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).
4. La app lee el secreto del llavero, calcula el código y devuelve **solo los
   6–8 dígitos**. La extensión los escribe y, si lo activaste, envía el
   formulario.

Más detalle en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Requisitos

- Ubuntu 22.04 / 24.04 (o cualquier distro con GNOME/KDE y libsecret).
- Python 3.10+ con los bindings de GTK 3 y libsecret (vienen de serie en
  Ubuntu Desktop). Si te falta alguno:

  ```bash
  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-secret-1 gnome-keyring
  ```

- Un navegador Chromium (Chrome, Chromium, Brave, Edge, Vivaldi) o Firefox.

## Instalación

```bash
git clone https://github.com/tinogm97/totp-autofill.git
cd totp-autofill
./install.sh
```

El script **no necesita `sudo`**. Instala todo en tu usuario:

| Qué | Dónde |
|---|---|
| App y extensión | `~/.local/share/totp-autofill/` |
| Comando `totp-autofill` | `~/.local/bin/totp-autofill` |
| Lanzador del menú | `~/.local/share/applications/totp-autofill.desktop` |
| Registro del host nativo | `~/.config/google-chrome/NativeMessagingHosts/`, `~/.mozilla/native-messaging-hosts/`, … |

> El host solo se registra en los navegadores que hayas abierto al menos una
> vez (tiene que existir su carpeta de configuración). Si instalas un
> navegador después, vuelve a ejecutar `./install.sh`.

## Instalar la extensión

La extensión está en `~/.local/share/totp-autofill/extension` (también en la
carpeta `extension/` del repositorio).

### Chrome / Chromium / Brave / Edge

1. Abre `chrome://extensions` (o `brave://extensions`, `edge://extensions`).
2. Activa el **Modo de desarrollador** (esquina superior derecha).
3. Pulsa **Cargar descomprimida** y elige
   `~/.local/share/totp-autofill/extension`.
4. El ID de la extensión debe ser **`blnffoflcmdajflilndalbfcgeddaakd`**
   (es fijo gracias al campo `key` del manifiesto; el host nativo solo acepta
   ese ID).
5. Reinicia el navegador la primera vez para que detecte el host nativo.

### Firefox

Firefox solo instala de forma permanente extensiones firmadas. Tienes dos
opciones:

- **Probar (temporal):** `about:debugging#/runtime/this-firefox` →
  *Cargar complemento temporal…* → elige `extension/manifest.json`. Se quita
  al cerrar Firefox.
- **Permanente:** fírmala como extensión *no listada* en
  [addons.mozilla.org](https://addons.mozilla.org/developers/) con
  [`web-ext sign`](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/#web-ext-sign)
  e instala el `.xpi` resultante.

En ambos casos, ve a `about:addons` → TOTP Autofill → *Permisos* y permite el
**acceso a todos los sitios web** (en Manifest V3 Firefox no lo concede
automáticamente).

## Configurar una cuenta

### 1. Consigue el secreto TOTP

Al activar el 2FA en un servicio te muestran un código QR. Junto a él casi
siempre hay un enlace tipo **"¿No puedes escanear el código?"** o
**"Introducir la clave manualmente"** que muestra el **secreto** (algo como
`JBSW Y3DP EHPK 3PXP`). También sirve la URI completa `otpauth://totp/...` si
la tienes (por ejemplo, leyendo el QR con `zbarimg`).

> Consejo: escanea el QR con el móvil **y** guarda el secreto en TOTP
> Autofill. Así ambos generan los mismos códigos y tienes respaldo.

Si ya tenías el 2FA activado y no guardaste el secreto, normalmente tendrás
que desactivarlo y volver a activarlo (o "cambiar la app de autenticación")
desde los ajustes de seguridad del servicio.

### 2. Añádela en la app

Abre **TOTP Autofill** desde el menú de aplicaciones y pulsa **+**:

![Diálogo de cuenta](docs/screenshot-edit.png)

| Campo | Descripción |
|---|---|
| **Nombre** | Descriptivo, p. ej. `VPN Empresa`. |
| **URL del formulario** | Dirección de la página que pide el código. Admite `*`. Ver [Patrones de URL](#patrones-de-url). |
| **Secreto** | Secreto Base32 o URI `otpauth://`. Con URI se rellenan solos nombre, dígitos, periodo y algoritmo. |
| **Selector CSS** | *Opcional.* Solo si la detección automática no encuentra el campo. |
| **Enviar automáticamente** | Pulsa el botón del formulario tras escribir el código. |
| **Opciones avanzadas** | Dígitos (6–8), periodo (30 s) y algoritmo (SHA1). Cámbialos solo si el servicio lo indica. |

**¿Cómo sé la URL del formulario?** Inicia sesión en el servicio hasta la
pantalla del código y copia la barra de direcciones. Suele convenir cambiar
la parte variable por `*`, por ejemplo `https://login.empresa.com/mfa/*`.

## Patrones de URL

- `*` significa "cualquier cosa" (incluido nada). El resto de caracteres,
  incluidos `.` y `?`, se comparan literalmente.
- Si no pones esquema (`https://`), vale cualquiera.
- Si el patrón **no** contiene `?` ni `#`, se ignoran la *query* y el
  *fragmento* de la URL.
- No distingue mayúsculas y minúsculas.

| Patrón | Encaja | No encaja |
|---|---|---|
| `https://sso.empresa.com/mfa` | `https://sso.empresa.com/mfa?next=/home` | `https://sso.empresa.com/mfa/paso2` |
| `https://sso.empresa.com/mfa*` | `…/mfa`, `…/mfa/paso2` | `https://otra.com/mfa` |
| `https://*.empresa.com/2fa` | `https://vpn.empresa.com/2fa` | `https://empresa.com.malo.com/2fa` ✱ |
| `github.com/sessions/two-factor*` | `https://github.com/sessions/two-factor/app` | `https://gitlab.com/…` |
| `https://app.com/login?step=otp*` | `https://app.com/login?step=otp&x=1` | `https://app.com/login?step=pwd` |

✱ Cuidado con los comodines demasiado amplios: `https://*empresa.com/*`
**sí** encajaría con `https://malaempresa.com/`. Escribe el dominio lo más
concreto posible. La app de escritorio nunca entrega un código si la URL real
de la página no encaja con el patrón de la cuenta.

## Detección del campo del código

Sin selector, la extensión prueba, por este orden:

1. Un campo con `autocomplete="one-time-code"` (el estándar).
2. Un grupo de tantas cajas de 1 carácter como dígitos tenga el código.
3. Un campo cuyo nombre, id, placeholder, etiqueta o `aria-label` hable de
   *otp, 2fa, mfa, código, code, token, verificación…*.
4. El único campo visible cuyo `maxlength` coincide con el número de dígitos.

Si el formulario aparece más tarde (por ejemplo tras meter la contraseña en
la misma página), la extensión sigue vigilando la página y lo rellena en
cuanto aparece.

**Selector propio:** si no detecta el campo, haz clic derecho sobre él →
*Inspeccionar* → clic derecho en el `<input>` de DevTools → *Copiar → Copiar
selector*, y pégalo en el campo **Selector CSS**. Si el selector encaja con
varios campos, se escribe un dígito en cada uno.

## Uso diario

- **Automático:** basta con abrir la página. El código se escribe solo
  (como máximo dos veces por página, para evitar bucles si el servicio lo
  rechaza). Si al código le quedan menos de 3 s de validez, espera al
  siguiente.
- **Popup:** pulsa el icono de la extensión para ver si está conectada con la
  app y rellenar el código manualmente (útil si lo borraste o falló).
- **Atajo:** `Alt+Shift+2` rellena el código en la página actual. Puedes
  cambiarlo en `chrome://extensions/shortcuts`.
- **App de escritorio:** muestra todos los códigos con su cuenta atrás y
  permite copiarlos al portapapeles.

## Línea de comandos

```bash
totp-autofill                      # abre la app gráfica
totp-autofill list                 # lista las cuentas
totp-autofill add "GitHub" "github.com/sessions/two-factor*" --auto-submit
                                   # pide el secreto sin mostrarlo
totp-autofill add "VPN" "https://vpn.empresa.com/mfa*" \
    --uri "otpauth://totp/Empresa:yo?secret=...&issuer=Empresa"
totp-autofill code GitHub          # 123456  (válido 17s)
totp-autofill code GitHub -q | xclip -sel clip
totp-autofill delete GitHub
totp-autofill install-browser --host-path ~/.local/share/totp-autofill/totp-autofill-host
totp-autofill uninstall-browser
```

`totp-autofill <comando> --help` muestra todas las opciones.

## Seguridad

**Qué protege:**

- Los secretos TOTP están en el **llavero del sistema** (cifrado con tu
  contraseña de sesión). `accounts.json` solo tiene nombres, URLs y
  selectores, con permisos `600`.
- La extensión **nunca recibe secretos**, solo el código del momento.
- La URL de la página la aporta el navegador (`sender.url`), no la página. La
  app de escritorio vuelve a comprobar que la URL encaja con el patrón de la
  cuenta antes de generar el código, así que una web maliciosa no puede
  obtener códigos de otra cuenta.
- El host nativo solo es accesible para la extensión con ID
  `blnffoflcmdajflilndalbfcgeddaakd` (Chromium) o
  `totp-autofill@tinogm97.github.io` (Firefox).

**Qué no protege:**

- Quien tenga acceso a tu sesión **desbloqueada** puede generar códigos, igual
  que podría abrir tu gestor de contraseñas.
- Un malware que se ejecute con tu usuario puede leer el llavero.
- Debilita notablemente el 2FA si la contraseña también está guardada en el
  mismo equipo. Para cuentas críticas (banca, correo, gestor de contraseñas
  principal) valora no usarlo.

## Solución de problemas

**El popup dice "Specified native messaging host not found".**
Vuelve a ejecutar `./install.sh` con el navegador ya abierto alguna vez, y
reinicia el navegador por completo. Comprueba que existe el fichero
`~/.config/google-chrome/NativeMessagingHosts/com.github.tinogm97.totp_autofill.json`.

**"Access to the specified native messaging host is forbidden".**
La extensión tiene otro ID. Asegúrate de que el manifiesto conserva el campo
`key`. Si usas otro ID a propósito:
`totp-autofill install-browser --host-path ~/.local/share/totp-autofill/totp-autofill-host --extension-id TU_ID`.

**Chromium instalado como snap.** El confinamiento de snap no le permite
lanzar programas externos, así que Native Messaging no funciona. Usa Google
Chrome (`.deb`), Brave o Chromium de otra fuente.

**Firefox instalado como snap (el de serie en Ubuntu).** Las versiones
recientes admiten Native Messaging a través del portal del escritorio y piden
permiso la primera vez. Si no funciona, instala el Firefox `.deb` del
repositorio de Mozilla.

**No detecta el campo.** Configura el **Selector CSS** (ver
[Detección del campo](#detección-del-campo-del-código)). Si el formulario está
dentro de un `iframe` de otro dominio, el patrón debe encajar con **la URL
del iframe**, no con la de la página principal.

**"No hay secreto en el llavero".** El llavero está bloqueado o se reinició.
Abre *Contraseñas y claves* (Seahorse), desbloquea el llavero *Inicio de
sesión* y edita la cuenta para volver a introducir el secreto.

**Depurar el host a mano:**

```bash
python3 - <<'PY' | ~/.local/share/totp-autofill/totp-autofill-host | tail -c +5
import json, struct, sys
m = json.dumps({"type": "ping"}).encode()
sys.stdout.buffer.write(struct.pack("=I", len(m)) + m)
PY
# {"ok": true, "version": "1.0.0"}
```

## Desarrollo

```
totp-autofill/
├── totp_autofill/             # Paquete Python (app de escritorio)
│   ├── totp.py                #   RFC 6238 + parser otpauth://
│   ├── store.py               #   cuentas, patrones de URL, llavero
│   ├── native_host.py         #   protocolo Native Messaging
│   ├── browser_integration.py #   registro del host en navegadores
│   ├── gui.py                 #   interfaz GTK 3
│   └── cli.py                 #   línea de comandos
├── extension/                 # Extensión Manifest V3 (Chrome + Firefox)
│   ├── background.js          #   puente con el host nativo + prefiltro
│   ├── content.js             #   detección y rellenado del campo
│   └── popup.{html,css,js}    #   estado y relleno manual
├── examples/demo-2fa.html     # página demo para probar
├── tests/                     # unitarios, paridad JS↔Python, e2e
├── data/                      # icono y .desktop
├── scripts/make_icons.py      # generación de iconos
├── install.sh / uninstall.sh
└── docs/ARQUITECTURA.md
```

Ejecutar sin instalar:

```bash
python3 -m totp_autofill            # GUI
python3 -m totp_autofill list       # CLI
```

Tests:

```bash
python3 -m unittest discover -s tests -v   # unitarios (incluye vectores RFC 6238)
node tests/url_matches_parity.mjs           # patrones JS y Python se comportan igual
tests/e2e/run.sh                            # extensión + host reales en Chromium headless
```

El test end-to-end necesita Node ≥ 18 y un Chromium de Playwright
(`npx playwright install chromium`); Chrome de marca ya no permite cargar
extensiones por línea de comandos.

Probar la demo a mano:

```bash
python3 -m http.server 8765 --directory examples
totp-autofill add "Demo" "http://localhost:8765/demo-2fa.html" \
    --secret JBSWY3DPEHPK3PXP --auto-submit
# abre http://localhost:8765/demo-2fa.html  (o ?split=1 para 6 cajas)
```

Tras cambiar la extensión, recárgala en `chrome://extensions`. Tras cambiar el
código Python, vuelve a ejecutar `./install.sh`.

## Desinstalar

```bash
./uninstall.sh           # quita la app; conserva cuentas y secretos
./uninstall.sh --purge   # además borra cuentas y secretos del llavero
```

Después quita la extensión del navegador.

## Licencia

[MIT](LICENSE) © Celestino Armando García Meca
