// Shared persona helpers: who is getting dressed.
//
// Pages each decide how the switcher behaves:
// - wardrobe/settings: single-select (viewing one person's wardrobe)
// - ask (index.html): multi-select toggles (pair mode when >1 chosen)
//
// State lives in localStorage so the choice survives page navigation.
"use strict";

const Persona = {
  all: [],
  selected: new Set(),       // ids selected on this page
  single: false,             // single-select (wardrobe/settings) vs multi
  onChange: null,            // callback after a selection change
  _loaded: false,

  async load() {
    if (this._loaded) return this.all;
    const res = await fetch("/api/personas");
    if (!res.ok) throw new Error("personas unavailable");
    this.all = await res.json();
    if (!this.all.length) this.all = [{ id: 1, name: "Me" }];
    this._loaded = true;
    return this.all;
  },

  async init(options = {}) {
    this.single = !!options.single;
    this.onChange = options.onChange || null;
    await this.load();
    // Restore selection; default = first persona.
    const stored = localStorage.getItem("persona.selected");
    const ids = stored ? stored.split(",").map(Number).filter(Boolean) : [];
    const valid = ids.filter((id) => this.all.some((p) => p.id === id));
    this.selected = new Set(valid.length ? valid : [this.all[0].id]);
    if (this.single) {
      this.selected = new Set([...this.selected][0] ? [...this.selected].slice(0, 1) : [this.all[0].id]);
    }
    this._persist();
    return this.all;
  },

  _persist() {
    localStorage.setItem("persona.selected", [...this.selected].join(","));
  },

  name(id) {
    const p = this.all.find((p) => p.id === id);
    return p ? p.name : `#${id}`;
  },

  // ⚩/⚘-style marker for a gendered persona; empty when unspecified.
  symbol(p) {
    if (typeof p === "number") p = this.all.find((x) => x.id === p) || {};
    if (p.gender === "male") return "♂ ";
    if (p.gender === "female") return "♀ ";
    return "";
  },

  ids() {
    return [...this.selected];
  },

  toggle(id) {
    if (!this.all.some((p) => p.id === id)) return;
    if (this.single) {
      this.selected = new Set([id]);
    } else if (this.selected.has(id) && this.selected.size > 1) {
      this.selected.delete(id); // never allow deselecting everyone
    } else {
      this.selected.add(id);
    }
    this._persist();
    if (this.onChange) this.onChange();
  },

  // Render chips into a container. On single-select pages the chips act as
  // a switcher; on multi-select pages (Ask) they toggle who gets dressed.
  render(container, { label = "" } = {}) {
    container.innerHTML = "";
    container.className = "persona-chips";
    if (label) {
      const l = document.createElement("span");
      l.className = "persona-label muted";
      l.textContent = label;
      container.append(l);
    }
    for (const p of this.all) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "persona-chip" + (this.selected.has(p.id) ? " on" : "");
      chip.textContent = this.symbol(p) + p.name;
      chip.dataset.personaId = p.id;
      chip.setAttribute("aria-pressed", this.selected.has(p.id));
      chip.onclick = () => this.toggle(p.id);
      container.append(chip);
    }
  },
};
