// Comprueba que urlMatches() de extension/background.js da los mismos
// resultados que url_matches() de Python. Uso: node tests/url_matches_parity.mjs
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const src = readFileSync(new URL("../extension/background.js", import.meta.url), "utf8");
const fn = src.match(/function urlMatches[\s\S]*?\n}\n/)[0];
const urlMatches = new Function(`${fn}; return urlMatches;`)();

const cases = [
  ["https://login.acme.com/mfa*", "https://login.acme.com/mfa/verify"],
  ["https://*.acme.com/2fa", "https://sso.acme.com/2fa"],
  ["https://login.acme.com/mfa*", "https://evil.com/login.acme.com/mfa"],
  ["https://acme.com/2fa", "https://acme.com/2fa?next=/#x"],
  ["https://acme.com/2fa?step=otp", "https://acme.com/2fa?step=login"],
  ["https://acme.com/2fa?step=otp*", "https://acme.com/2fa?step=otp&x=1"],
  ["acme.com/2fa", "https://ACME.com/2fa"],
  ["https://acme.com/*", "https://acmeXcom/2fa"],
  ["http://localhost:8765/*", "http://localhost:8765/demo-2fa.html"],
  ["*", "https://anything.org/x"],
  ["localhost:4200", "http://localhost:4200/login"],
  ["localhost:4200", "http://localhost:4200/"],
  ["localhost:4200", "http://localhost:42000/login"],
  ["http://localhost:4200", "http://localhost:4200/auth#/otp"],
  ["", "https://acme.com"],
];

const py = JSON.parse(execFileSync("python3", ["-c", `
import json, sys
from totp_autofill.store import url_matches
print(json.dumps([url_matches(p, u) for p, u in json.loads(sys.argv[1])]))
`, JSON.stringify(cases)], { cwd: new URL("..", import.meta.url) }));

let failures = 0;
cases.forEach(([p, u], i) => {
  const js = urlMatches(p, u);
  if (js !== py[i]) {
    failures++;
    console.error(`DIFERENCIA: ${p} ~ ${u}: js=${js} py=${py[i]}`);
  }
});
console.log(failures ? `${failures} diferencias` : `OK: ${cases.length} casos coinciden`);
process.exit(failures ? 1 : 0);
