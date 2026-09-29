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

let patternsCache = { list: [], fetchedAt: 0, error: null };

function native(message) {
  return api.runtime.sendNativeMessage(HOST, message);
}

/**
 * Misma semántica que url_matches() en totp_autofill/store.py:
 * `*` es comodín, sin esquema vale cualquiera, y si el patrón no contiene
 * `?` ni `#` se ignoran query y fragmento de la URL.
 */
function urlMatches(pattern, url) {
  pattern = pattern.trim();
  if (!pattern || !url) return false;
  if (!pattern.includes("://")) pattern = "*://" + pattern;
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
    patternsCache = { list: res.ok ? res.patterns : [], fetchedAt: Date.now(), error: res.ok ? null : res.error };
  } catch (err) {
    patternsCache = { list: [], fetchedAt: Date.now(), error: String(err?.message ?? err) };
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

async function handleMessage(message, sender) {
  // La URL se toma de `sender` (la fija el navegador), nunca del mensaje,
  // para que una página no pueda pedir el código de otra web.
  const url = sender.url ?? "";

  switch (message?.type) {
    case "match":
      return { ok: true, accounts: await matchAccounts(url) };
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
