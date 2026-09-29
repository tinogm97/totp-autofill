/* Popup: estado de la conexión con la app y relleno manual. */

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

function setStatus(text, kind) {
  $("status").textContent = text;
  $("status").className = `status ${kind ?? ""}`;
}

async function activeTab() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function fillWith(accountId) {
  const tab = await activeTab();
  try {
    const res = await api.tabs.sendMessage(tab.id, { type: "fill", id: accountId });
    $("message").textContent = res?.ok ? "Código introducido ✔" : res?.error ?? "No se pudo rellenar";
    if (res?.ok) setTimeout(() => window.close(), 700);
  } catch (err) {
    $("message").textContent = err.message;
  }
}

async function init() {
  const status = await api.runtime.sendMessage({ type: "status" });
  if (!status?.ok) {
    setStatus(
      "No se encuentra la app de escritorio. Ejecuta ./install.sh y reinicia el navegador. " +
        `(${status?.error ?? "sin respuesta"})`,
      "error",
    );
    return;
  }
  setStatus(`Conectado a la app v${status.version} · ${status.accounts} cuenta(s)`, "ok");

  const tab = await activeTab();
  let res = null;
  try {
    res = await api.tabs.sendMessage(tab.id, { type: "list" });
  } catch {
    // Ningún frame de la página tiene cuentas asociadas.
  }
  if (!res?.accounts?.length) {
    $("message").textContent = "Esta página no coincide con ninguna cuenta configurada.";
    return;
  }

  $("accounts").hidden = false;
  for (const account of res.accounts) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = account.name;
    if (account.username) {
      const user = document.createElement("small");
      user.textContent = account.username;
      name.append(user);
    }
    if (account.id === res.suggested) li.classList.add("suggested");
    const button = document.createElement("button");
    button.textContent = "Rellenar";
    button.addEventListener("click", () => fillWith(account.id));
    li.append(name, button);
    $("account-list").append(li);
  }
}

init();
