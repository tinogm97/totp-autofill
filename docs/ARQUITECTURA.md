# Arquitectura

TOTP Autofill tiene dos piezas que se comunican por
[Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging):

| Pieza | Tecnología | Responsabilidad |
|---|---|---|
| **App de escritorio** (`totp_autofill/`) | Python 3, GTK 3, libsecret | Guardar cuentas y secretos, generar códigos, GUI y CLI. |
| **Extensión** (`extension/`) | WebExtension Manifest V3 | Detectar la página y el campo, pedir el código y escribirlo. |

La división responde a una idea: **el secreto no sale nunca del proceso de
escritorio**. El navegador solo ve códigos de un solo uso.

## Flujo completo

```
content.js                background.js                 host (Python)
    │  {type: match}           │                              │
    ├─────────────────────────►│ ¿patrones en caché (15 s)?   │
    │                          ├── no ── {type: patterns} ───►│ lee accounts.json
    │                          │◄──────── [patrones] ─────────┤
    │                          │ ¿la URL encaja con alguno?   │
    │                          ├── sí ── {type: match, url} ─►│ filtra cuentas
    │◄──── [cuentas sin secreto]◄─────────────────────────────┤
    │ busca el campo / espera (MutationObserver)              │
    │  {type: code, id}        │                              │
    ├─────────────────────────►├── {type: code, id, url} ────►│ ¿url encaja con la cuenta?
    │                          │                              │ secreto ← llavero
    │◄──── {code, remaining} ──┤◄─────────────────────────────┤ TOTP(secreto, ahora)
    │ escribe + envía (opcional)                              │
```

- `url` la pone **background.js a partir de `sender.url`**, que rellena el
  navegador. El content script no puede falsificarla.
- El prefiltro de patrones evita lanzar el proceso Python en cada página que
  visitas: solo se consulta al host cuando la URL encaja con algún patrón (y
  para refrescar la caché cada 15 s como mucho).

## Protocolo del host

Cada mensaje es JSON en UTF-8 precedido de su longitud en 4 bytes (orden
nativo). El navegador lanza `totp-autofill-host` y le habla por stdin/stdout.

| Petición | Respuesta |
|---|---|
| `{"type": "ping"}` | `{"ok": true, "version": "1.0.0"}` |
| `{"type": "patterns"}` | `{"ok": true, "patterns": ["https://…/mfa*"]}` |
| `{"type": "match", "url": U}` | `{"ok": true, "accounts": [{"id", "name", "selector", "autoSubmit", "digits"}]}` |
| `{"type": "code", "id": I, "url": U}` | `{"ok": true, "code": "123456", "remaining": 17}` |
| cualquier error | `{"ok": false, "error": "mensaje"}` |

`code` falla si el patrón de la cuenta `I` no encaja con `U`.

## Almacenamiento

- **`~/.config/totp-autofill/accounts.json`** (permisos `600`, escritura
  atómica con `os.replace`):

  ```json
  {
    "version": 1,
    "accounts": [
      {
        "name": "VPN Empresa",
        "url_pattern": "https://sso.empresa.com/mfa*",
        "selector": "",
        "auto_submit": false,
        "digits": 6,
        "period": 30,
        "algorithm": "SHA1",
        "id": "3f1c…"
      }
    ]
  }
  ```

- **Llavero** (libsecret): un elemento por cuenta con el esquema
  `com.github.tinogm97.TotpAutofill` y el atributo `account_id`. Se ve en
  Seahorse como *"TOTP Autofill: <nombre>"*.

## Patrones de URL

Implementados dos veces con la misma semántica:
`url_matches()` en `store.py` (la que decide) y `urlMatches()` en
`background.js` (solo prefiltro). `tests/url_matches_parity.mjs` comprueba que
coinciden.

1. Solo `*` es comodín (→ `.*`); todo lo demás se escapa.
2. Sin `://` en el patrón se antepone `*://`.
3. Sin `?` ni `#` en el patrón, se quitan query y fragmento de la URL.
4. Comparación sin distinguir mayúsculas, anclada al principio y al final.

## Detección del campo (`content.js`)

`findField(account)` devuelve una lista de `<input>` (uno, o uno por dígito):

1. `account.selector` si existe (todas las coincidencias visibles).
2. `autocomplete="one-time-code"`.
3. Grupo de `digits` inputs con `maxlength=1` que comparten contenedor.
4. Input cuyo texto descriptivo encaja con `OTP_HINT` y no con `NOT_OTP`.
5. Único input visible con `maxlength == digits`.

El valor se asigna con el *setter* nativo de `HTMLInputElement.value` y se
emiten `input` y `change`, para que frameworks como React detecten el cambio.

Protecciones contra efectos no deseados:

- No sobrescribe un campo que ya tiene valor (salvo relleno manual).
- Máximo 2 rellenos automáticos por URL, para no entrar en bucle de envíos
  si el servicio rechaza el código y vuelve a pintar el formulario.
- Si al código le quedan < 3 s, espera al siguiente periodo.

## ID fijo de la extensión

Chrome calcula el ID de una extensión desempaquetada a partir de la ruta,
salvo que el manifiesto incluya `key` (clave pública RSA). Con `key`, el ID es
`sha256(clave)[:32]` traducido a `a-p`: `blnffoflcmdajflilndalbfcgeddaakd`.
Eso permite que `install.sh` escriba `allowed_origins` sin preguntar nada.
La clave privada no se necesita (ni se guarda): solo haría falta para
empaquetar un `.crx`.

## Decisiones descartadas

- **Teclear el código con `xdotool` en la ventana activa:** funciona fuera del
  navegador, pero no puede ver la URL real ni el campo, y no funciona en
  Wayland. La extensión es más precisa y segura.
- **Guardar los secretos en `chrome.storage`:** quedarían en el perfil del
  navegador en claro y accesibles a cualquier código de la extensión.
- **Dependencias como `pyotp` o `keyring`:** TOTP son 10 líneas con `hmac`, y
  libsecret ya está en Ubuntu vía `gi`; así la instalación no necesita `pip`.
