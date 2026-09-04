// Wardrobe page: item CRUD with inline edit.
"use strict";

const $ = (id) => document.getElementById(id);
let allItems = [];

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.status === 204 ? null : res.json();
}

function itemFromForm() {
  return {
    name: $("name").value.trim(),
    type: $("type").value,
    color: $("color").value.trim() || null,
    warmth: parseInt($("warmth").value, 10),
    formality: parseInt($("formality").value, 10),
    style_tags: $("style-tags").value.trim() || null,
    notes: $("notes").value.trim() || null,
  };
}

function formFromItem(it) {
  $("item-id").value = it.id;
  $("name").value = it.name;
  $("type").value = it.type;
  $("color").value = it.color || "";
  $("warmth").value = it.warmth;
  $("formality").value = it.formality;
  $("style-tags").value = it.style_tags || "";
  $("notes").value = it.notes || "";
}

function resetForm() {
  $("item-form").reset();
  $("item-id").value = "";
  $("form-title").textContent = "Add an item";
  $("save-btn").textContent = "Add item";
  $("cancel-btn").hidden = true;
  $("form-error").textContent = "";
}

async function refresh() {
  allItems = await api("/api/items");
  render();
}

function render() {
  const filter = $("filter-type").value;
  const items = filter ? allItems.filter((i) => i.type === filter) : allItems;
  $("count").textContent = allItems.length;
  $("empty-hint").hidden = allItems.length > 0;

  const tbody = $("items-tbody");
  tbody.innerHTML = "";
  for (const it of items) {
    const tr = document.createElement("tr");

    const cells = [
      it.name,
      it.type,
      it.color || "—",
      it.warmth,
      it.formality,
      it.style_tags || "—",
    ];
    for (const val of cells) {
      const td = document.createElement("td");
      td.textContent = val;
      tr.append(td);
    }

    const actions = document.createElement("td");
    const edit = document.createElement("button");
    edit.textContent = "Edit";
    edit.onclick = () => {
      formFromItem(it);
      $("form-title").textContent = `Edit “${it.name}”`;
      $("save-btn").textContent = "Save";
      $("cancel-btn").hidden = false;
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "Delete";
    del.onclick = async () => {
      if (!confirm(`Delete “${it.name}”?`)) return;
      try {
        await api(`/api/items/${it.id}`, { method: "DELETE" });
        if (String($("item-id").value) === String(it.id)) resetForm();
        await refresh();
      } catch (err) {
        alert(err.message);
      }
    };
    actions.append(edit, " ", del);
    tr.append(actions);
    tbody.append(tr);
  }
}

$("item-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("form-error").textContent = "";
  const id = $("item-id").value;
  try {
    if (id) {
      await api(`/api/items/${id}`, { method: "PUT", body: JSON.stringify(itemFromForm()) });
    } else {
      await api("/api/items", { method: "POST", body: JSON.stringify(itemFromForm()) });
    }
    resetForm();
    await refresh();
  } catch (err) {
    $("form-error").textContent = err.message;
  }
});

$("cancel-btn").onclick = resetForm;
$("filter-type").onchange = render;

refresh();
