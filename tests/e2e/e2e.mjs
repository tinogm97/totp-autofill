// Lo ejecuta tests/e2e/run.sh, que prepara el entorno.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { readdirSync } from "node:fs";

const { ROOT, PROFILE, PORT, SECRET, SPLIT } = process.env;
const EXT = `${ROOT}/extension`;
const EXT_ID = "blnffoflcmdajflilndalbfcgeddaakd";

// Último Chromium instalado por Playwright.
const cache = `${process.env.HOME}/.cache/ms-playwright`;
const build = readdirSync(cache).filter((d) => /^chromium-\d+$/.test(d))
  .sort((a, b) => a.split("-")[1] - b.split("-")[1]).at(-1);
if (!build) throw new Error("Instala Chromium con: npx playwright install chromium");

const ctx = await chromium.launchPersistentContext(PROFILE, {
  executablePath: `${cache}/${build}/chrome-linux64/chrome`,
  headless: true,
  args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
});
if (!ctx.serviceWorkers().length) await ctx.waitForEvent("serviceworker");

const page = await ctx.newPage();
await page.goto(`http://localhost:${PORT}/demo-2fa.html${SPLIT ? "?split=1" : ""}`);
await page.click("button[type=submit]"); // paso 1: usuario y contraseña
await page.waitForSelector("#received", { timeout: 15000 }); // autocompletado + envío
const received = await page.textContent("#received");
const expected = execFileSync("python3", ["-c",
  `from totp_autofill.totp import totp; print(totp("${SECRET}"))`]).toString().trim();

const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${EXT_ID}/popup.html`);
await popup.waitForFunction(() => !document.getElementById("status").textContent.includes("Conectando"));
const status = await popup.textContent("#status");
await ctx.close();

const ok = received === expected && status.startsWith("Conectado");
console.log(`${ok ? "OK" : "FALLO"} [${SPLIT ? "6 cajas" : "campo único"}] ` +
  `recibido=${received} esperado=${expected} · popup: ${status}`);
process.exit(ok ? 0 : 1);
