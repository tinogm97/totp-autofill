/*
 * Content script de TOTP Autofill.
 *
 * 1. Pregunta al script de fondo si la URL actual tiene alguna cuenta 2FA
 *    configurada en la app de escritorio.
 * 2. Si la tiene, busca el campo del código (selector configurado o
 *    detección automática) y espera a que aparezca si aún no está.
 * 3. Pide el código TOTP y lo escribe; opcionalmente envía el formulario.
 */
(() => {
  if (window.__totpAutofillLoaded) return;
  window.__totpAutofillLoaded = true;

  const api = globalThis.browser ?? globalThis.chrome;

  // Rellenos automáticos máximos por URL: evita bucles si la web rechaza
  // el código y vuelve a pintar el formulario. Desde el popup o con el
  // atajo de teclado siempre se puede forzar.
  const MAX_AUTO_FILLS = 2;

  const OTP_HINT =
    /(one.?time|otp|totp|2fa|mfa|two.?factor|second.?factor|verif|auth.?code|security.?code|passcode|token|c[oó]digo|code|pin)/i;
  const NOT_OTP =
    /(user|e-?mail|login|search|phone|tel[eé]fono|zip|postal|captcha|coupon|promo|card|cvv|cvc|country)/i;
  const TEXT_TYPES = new Set(["", "text", "tel", "number", "password"]);

  let accounts = [];
  let currentUrl = null;
  let autoFills = 0;
  let filledElement = null;
  let busy = false;
  let observer = null;
  let debounce = null;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------------------------------------------------------------- campos

  function isVisible(el) {
    if (!el.isConnected || el.disabled || el.readOnly) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const style = getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none" && style.opacity !== "0";
  }

  function textInputs() {
    return [...document.querySelectorAll("input")].filter(
      (el) => TEXT_TYPES.has(el.type) && isVisible(el),
    );
  }

  function describe(el) {
    const labels = [...(el.labels ?? [])].map((l) => l.textContent).join(" ");
    return [
      el.name, el.id, el.placeholder, el.className, labels,
      el.getAttribute("aria-label"), el.getAttribute("data-testid"),
    ].join(" ");
  }

  /** Grupo de N cajas de 1 carácter (formularios de código "partido"). */
  function findSplitInputs(inputs, digits) {
    const groups = new Map();
    for (const el of inputs.filter((i) => i.maxLength === 1)) {
      const key = el.parentElement?.parentElement ?? el.parentElement;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(el);
    }
    return [...groups.values()].find((g) => g.length === digits) ?? null;
  }

  /**
   * Localiza el campo del código. Devuelve una lista de inputs: uno solo
   * (campo normal) o varios (una caja por dígito). `null` si no hay.
   */
  function findField(account) {
    if (account.selector) {
      let found = [];
      try {
        found = [...document.querySelectorAll(account.selector)].filter(isVisible);
      } catch {
        console.warn("[TOTP Autofill] Selector CSS no válido:", account.selector);
      }
      return found.length ? found : null;
    }

    const inputs = textInputs();

    const oneTime = inputs.filter((el) => el.autocomplete === "one-time-code");
    if (oneTime.length === 1) return oneTime;
    if (oneTime.length === account.digits) return oneTime;

    const split = findSplitInputs(inputs, account.digits);
    if (split) return split;

    const hinted = inputs.find((el) => {
      const text = describe(el);
      return OTP_HINT.test(text) && !NOT_OTP.test(text) &&
        (el.maxLength <= 0 || el.maxLength >= account.digits);
    });
    if (hinted) return [hinted];

    const sized = inputs.filter((el) => el.maxLength === account.digits);
    if (sized.length === 1) return sized;

    return null;
  }

  // ----------------------------------------------------------- rellenado

  /** Asigna el valor de forma que React/Vue/Angular detecten el cambio. */
  function setValue(el, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    el.focus();
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function requestCode(account) {
    let res = await api.runtime.sendMessage({ type: "code", id: account.id });
    // Si al código le quedan menos de 3 s, esperamos al siguiente.
    if (res?.ok && res.remaining < 3) {
      await sleep((res.remaining + 0.5) * 1000);
      res = await api.runtime.sendMessage({ type: "code", id: account.id });
    }
    if (!res?.ok) throw new Error(res?.error ?? "Sin respuesta de la app de escritorio");
    return res.code;
  }

  function submit(el) {
    const form = el.form ?? el.closest("form");
    if (form) {
      const button = [...form.querySelectorAll(
        'button[type="submit"], input[type="submit"], button:not([type])',
      )].find(isVisible);
      if (button) button.click();
      else form.requestSubmit();
      return;
    }
    for (const type of ["keydown", "keypress", "keyup"]) {
      el.dispatchEvent(new KeyboardEvent(type, {
        key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true,
      }));
    }
  }

  async function fill(account, { force = false } = {}) {
    const fields = findField(account);
    if (!fields) return { ok: false, error: "No se encontró el campo del código en la página" };
    const first = fields[0];
    if (!force && (first === filledElement || fields.some((f) => f.value))) {
      return { ok: false, error: "El campo ya está relleno" };
    }

    const code = await requestCode(account);
    if (fields.length === 1) {
      setValue(first, code);
    } else {
      fields.forEach((el, i) => setValue(el, code[i] ?? ""));
    }
    filledElement = first;

    if (account.autoSubmit) setTimeout(() => submit(fields[fields.length - 1]), 400);
    return { ok: true };
  }

  // ------------------------------------------------------------- ciclo

  async function refreshAccounts() {
    if (location.href === currentUrl) return;
    currentUrl = location.href;
    autoFills = 0;
    filledElement = null;
    try {
      const res = await api.runtime.sendMessage({ type: "match" });
      accounts = res?.ok ? res.accounts : [];
    } catch {
      accounts = [];
    }
    if (accounts.length) startObserving();
    else stopObserving();
  }

  async function tryAutoFill() {
    if (busy || !accounts.length || autoFills >= MAX_AUTO_FILLS) return;
    busy = true;
    try {
      const res = await fill(accounts[0]);
      if (res.ok) autoFills += 1;
    } catch (err) {
      console.warn("[TOTP Autofill]", err.message);
    } finally {
      busy = false;
    }
  }

  function schedule() {
    clearTimeout(debounce);
    debounce = setTimeout(tryAutoFill, 300);
  }

  function startObserving() {
    if (observer) return;
    // Los formularios de 2FA a menudo aparecen tras un paso previo (SPA),
    // así que vigilamos el DOM mientras la URL tenga cuentas asociadas.
    observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    schedule();
  }

  function stopObserving() {
    observer?.disconnect();
    observer = null;
  }

  // Cambios de URL en aplicaciones de una sola página (pushState).
  setInterval(() => {
    if (location.href !== currentUrl) refreshAccounts();
  }, 1000);

  // Peticiones del popup y del atajo de teclado.
  api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!accounts.length) return false; // otro frame responderá
    if (message?.type === "list") {
      sendResponse({ ok: true, accounts });
      return false;
    }
    if (message?.type === "fill") {
      const account = accounts.find((a) => a.id === message.id) ?? accounts[0];
      fill(account, { force: true })
        .then(sendResponse)
        .catch((err) => sendResponse({ ok: false, error: err.message }));
      return true;
    }
    return false;
  });

  refreshAccounts();
})();
