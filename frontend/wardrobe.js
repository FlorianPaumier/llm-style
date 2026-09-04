// Wardrobe page: item CRUD with inline edit, plus photo -> AI draft.
"use strict";

const $ = (id) => document.getElementById(id);
let allItems = [];
let pendingFile = null; // File chosen in the form, not yet saved

// Table view state: current sort column/direction and page.
const PAGE_SIZE = 10;
let sortKey = null;   // null = table order (by id)
let sortAsc = true;
let page = 1;

async function api(path, options) {
  const res = await fetch(path, {
    headers: options && options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
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
    image_path: $("image-path").value || null,
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
  // Editing an existing item: show its saved photo (or none).
  setPendingFile(null);
  const path = it.image_path || null;
  $("image-path").value = path || "";
  if (path) {
    showPreview(`/api/items/${it.id}/photo`);
  }
}

function resetForm() {
  $("item-form").reset();
  $("item-id").value = "";
  $("image-path").value = "";
  setPendingFile(null);
  hidePreview();
  $("form-title").textContent = "Add an item";
  $("save-btn").textContent = "Add item";
  $("cancel-btn").hidden = true;
  $("form-error").textContent = "";
}

async function refresh() {
  allItems = await api("/api/items");
  render();
}

function visibleItems() {
  const filter = $("filter-type").value;
  let items = filter ? allItems.filter((i) => i.type === filter) : allItems.slice();

  if (sortKey) {
    const dir = sortAsc ? 1 : -1;
    items.sort((a, b) => {
      const va = a[sortKey] ?? "";
      const vb = b[sortKey] ?? "";
      // Numeric columns sort numerically; everything else case-insensitively.
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb), undefined, { sensitivity: "base" }) * dir;
    });
  }
  return items;
}

function updateSortHeaders() {
  document.querySelectorAll("th.sortable").forEach((th) => {
    th.classList.toggle("asc", sortKey === th.dataset.key && sortAsc);
    th.classList.toggle("desc", sortKey === th.dataset.key && !sortAsc);
  });
}

function clampPage(pageCount) {
  if (page > pageCount) page = pageCount;
  if (page < 1) page = 1;
}

function render() {
  const items = visibleItems();
  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  clampPage(pageCount);
  const start = (page - 1) * PAGE_SIZE;
  const pageItems = items.slice(start, start + PAGE_SIZE);

  $("count").textContent = allItems.length;
  $("empty-hint").hidden = allItems.length > 0;
  updateSortHeaders();

  // Pager state.
  $("prev-page").disabled = page <= 1;
  $("next-page").disabled = page >= pageCount;
  $("page-info").textContent = items.length
    ? `Page ${page} of ${pageCount}`
    : "No items";
  $("showing-info").textContent = items.length
    ? `Showing ${start + 1}–${Math.min(start + PAGE_SIZE, items.length)} of ${items.length}`
    : "";

  const tbody = $("items-tbody");
  tbody.innerHTML = "";
  for (const it of pageItems) {
    const tr = document.createElement("tr");

    const thumbCell = document.createElement("td");
    if (it.image_path) {
      const img = document.createElement("img");
      img.className = "thumb";
      img.src = `/api/items/${it.id}/photo`;
      img.alt = it.name;
      thumbCell.append(img);
    } else {
      const span = document.createElement("span");
      span.className = "thumb-empty";
      span.textContent = "—";
      thumbCell.append(span);
    }
    tr.append(thumbCell);

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
$("filter-type").onchange = () => {
  page = 1; // a new filter can shrink the visible set
  render();
};

// --- Sorting & pagination --------------------------------------------

document.querySelectorAll("th.sortable").forEach((th) => {
  th.onclick = () => {
    const key = th.dataset.key;
    if (sortKey === key) {
      sortAsc = !sortAsc; // same column: flip direction
    } else {
      sortKey = key;
      sortAsc = true;
    }
    page = 1; // re-sorted list restarts at the first page
    render();
  };
});

$("prev-page").onclick = () => {
  page -= 1;
  render();
};
$("next-page").onclick = () => {
  page += 1;
  render();
};

// --- Photo upload & AI classification ---------------------------------

function setPendingFile(file) {
  pendingFile = file;
  $("classify-btn").disabled = !file;
  $("classify-status").textContent = "";
  $("photo-remove").hidden = !file && !$("image-path").value;
  if (file) {
    showPreview(URL.createObjectURL(file));
  }
}

function showPreview(src) {
  $("photo-preview").src = src;
  $("photo-preview").hidden = false;
  $("photo-hint").hidden = true;
}

function hidePreview() {
  $("photo-preview").hidden = true;
  $("photo-preview").src = "";
  $("photo-hint").hidden = false;
}

const drop = $("photo-drop");
drop.onclick = () => $("photo-input").click();
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("dragover"); });
drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("dragover");
  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) setPendingFile(file);
});
$("photo-input").onchange = () => {
  const file = $("photo-input").files && $("photo-input").files[0];
  if (file) setPendingFile(file);
};
$("photo-remove").onclick = () => {
  $("image-path").value = "";
  setPendingFile(null);
  hidePreview();
};

$("classify-btn").onclick = async () => {
  if (!pendingFile) return;
  const btn = $("classify-btn");
  btn.disabled = true;
  $("classify-status").textContent = "Asking the vision model… (up to ~30s)";
  try {
    const fd = new FormData();
    fd.append("photo", pendingFile, pendingFile.name);
    const draft = await api("/api/classify", { method: "POST", body: fd });
    // Pre-fill the form: the draft is a suggestion, the user reviews it.
    $("name").value = draft.name;
    $("type").value = draft.type;
    if (draft.color) $("color").value = draft.color;
    $("warmth").value = draft.warmth;
    $("formality").value = draft.formality;
    if (draft.style_tags) $("style-tags").value = draft.style_tags;
    $("image-path").value = draft.image_path || "";
    $("photo-remove").hidden = false;
    $("classify-status").textContent = "Draft filled in — review the scores before saving.";
  } catch (err) {
    $("classify-status").textContent = "";
    $("form-error").textContent = "Classification failed: " + err.message;
    btn.disabled = false;
    return;
  }
  btn.disabled = false;
};

refresh();
