/*
 * Service worker / script de fondo de TOTP Autofill.
 *
 * Hace de puente entre los content scripts (páginas web) y la app de
 * escritorio, con la que habla mediante Native Messaging. Los secretos TOTP
 * nunca llegan a la extensión: solo los códigos de 6-8 dígitos ya generados.
 */

const api = globalThis.browser ?? globalThis.chrome;

const HOST = "com.github.tinogm97.totp_autofill";
const PATTERNS_TTL_MS = 15_000;

let patternsCache = { list: [], users: [], fetchedAt: 0, error: null };

function native(message) {
  return api.runtime.sendNativeMessage(HOST, message);
}

/**
 * Misma semántica que url_matches() en totp_autofill/store.py:
 * `*` es comodín, sin esquema vale cualquiera, un host solo abarca todo el
 * sitio, y si el patrón no contiene `?` ni `#` se ignoran query y fragmento.
 */
function urlMatches(pattern, url) {
  pattern = pattern.trim();
  if (!pattern || !url) return false;
  if (!pattern.includes("://")) pattern = "*://" + pattern;
  if (!pattern.split("://")[1].includes("/")) pattern += "/*";
  if (!pattern.includes("?") && !pattern.includes("#")) {
    try {
      const u = new URL(url);
      url = u.origin + u.pathname;
    } catch {
      return false;
    }
  }
  const escaped = pattern
    .split("*")
    .map((part) => part.replace(/[.+?^${}()|[\]\\/]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${escaped}$`, "i").test(url);
}

async function getPatterns(force = false) {
  const fresh = Date.now() - patternsCache.fetchedAt < PATTERNS_TTL_MS;
  if (!force && fresh) return patternsCache.list;
  try {
    const res = await native({ type: "patterns" });
    patternsCache = {
      list: res.ok ? res.patterns : [],
      users: res.ok ? res.users ?? [] : [],
      fetchedAt: Date.now(),
      error: res.ok ? null : res.error,
    };
  } catch (err) {
    patternsCache = { list: [], users: [], fetchedAt: Date.now(), error: String(err?.message ?? err) };
  }
  return patternsCache.list;
}

/** Cuentas (sin secretos) configuradas para `url`. */
async function matchAccounts(url) {
  const patterns = await getPatterns();
  if (!patterns.some((p) => urlMatches(p, url))) return [];
  const res = await native({ type: "match", url });
  return res.ok ? res.accounts : [];
}

// ------------------------------------------------ usuario que inicia sesión
//
// Cuando varias cuentas comparten URL (p. ej. localhost:4200), hay que saber
// con qué usuario se está entrando. El content script informa de lo que se
// escribe en campos de usuario/email; aquí solo se guarda si coincide con un
// usuario configurado, en memoria de sesión (storage.session) y por pestaña
// (no por origen), para que sirva aunque el paso del código sea otra página
// u otro dominio (p. ej. un SSO).

const userKey = (sender) => (sender.tab?.id === undefined ? null : `user:${sender.tab.id}`);

async function rememberUser(value, sender) {
  const key = userKey(sender);
  if (!key || !value) return;
  await getPatterns();
  const user = patternsCache.users.find((u) => u.toLowerCase() === value.trim().toLowerCase());
  if (user) await api.storage.session.set({ [key]: user });
}

async function rememberedUser(sender) {
  const key = userKey(sender);
  if (!key) return null;
  return (await api.storage.session.get(key))[key] ?? null;
}

api.tabs.onRemoved.addListener((tabId) => {
  api.storage.session.remove(`user:${tabId}`);
});
// ------------------------------------------------------------- mensajes

async function handleMessage(message, sender) {
  // La URL se toma de `sender` (la fija el navegador), nunca del mensaje,
  // para que una página no pueda pedir el código de otra web.
  const url = sender.url ?? "";

  switch (message?.type) {
    case "match":
      return {
        ok: true,
        accounts: await matchAccounts(url),
        rememberedUser: await rememberedUser(sender),
      };
    case "user":
      await rememberUser(String(message.value ?? ""), sender);
      return { ok: true };
    case "code":
      return await native({ type: "code", id: message.id, url });
    case "status": {
      try {
        const ping = await native({ type: "ping" });
        await getPatterns(true);
        return { ok: true, version: ping.version, accounts: patternsCache.list.length };
      } catch (err) {
        return { ok: false, error: String(err?.message ?? err) };
      }
    }
    default:
      return { ok: false, error: `Mensaje desconocido: ${message?.type}` };
  }
}

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then(sendResponse)
    .catch((err) => sendResponse({ ok: false, error: String(err?.message ?? err) }));
  return true; // respuesta asíncrona
});

api.commands.onCommand.addListener(async (command) => {
  if (command !== "fill-code") return;
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  if (tab?.id !== undefined) {
    api.tabs.sendMessage(tab.id, { type: "fill" }).catch(() => {});
  }
});
