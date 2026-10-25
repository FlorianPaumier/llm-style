// Ask page: mood + occasion + weather -> outfit recommendation,
// for one person or a coordinated pair (multi-select the persona chips).
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

// Piece label: the detailed category is the display value ("T-shirt",
// "Cardigan", "Tights"…). It's what tells a layered cardigan apart from
// the primary top, and tights from the skirt — pieces that share the same
// broad slot. Falls back to the raw slot for unknown categories.
function pieceLabel(piece) {
  const category = piece.item && piece.item.category;
  return (category && CATEGORY_LABEL[category]) || piece.slot;
}

function renderPersonaOutfit(container, po) {
  const div = document.createElement("div");
  div.className = "persona-outfit";

  const head = document.createElement("div");
  head.className = "persona-outfit-head";
  const who = document.createElement("h3");
  who.textContent = po.persona_name;
  const title = document.createElement("span");
  title.className = "persona-outfit-title muted";
  title.textContent = po.title;
  head.append(who, title);
  if (po.option > 1) {
    // One of several options in the same request: label the alternatives.
    const opt = document.createElement("span");
    opt.className = "option-chip";
    opt.textContent = `Option ${po.option}`;
    head.append(opt);
  }
  div.append(head);

  const grid = document.createElement("div");
  grid.className = "outfit-grid";
  for (const piece of po.outfit) {
    const pieceDiv = document.createElement("div");
    pieceDiv.className = "outfit-piece";
    const slot = document.createElement("div");
    slot.className = "slot";
    slot.textContent = pieceLabel(piece);
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = piece.item.name +
      (piece.item.color ? ` (${piece.item.color})` : "");
    pieceDiv.append(slot, name);
    grid.append(pieceDiv);
  }
  div.append(grid);

  const rationale = document.createElement("p");
  rationale.className = "rationale";
  rationale.textContent = po.rationale || "";
  div.append(rationale);

  const gaps = document.createElement("ul");
  gaps.className = "gaps";
  for (const g of po.gaps || []) {
    const li = document.createElement("li");
    li.textContent = g;
    gaps.append(li);
  }
  if (po.source === "fallback") {
    const li = document.createElement("li");
    li.textContent = "Shown without the stylist model — start Ollama for a mood-matched pick.";
    gaps.append(li);
  }
  div.append(gaps);

  // Worn tracking is per outfit: options are alternatives, so marking one
  // worn must never inflate the others' items.
  if (po.history_id) {
    const wornArea = document.createElement("p");
    wornArea.className = "actions worn-area";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "worn-btn";
    btn.textContent = "We wore this today";
    btn.dataset.historyId = po.history_id;
    const status = document.createElement("span");
    status.className = "muted worn-status";
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const r = await api(`/api/history/${po.history_id}/worn`, { method: "POST" });
        status.textContent = r.already_worn ? "Already counted." : "Noted — wear it well!";
      } catch {
        status.textContent = "Could not save.";
        btn.disabled = false;
      }
    };
    wornArea.append(btn, " ", status);
    div.append(wornArea);
  }
  container.append(div);
}

function renderResult(body) {
  $("result").hidden = false;

  // One card per (persona, option) — a single request may carry several
  // options per person when the count select asked for more than one.
  const outfits = body.outfits && body.outfits.length ? body.outfits : null;
  const cards = $("persona-results");
  cards.innerHTML = "";
  if (outfits) {
    for (const po of outfits) renderPersonaOutfit(cards, po);
  } else {
    // Backward-compatible fallback for older servers.
    renderPersonaOutfit(cards, {
      persona_name: "You", title: body.title || "Your outfit",
      outfit: body.outfit, rationale: body.rationale, gaps: body.gaps,
      source: body.source, persona_id: null, history_id: body.history_id,
    });
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
  const count = parseInt($("count").value, 10) || 1;
  const payload = {
    mood,
    occasion: $("occasion").value,
    persona_ids: Persona.ids(),
    count,
  };
  // What they'll be doing ("Christmas dinner", "zoo day") — the stylist
  // dresses for it and the engine guarantees a warm-layer option.
  const activity = $("activity").value.trim();
  if (activity) payload.activity = activity;
  if (tempInput !== "") payload.weather_override_c = parseFloat(tempInput);

  const btn = $("ask-btn");
  btn.disabled = true;
  const pairNote = Persona.ids().length > 1 ? " — coordinating the pair…" : "…";
  $("status").textContent = "Asking your stylist" + pairNote;
  try {
    // Several options mean several sequential model calls — that belongs
    // in a background job, not one hanging HTTP request.
    let body;
    if (count > 1) {
      const { status_url } = await api("/api/outfits/recommend/async", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      let job = null;
      while (!job || job.status === "queued" || job.status === "running") {
        await new Promise((r) => setTimeout(r, 1500));
        $("status").textContent = "Working on your options…";
        job = await api(status_url);
      }
      if (job.status !== "done") throw new Error(job.error || "The recommendation job failed");
      body = job.result;
    } else {
      body = await api("/api/outfits/recommend", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
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

// --- Persona selection (who is getting dressed; select two to pair) ---

async function initPersonas() {
  await Persona.init({ single: false });
  const render = () => {
    Persona.render($("persona-picker"), { label: "Dressing:" });
    const pair = Persona.ids().length > 1;
    const hint = $("pair-hint");
    hint.hidden = !pair;
    if (pair) {
      hint.textContent =
        `Pair mode — ${Persona.ids().map((id) => Persona.name(id)).join(" & ")} ` +
        "will get coordinated outfits that complement each other.";
    }
  };
  Persona.onChange = render;
  render();
}

loadWeather();
initPersonas();
