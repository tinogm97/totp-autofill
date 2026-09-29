// Lo ejecuta tests/e2e/run.sh, que prepara el entorno.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { readdirSync } from "node:fs";

const { ROOT, PROFILE, PORT, SECRET_ANA, SECRET_LUIS } = process.env;
const EXT = `${ROOT}/extension`;
const EXT_ID = "blnffoflcmdajflilndalbfcgeddaakd";
const DEMO = `http://localhost:${PORT}/demo-2fa.html`;

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

const totp = (secret) => execFileSync("python3", ["-c",
  `from totp_autofill.totp import totp; print(totp("${secret}"))`]).toString().trim();

/** Inicia sesión con `email` y devuelve el código que recibe la demo. */
async function login(query, email, { choose } = {}) {
  const page = await ctx.newPage();
  await page.goto(`${DEMO}${query}`);
  await page.fill("input[name=username]", email);
  await page.click("button[type=submit]");
  if (choose) {
    // Selector de cuentas: Playwright atraviesa el shadow DOM abierto.
    await page.click(`#totp-autofill-chooser >> text=Demo ${choose}`);
  }
  await page.waitForSelector("#received", { timeout: 15000 });
  const received = await page.textContent("#received");
  await page.close();
  return received;
}

const cases = [
  ["SPA, ana → código de Ana", "", "ana@demo.com", SECRET_ANA],
  ["SPA 6 cajas, luis → código de Luis", "?split=1", "luis@demo.com", SECRET_LUIS],
  ["Multipágina, luis → código de Luis", "?multipage=1", "LUIS@demo.com", SECRET_LUIS],
  ["Multipágina, ana → código de Ana", "?multipage=1", "ana@demo.com", SECRET_ANA],
  ["Usuario desconocido → selector → Luis", "", "otro@demo.com", SECRET_LUIS, "Luis"],
];

let failed = 0;
for (const [label, query, email, secret, choose] of cases) {
  let received;
  try {
    received = await login(query, email, { choose });
  } catch (err) {
    received = `error: ${err.message.split("\n")[0]}`;
  }
  const expected = totp(secret);
  const ok = received === expected;
  failed += ok ? 0 : 1;
  console.log(`${ok ? "OK   " : "FALLO"} ${label}: recibido=${received} esperado=${expected}`);
}

const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${EXT_ID}/popup.html`);
await popup.waitForFunction(() => !document.getElementById("status").textContent.includes("Conectando"));
const status = await popup.textContent("#status");
const popupOk = status.startsWith("Conectado");
failed += popupOk ? 0 : 1;
console.log(`${popupOk ? "OK   " : "FALLO"} popup: ${status}`);

await ctx.close();
process.exit(failed ? 1 : 0);
