// Settings page: city, models, Ollama URL, and the people in the household.
// A field you don't touch keeps its stored value; clearing one you
// edited resets it to the default.
"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

async function load() {
  const res = await fetch("/api/settings");
  const s = await res.json();
  // Show the effective value as a placeholder: an untouched blank field
  // means "keep this", not "reset".
  $("city").placeholder = s.city;
  $("model").placeholder = s.model;
  $("vision-model").placeholder = s.vision_model;
  $("ollama-url").placeholder = s.ollama_url;
}

// Only fields the user actually edited are sent.
const edited = new Set();
for (const id of ["city", "model", "vision-model", "ollama-url"]) {
  $(id).addEventListener("input", () => edited.add(id));
}

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("status").textContent = "Saving…";
  const keyBy = {
    city: "city",
    model: "model",
    "vision-model": "vision_model",
    "ollama-url": "ollama_url",
  };
  const payload = {};
  for (const id of edited) {
    const value = $(id).value.trim();
    payload[keyBy[id]] = value === "" ? null : value; // cleared = default
  }
  if (Object.keys(payload).length === 0) {
    $("status").textContent = "Nothing to change.";
    return;
  }
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    $("status").textContent = "Saved.";
    edited.clear();
    for (const id of Object.keys(keyBy)) $(id).value = "";
    load();
  } else {
    $("status").textContent = "Failed to save.";
  }
});

// --- People (personas) -------------------------------------------------

async function refreshPeople() {
  const people = await api("/api/personas");
  const list = $("people-list");
  list.innerHTML = "";
  for (const p of people) {
    const li = document.createElement("li");

    const name = document.createElement("span");
    name.textContent = Persona.symbol(p) + p.name;
    li.append(name);

    if (p.description) {
      const desc = document.createElement("span");
      desc.className = "muted";
      desc.textContent = p.description;
      li.append(desc);
    }

    // Gender steers the stylist's phrasing and silhouettes; change it
    // right here — the PUT follows this page's merge semantics.
    const gender = document.createElement("select");
    gender.className = "person-gender";
    gender.setAttribute("aria-label", `Gender for ${p.name}`);
    for (const [value, label] of [
      ["unspecified", "gender: —"],
      ["male", "gender: male"],
      ["female", "gender: female"],
    ]) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      if ((p.gender || "unspecified") === value) opt.selected = true;
      gender.append(opt);
    }
    gender.onchange = async () => {
      try {
        await api(`/api/personas/${p.id}`, {
          method: "PUT",
          body: JSON.stringify({ gender: gender.value }),
        });
        await refreshPeople();
      } catch (err) {
        $("person-error").textContent = err.message;
      }
    };
    li.append(" ", gender);

    const rename = document.createElement("button");
    rename.textContent = "Rename";
    rename.onclick = async () => {
      const value = prompt("New name", p.name);
      if (!value || !value.trim()) return;
      try {
        await api(`/api/personas/${p.id}`, {
          method: "PUT",
          body: JSON.stringify({ name: value.trim() }),
        });
        await refreshPeople();
      } catch (err) {
        $("person-error").textContent = err.message;
      }
    };
    li.append(" ", rename);

    const describe = document.createElement("button");
    describe.textContent = p.description ? "Edit notes" : "Add notes";
    describe.title = "Styling notes the LLM stylist must respect (e.g. 'no hats — they don't suit me')";
    describe.onclick = async () => {
      const value = prompt(
        "Styling notes for the stylist (blank = none)\ne.g. “no hats — they don't suit me; prefers bold colors”",
        p.description || ""
      );
      if (value === null) return; // cancelled
      try {
        await api(`/api/personas/${p.id}`, {
          method: "PUT",
          body: JSON.stringify({ description: value === "" ? null : value }),
        });
        await refreshPeople();
      } catch (err) {
        $("person-error").textContent = err.message;
      }
    };
    li.append(" ", describe);

    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "Delete";
    del.onclick = async () => {
      if (!confirm(`Delete ${p.name}? Their wardrobe must be empty first.`)) return;
      try {
        await api(`/api/personas/${p.id}`, { method: "DELETE" });
        await refreshPeople();
      } catch (err) {
        // 400 = last persona, 409 = wardrobe not empty.
        $("person-error").textContent = err.message;
      }
    };
    li.append(" ", del);
    list.append(li);
  }
}

$("person-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("person-error").textContent = "";
  const name = $("person-name").value.trim();
  if (!name) return;
  const notes = $("person-notes").value.trim();
  const gender = $("person-gender").value; // "" = unspecified
  try {
    await api("/api/personas", {
      method: "POST",
      body: JSON.stringify({ name, description: notes || null, gender: gender || null }),
    });
    $("person-name").value = "";
    $("person-gender").value = "";
    $("person-notes").value = "";
    await refreshPeople();
  } catch (err) {
    $("person-error").textContent = err.message;
  }
});

load();
refreshPeople();
