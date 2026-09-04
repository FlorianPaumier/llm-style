// Ask page: mood + occasion + weather -> outfit recommendation.
"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function renderWeatherNote(weather) {
  if (!weather) {
    $("weather-note").textContent = "Live weather unavailable — set the temperature manually.";
    return;
  }
  $("weather-note").textContent =
    `Live weather for ${weather.city}: ${weather.temperature_c.toFixed(0)}°C` +
    (weather.precipitation_mm > 0 ? ", rain expected" : "");
}

function renderResult(body) {
  $("result").hidden = false;
  $("outfit-title").textContent = body.title || "Your outfit";

  const grid = $("outfit-grid");
  grid.innerHTML = "";
  for (const piece of body.outfit) {
    const div = document.createElement("div");
    div.className = "outfit-piece";
    const slot = document.createElement("div");
    slot.className = "slot";
    slot.textContent = piece.slot;
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = piece.item.name +
      (piece.item.color ? ` (${piece.item.color})` : "");
    div.append(slot, name);
    grid.append(div);
  }

  $("outfit-rationale").textContent = body.rationale || "";

  const gaps = $("outfit-gaps");
  gaps.innerHTML = "";
  for (const g of body.gaps || []) {
    const li = document.createElement("li");
    li.textContent = g;
    gaps.append(li);
  }
  if (body.source === "fallback") {
    const li = document.createElement("li");
    li.textContent = "Shown without the stylist model — start Ollama for a mood-matched pick.";
    gaps.append(li);
  }
}

async function loadWeather() {
  try {
    const w = await api("/api/weather");
    renderWeatherNote(w);
  } catch {
    renderWeatherNote(null);
  }
}

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const mood = $("mood").value.trim();
  if (!mood) return;
  const tempInput = $("weather-temp").value;
  const payload = {
    mood,
    occasion: $("occasion").value,
  };
  if (tempInput !== "") payload.weather_override_c = parseFloat(tempInput);

  const btn = $("ask-btn");
  btn.disabled = true;
  $("status").textContent = "Asking your stylist…";
  try {
    const body = await api("/api/outfits/recommend", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderResult(body);
    renderWeatherNote(body.weather);
    $("status").textContent = "";
  } catch (err) {
    $("status").textContent = "";
    alert("Could not get a recommendation: " + err.message);
  } finally {
    btn.disabled = false;
  }
});

loadWeather();
