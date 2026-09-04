// Settings page: city, model, Ollama URL.
"use strict";

const $ = (id) => document.getElementById(id);

async function load() {
  const res = await fetch("/api/settings");
  const s = await res.json();
  $("city").value = s.city;
  $("model").value = s.model;
  $("ollama-url").value = s.ollama_url;
}

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("status").textContent = "Saving…";
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city: $("city").value.trim() || null,
      model: $("model").value.trim() || null,
      ollama_url: $("ollama-url").value.trim() || null,
    }),
  });
  $("status").textContent = res.ok ? "Saved." : "Failed to save.";
});

load();
