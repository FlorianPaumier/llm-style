// Install page: show LAN URL + QR, and the browser install prompt.
"use strict";

let installEvent = null;

async function load() {
  try {
    const res = await fetch("/api/app/download");
    if (!res.ok) return;
    const info = await res.json();
    const url = document.getElementById("lan-url");
    url.textContent = info.lan_urls.length
      ? `or type it in manually: ${info.primary_url}`
      : `No Wi-Fi address found — the app is at ${info.primary_url}`;
  } catch {
    document.getElementById("install-note").textContent =
      "Backend unreachable — start it with: cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0";
  }
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installEvent = e;
  const btn = document.getElementById("install-btn");
  btn.hidden = false;
  document.getElementById("install-status").textContent =
    "This browser supports one-tap install.";
});

document.getElementById("install-btn").addEventListener("click", async () => {
  if (!installEvent) return;
  installEvent.prompt();
  const { outcome } = await installEvent.userChoice;
  document.getElementById("install-status").textContent =
    outcome === "accepted" ? "Installed!" : "Maybe later.";
  installEvent = null;
  document.getElementById("install-btn").hidden = true;
});

load();
