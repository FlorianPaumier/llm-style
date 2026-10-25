// Wardrobe page: item CRUD with inline edit, photo -> AI draft, server-side
// pagination/sort/filter — for the persona selected in the header.
"use strict";

const $ = (id) => document.getElementById(id);

// Category metadata (CATEGORY_GROUPS / TYPE_OF_CATEGORY / CATEGORY_LABEL /
// ONE_PIECE_CATEGORIES) lives in the shared categories.js.

function populateCategorySelect() {
  const sel = $("category");
  sel.innerHTML = "";
  for (const group of CATEGORY_GROUPS) {
    const og = document.createElement("optgroup");
    og.label = group.label;
    for (const [value, label] of group.items) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label + (ONE_PIECE_CATEGORIES.has(value) ? " (one-piece)" : "");
      og.append(opt);
    }
    sel.append(og);
  }
}

// The type select is the grouping aid; picking a category sets it.
function syncTypeFromCategory() {
  $("type").value = TYPE_OF_CATEGORY[$("category").value] || "top";
}

populateCategorySelect();
$("category").onchange = syncTypeFromCategory;

let pendingToken = null; // photo_token from a classify run, not yet saved
let editingPhoto = null; // whether the edited item currently has a photo
let removedPhoto = false; // user clicked "remove photo" while editing
let quickAddFile = null; // staged photo for quick add (no classify until click)
let refreshTimer = null;
let currentPersonaId = 1; // wardrobe being viewed; set by persona switcher
let formPersonaId = 1; // persona the form will save to; set by form chips

// Table view state (server-driven now).
const PAGE_SIZE = 10;
let sortKey = null;   // null = table order (by id)
let sortAsc = true;
let page = 1;
let totalPages = 1;
let totalItems = 0;

async function api(path, options) {
  const res = await fetch(path, {
    headers: options && options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

// --- Form persona picker: whose wardrobe does the form save to? -------
//
// Separate from the view switcher above the table: picking a chip here
// only changes where this item will be saved (or moved to, when editing).
// Rendered by hand rather than via Persona.render, which would mutate the
// shared Persona.selected state that drives the view switcher.

function renderFormPersonas() {
  const box = $("form-persona-picker");
  box.innerHTML = "";
  for (const p of Persona.all) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "persona-chip" + (p.id === formPersonaId ? " on" : "");
    chip.textContent = p.name;
    chip.dataset.personaId = p.id;
    chip.setAttribute("aria-pressed", p.id === formPersonaId);
    chip.onclick = () => {
      formPersonaId = p.id;
      renderFormPersonas();
    };
    box.append(chip);
  }
}

function itemFromForm() {
  return {
    name: $("name").value.trim(),
    category: $("category").value, // primary field; server derives the type
    type: $("type").value,         // grouping aid, must agree with category
    color: $("color").value.trim() || null,
    warmth: parseInt($("warmth").value, 10),
    formality: parseInt($("formality").value, 10),
    style_tags: $("style-tags").value.trim() || null,
    notes: $("notes").value.trim() || null,
    persona_id: formPersonaId, // explicit: PUT moves the item between wardrobes
  };
}

function formFromItem(it) {
  $("item-id").value = it.id;
  $("name").value = it.name;
  $("category").value = it.category || TYPE_OF_CATEGORY[it.type]; // legacy rows: slot catch-all
  syncTypeFromCategory();
  $("color").value = it.color || "";
  $("warmth").value = it.warmth;
  $("formality").value = it.formality;
  $("style-tags").value = it.style_tags || "";
  $("notes").value = it.notes || "";
  formPersonaId = it.persona_id; // editing shows (and can change) the owner
  renderFormPersonas();
  setPendingToken(null);
  removedPhoto = false;
  editingPhoto = it.has_photo;
  if (it.has_photo) {
    showPreview(`/api/items/${it.id}/photo`);
    $("photo-remove").hidden = false;
  } else {
    hidePreview();
  }
}

function resetForm() {
  $("item-form").reset();
  $("item-id").value = "";
  formPersonaId = currentPersonaId; // new items default to the viewed wardrobe
  renderFormPersonas();
  setPendingToken(null);
  removedPhoto = false;
  editingPhoto = false;
  hidePreview();
  $("form-title").textContent = "Add an item";
  $("save-btn").textContent = "Add item";
  $("cancel-btn").hidden = true;
  $("form-error").textContent = "";
}

function updateSortHeaders() {
  document.querySelectorAll("th.sortable").forEach((th) => {
    th.classList.toggle("asc", sortKey === th.dataset.key && sortAsc);
    th.classList.toggle("desc", sortKey === th.dataset.key && !sortAsc);
  });
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(loadPage, 150);
}

let loadSeq = 0; // guards against out-of-order page loads (rapid sort/filter)
async function loadPage() {
  const seq = ++loadSeq;
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
    persona_id: String(currentPersonaId),
  });
  const filter = $("filter-type").value;
  if (filter) params.set("type", filter);
  if (sortKey) {
    params.set("sort", sortKey);
    params.set("order", sortAsc ? "asc" : "desc");
  }
  const body = await api(`/api/items?${params}`);
  if (seq !== loadSeq) return; // a newer load superseded this response

  totalPages = body.pages;
  totalItems = body.total;

  $("count").textContent = body.total;
  $("empty-hint").hidden = body.total > 0;
  updateSortHeaders();

  $("prev-page").disabled = page <= 1;
  $("next-page").disabled = page >= totalPages;
  const start = (page - 1) * PAGE_SIZE;
  $("page-info").textContent = body.total
    ? `Page ${page} of ${totalPages}`
    : "No items";
  $("showing-info").textContent = body.total
    ? `Showing ${start + 1}–${Math.min(start + PAGE_SIZE, body.total)} of ${body.total}`
    : "";

  renderRows(body.items);
}

function renderRows(pageItems) {
  const tbody = $("items-tbody");
  tbody.innerHTML = "";
  for (const it of pageItems) {
    const tr = document.createElement("tr");

    const thumbCell = document.createElement("td");
    if (it.has_photo) {
      const img = document.createElement("img");
      img.className = "thumb";
      img.src = it.photo_url;
      img.alt = it.name;
      img.loading = "lazy";
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
      CATEGORY_LABEL[it.category] || it.category || "—", // category is the display value
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
        scheduleRefresh();
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
      // PUT carries persona_id too: a changed form picker moves the item.
      await api(`/api/items/${id}`, { method: "PUT", body: JSON.stringify(itemFromForm()) });
      // Photo changes are separate from field edits (photo endpoints).
      if (removedPhoto && editingPhoto) {
        await api(`/api/items/${id}/photo`, { method: "DELETE" });
      } else if (pendingToken) {
        await api(`/api/items/${id}/photo`, {
          method: "POST",
          body: JSON.stringify({ photo_token: pendingToken }),
        });
      }
    } else {
      const payload = itemFromForm(); // includes persona_id from the form picker
      if (pendingToken) payload.photo_token = pendingToken;
      await api("/api/items", { method: "POST", body: JSON.stringify(payload) });
    }
    const savedToken = pendingToken; // captured before resetForm clears it
    resetForm();
    if (savedToken) markBulkSavedByToken(savedToken); // queue row -> "Saved"
    scheduleRefresh();
  } catch (err) {
    $("form-error").textContent = err.message;
  }
});

$("cancel-btn").onclick = resetForm;
$("filter-type").onchange = () => {
  page = 1; // a new filter can shrink the visible set
  loadPage();
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
    loadPage();
  };
});

$("prev-page").onclick = () => {
  page -= 1;
  loadPage();
};
$("next-page").onclick = () => {
  page += 1;
  loadPage();
};

// --- Photo upload & AI classification ---------------------------------

function setPendingToken(token) {
  pendingToken = token;
  $("classify-btn").disabled = !token;
  $("classify-status").textContent = "";
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
  $("photo-remove").hidden = true;
}

const drop = $("photo-drop");
drop.onclick = () => $("photo-input").click();
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("dragover"); });
drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("dragover");
  const files = e.dataTransfer && e.dataTransfer.files;
  if (files && files.length) setFiles(files);
});
$("photo-input").onchange = () => {
  const files = $("photo-input").files;
  if (files && files.length) setFiles(files);
  $("photo-input").value = ""; // allow re-picking the same file later
};

// One file keeps the classic flow (classify + prefill the form); several
// files go through the queue card instead.
function setFiles(files) {
  const list = Array.from(files);
  if (list.length === 1) {
    setFile(list[0]);
  } else if (list.length > 1) {
    startBulkQueue(list);
  }
}

function setFile(file) {
  $("classify-status").textContent = "";
  $("classify-btn").disabled = true; // until a token comes back
  showPreview(URL.createObjectURL(file));
  $("photo-remove").hidden = false;
  if ($("quick-add-mode").checked) {
    // Quick add stages the photo instead: no model call until the user
    // commits with the Quick add button (every detected item is saved).
    quickAddFile = file;
    $("quick-add-btn").hidden = false;
    $("quick-add-status").textContent = "Ready — Quick add saves the AI's draft as-is.";
    return;
  }
  runClassify(file);
}

$("photo-remove").onclick = () => {
  setPendingToken(null);
  removedPhoto = true;
  hidePreview();
};

$("classify-btn").onclick = () => {
  // Kept for keyboard activation of the drop zone path; classify runs
  // automatically on file selection.
  $("classify-btn").blur();
};

// --- Quick add: photo -> saved item, no review form ----------------------

$("quick-add-mode").onchange = () => {
  // Switching mode invalidates any staged file; user re-picks.
  quickAddFile = null;
  $("quick-add-btn").hidden = true;
  $("quick-add-status").textContent = "";
  hidePreview();
};

$("quick-add-btn").onclick = async () => {
  if (!quickAddFile) return;
  const btn = $("quick-add-btn");
  btn.disabled = true;
  $("quick-add-status").textContent = "Saving from photo… (up to ~30s)";
  try {
    const fd = new FormData();
    fd.append("photo", quickAddFile, quickAddFile.name);
    fd.append("persona_id", String(formPersonaId));
    const { items } = await api("/api/items/from-photo", { method: "POST", body: fd });
    const s = items.length === 1 ? "" : "s";
    $("quick-add-status").textContent =
      `Saved ${items.length} item${s} to ${Persona.name(items[0].persona_id)}'s wardrobe.`;
    quickAddFile = null;
    btn.hidden = true;
    hidePreview();
    scheduleRefresh();
  } catch (err) {
    $("quick-add-status").textContent = "";
    $("form-error").textContent = "Quick add failed: " + err.message;
  } finally {
    btn.disabled = false;
  }
};

async function runClassify(file) {
  $("classify-status").textContent = "Asking the vision model… (up to ~30s)";
  try {
    const fd = new FormData();
    fd.append("photo", file, file.name);
    const { items } = await api("/api/classify", { method: "POST", body: fd });
    if (items.length > 1) {
      // Multi-item photo (a flat-lay): don't prefill the form — one row
      // per draft in the queue, reviewed (and saved) from there.
      openDraftQueue(items, file);
      $("classify-status").textContent = `Found ${items.length} items — review them in the queue below.`;
      return;
    }
    applyDraftToForm(items[0]);
    $("classify-status").textContent = "Draft filled in — review the scores before saving.";
  } catch (err) {
    $("classify-status").textContent = "";
    $("form-error").textContent = "Classification failed: " + err.message;
  }
}

// Prefill the item form from a draft (token + fields). Shared by the
// single-photo flow and the queue's Review buttons.
function applyDraftToForm(draft) {
  $("name").value = draft.name;
  // Category is the review form's primary field: a vision-model mistake
  // can be corrected here before saving.
  $("category").value = draft.category || TYPE_OF_CATEGORY[draft.type];
  syncTypeFromCategory();
  if (draft.color) $("color").value = draft.color;
  $("warmth").value = draft.warmth;
  $("formality").value = draft.formality;
  if (draft.style_tags) $("style-tags").value = draft.style_tags;
  setPendingToken(draft.photo_token);
  showPreview(`/api/classify/photo/${draft.photo_token}`);
  $("photo-remove").hidden = false;
}

// --- Bulk photo queue: many photos, classified one at a time -----------
//
// Selecting 2+ photos shows the queue card: each row tracks one file
// (Queued -> Classifying… -> Draft ready / Failed). A ready row's Review
// button loads that draft into the item form; saving the item marks the
// row "Saved" (its photo token was just claimed).
//
// Selections above the backend's 20-photos-per-request cap are sent as
// sequential batches (see BULK_BATCH_SIZE): one job per batch, polled to
// completion before the next submits, so the vision model still sees at
// most one photo at a time across the whole queue.
//
// One photo can hold SEVERAL items (a flat-lay). While a batch runs the
// rows stay per-FILE (progress counts files); at its completion those
// rows are REBUILT per-DRAFT from the result list — a file that yielded
// k drafts becomes k ready rows (labelled with each draft's name, sharing
// the same thumbnail). The single-photo flow with several drafts reuses
// the same rows/render/review machinery via openDraftQueue (no job, no
// polling).

let bulkQueue = null; // {rows: [{file, label?, state, draft, chip, err, review}], status}

// Paired with the backend's MAX_BULK_PHOTOS (main.py): /api/classify/bulk
// rejects more than 20 photos per request, so bigger selections are sent
// in sequential batches of at most this size.
const BULK_BATCH_SIZE = 20;

function rowLabel(row) {
  const base = row.label || row.file.name;
  // The review UI shows the detailed category for every draft so a
  // vision-model mistake is visible (and correctable) before saving.
  if (row.draft && row.draft.category) {
    return `${base} · ${CATEGORY_LABEL[row.draft.category] || row.draft.category}`;
  }
  return base;
}

function setChip(row, text, tone) {
  row.chip.textContent = text;
  row.chip.className = "chip bulk-chip " + (tone || "");
}

function queueIsFinished() {
  return !bulkQueue || bulkQueue.status === "done" || bulkQueue.status === "failed";
}

// Ready rows exist -> offer saving them all in one click.
function updateBulkSaveAll() {
  const btn = $("bulk-save-all");
  if (!btn || !bulkQueue) return;
  const ready = bulkQueue.rows.filter((r) => r.state === "ready").length;
  btn.hidden = !queueIsFinished() || ready === 0;
  btn.disabled = !queueIsFinished() || ready === 0;
}

function bulkSummary() {
  const q = bulkQueue;
  if (!q) return;
  if (q.status === "done") {
    const drafts = q.rows.filter((r) => r.state === "ready" || r.state === "saved").length;
    const failed = q.rows.filter((r) => r.state === "failed").length;
    const files = q.files || q.rows.length;
    const fileText = `${files} photo${files === 1 ? "" : "s"}`;
    // All-failed (model down) keeps the classic "Classified" phrasing;
    // otherwise drafts are counted (a flat-lay yields several per photo).
    $("bulk-summary").textContent = drafts
      ? `${drafts} item${drafts === 1 ? "" : "s"} from ${fileText}`
      : `Classified ${failed > files ? files : failed} of ${files}`;
    return;
  }
  // While running, rows per batch are replaced by per-DRAFT rows (a
  // flat-lay yields several per file), so row count is unstable — the
  // honest denominator is always files.
  $("bulk-summary").textContent =
    q.status === "failed"
      ? `Classified ${q.filesDone || 0} of ${q.files}`
      : `Classifying ${q.filesDone || 0} of ${q.files}…`;
}

function startBulkQueue(files) {
  if (!queueIsFinished()) {
    // A queue is still running; simplest local-first answer: don't mix
    // uploads into it — ask the user to let it finish first.
    $("classify-status").textContent = "";
    $("form-error").textContent = "A photo queue is already running — let it finish first.";
    return;
  }
  const q = {
    rows: files.map((file) => ({ file, state: "queued", draft: null })),
    files: files.length,
    filesDone: 0,
    status: "uploading",
  };
  bulkQueue = q;
  renderBulkRows();
  $("bulk-queue").hidden = false;
  $("bulk-save-all").hidden = true; // nothing ready yet
  $("bulk-summary").textContent = "Uploading…";

  pollBulkQueue(q).catch((e) => {
    // Submission or polling itself failed outside a batch (network,
    // 422, job crash): every unfinished row shows the reason inline.
    q.status = "failed";
    for (const row of q.rows) {
      if (row.state === "queued" || row.state === "classifying" || row.state === "waiting-result") {
        row.state = "failed";
        setChip(row, "Failed", "fail");
        row.err.textContent = e.message;
      }
    }
    bulkSummary();
    updateBulkSaveAll();
  });
}

// One multi-item photo: drafts are known, so rows start ready. No job, no
// polling — this shares only the rows/render/review/markBulkSaved machinery
// with the bulk queue.
function openDraftQueue(drafts, file) {
  bulkQueue = {
    rows: drafts.map((draft) => ({ file, label: draft.name, state: "ready", draft })),
    files: 1,
    status: "done",
  };
  renderBulkRows();
  $("bulk-queue").hidden = false;
  bulkSummary();
  updateBulkSaveAll();
}

// What a row shows per state — used on render; state changes later in the
// queue's life update the chip in place via setChip instead.
const BULK_CHIP = {
  queued: ["Queued", ""],
  classifying: ["Classifying…", "busy"],
  "waiting-result": ["Classifying…", "busy"], // done server-side, result pending
  ready: ["Draft ready", "ok"],
  failed: ["Failed", "fail"],
  saved: ["Saved", "ok"],
};

let bulkObjectUrls = []; // thumbnails created by renderBulkRows, revoked on re-render

function renderBulkRows() {
  for (const url of bulkObjectUrls) URL.revokeObjectURL(url);
  bulkObjectUrls = [];
  const box = $("bulk-rows");
  box.innerHTML = "";
  for (const row of bulkQueue.rows) {
    const li = document.createElement("li");
    const thumb = document.createElement("img");
    const thumbUrl = URL.createObjectURL(row.file);
    bulkObjectUrls.push(thumbUrl);
    thumb.src = thumbUrl;
    thumb.alt = rowLabel(row);
    thumb.className = "bulk-thumb";
    const name = document.createElement("span");
    name.className = "bulk-name" + (row.label ? " bulk-row-label" : "");
    name.textContent = rowLabel(row);
    if (row.label) name.title = row.file.name; // which photo the draft came from
    row.chip = document.createElement("span");
    const [text, tone] = BULK_CHIP[row.state] || ["Queued", ""];
    setChip(row, text, tone);
    row.err = document.createElement("span");
    row.err.className = "error bulk-error";
    if (row.error) row.err.textContent = row.error;
    row.review = document.createElement("button");
    row.review.type = "button";
    row.review.textContent = "Review";
    row.review.hidden = row.state !== "ready";
    row.review.onclick = () => reviewDraft(row);
    li.append(thumb, name, row.chip, row.err, row.review);
    box.append(li);
  }
}

function reviewDraft(row) {
  if (!row.draft) return;
  $("item-id").value = ""; // reviewing always starts a NEW item
  $("cancel-btn").hidden = true;
  $("form-title").textContent = "Add an item";
  $("save-btn").textContent = "Add item";
  $("form-error").textContent = "";
  applyDraftToForm(row.draft);
  $("classify-status").textContent = "Draft filled in — review the scores before saving.";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function submitBulk(files) {
  const fd = new FormData();
  for (const file of files) fd.append("photos", file, file.name);
  const res = await fetch("/api/classify/bulk", { method: "POST", body: fd });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json(); // {job_id, status_url}
}

async function pollBulkQueue(q) {
  // The backend caps /api/classify/bulk at MAX_BULK_PHOTOS per request, so
  // bigger selections are split into batches. Batches run strictly one
  // after another — each is polled to completion first — keeping the
  // "one vision call at a time" invariant across the whole queue.
  const pending = q.rows.slice(); // the per-FILE rows, in selection order
  let filesBefore = 0; // files settled by earlier batches
  for (let i = 0; i < pending.length; i += BULK_BATCH_SIZE) {
    const batch = pending.slice(i, i + BULK_BATCH_SIZE);
    try {
      await runBatch(q, batch, filesBefore);
    } catch (e) {
      // This batch's submission/polling died (network, job crash): mark
      // only ITS rows failed and let the remaining batches still run.
      for (const row of batch) {
        if (row.state === "queued" || row.state === "classifying" || row.state === "waiting-result") {
          row.state = "failed";
          setChip(row, "Failed", "fail");
          row.err.textContent = e.message;
        }
      }
    } finally {
      filesBefore += batch.length;
      q.filesDone = filesBefore;
      bulkSummary();
    }
  }
  q.status = "done";
  bulkSummary();
  updateBulkSaveAll();
}

// Upload one batch, poll its job to completion, then splice the batch's
// per-FILE rows out of the queue and the per-DRAFT rows in. Progress from
// the job counts files; filesBefore is how many earlier batches settled.
async function runBatch(q, batch, filesBefore) {
  const { status_url } = await submitBulk(batch.map((r) => r.file));
  // q.status stays "running" for the WHOLE batch loop: a job finishing is
  // not the queue finishing (later batches may follow), and "done" would
  // briefly unlock Clear on a queue that is still going.
  q.status = "running";

  let last = null;
  while (!last || last.status === "queued" || last.status === "running") {
    await new Promise((r) => setTimeout(r, 1500));
    last = await api(status_url);
    const done = last.progress ? last.progress.done : 0;
    batch.forEach((row, i) => {
      if (row.state !== "queued" && row.state !== "classifying") return;
      if (i < done) {
        row.state = "waiting-result"; // done server-side, final state lands with the result
      } else if (i === done) {
        row.state = "classifying";
        setChip(row, "Classifying…", "busy");
      }
    });
    q.filesDone = filesBefore + done;
    bulkSummary();
  }

  if (last.status !== "done") {
    throw new Error(last.error || "The classification job failed");
  }

  // The result is PER-DRAFT: a multi-item photo (flat-lay) yields several
  // ok:true rows sharing one filename. Rebuild the batch's rows from it —
  // while running the rows were per-FILE (progress counts files); from
  // here on each row is one draft (or one failure). Earlier batches'
  // drafts live earlier in q.rows; replace only this batch's segment.
  const built = draftRowsFromResult(batch, last.result || []);
  const start = q.rows.indexOf(batch[0]);
  q.rows.splice(start, batch.length, ...built);
  renderBulkRows();
}

// A batch's terminal result -> its per-draft rows. ok:true rows keep
// request order (grouped by filename); ok:false rows become one failed
// row each. A file that uploaded but produced no result row at all (the
// job ended without reporting it) fails with "no result".
function draftRowsFromResult(batch, result) {
  const fileByName = new Map(batch.map((r) => [r.file.name, r.file]));
  const fallbackFile = batch.length ? batch[0].file : null;
  const rows = [];
  const seenFiles = new Set();
  for (const item of result) {
    const file = fileByName.get(item.filename) || fallbackFile;
    if (item.ok && item.draft && file) {
      rows.push({ file, label: item.draft.name, state: "ready", draft: item.draft });
    } else {
      rows.push({
        file: file || fallbackFile,
        label: item.filename,
        state: "failed",
        error: item.error || "Vision model returned no result",
      });
    }
    // ok:false rows belong to a file too — it WAS reported, it just
    // failed; it must not also produce a phantom "no result" row.
    seenFiles.add(item.filename);
  }
  // A file that uploaded (and was mid-flight) but never produced a result
  // row — the job ended without reporting it.
  for (const row of batch) {
    if (seenFiles.has(row.file.name)) continue;
    if (row.state === "queued" || row.state === "classifying" || row.state === "waiting-result") {
      rows.push({ file: row.file, state: "failed", error: "No result for this photo" });
    }
  }
  return rows;
}

function markBulkSaved(row) {
  row.state = "saved";
  setChip(row, "Saved", "ok");
  row.review.hidden = true;
  updateBulkSaveAll();
}

// A form save claimed a draft's photo token; flip that queue row to Saved.
function markBulkSavedByToken(token) {
  if (!bulkQueue) return;
  for (const row of bulkQueue.rows) {
    if (row.draft && row.draft.photo_token === token && row.state === "ready") {
      markBulkSaved(row);
    }
  }
}

// Save every ready draft at once: same POST /api/items the form submit
// does (fields + photo_token), one request per draft, sequentially — the
// photo queue never bursts the backend. A failed row never stops the rest.
$("bulk-save-all").onclick = async () => {
  const btn = $("bulk-save-all");
  if (!bulkQueue || !queueIsFinished()) return;
  const ready = bulkQueue.rows.filter((r) => r.state === "ready");
  if (!ready.length) return;
  btn.disabled = true;
  let saved = 0;
  for (const row of ready) {
    setChip(row, "Saving…", "busy");
    try {
      await api("/api/items", {
        method: "POST",
        body: JSON.stringify({
          name: row.draft.name,
          category: row.draft.category,
          type: row.draft.type,
          color: row.draft.color,
          warmth: row.draft.warmth,
          formality: row.draft.formality,
          style_tags: row.draft.style_tags,
          notes: null,
          persona_id: formPersonaId, // the form's "Whose wardrobe?" picker
          photo_token: row.draft.photo_token,
        }),
      });
      saved += 1;
      markBulkSaved(row);
    } catch (err) {
      row.state = "failed";
      setChip(row, "Failed", "fail");
      row.err.textContent = err.message;
    }
  }
  $("bulk-summary").textContent = `Saved ${saved} of ${ready.length}`;
  btn.disabled = false;
  updateBulkSaveAll();
  if (saved) scheduleRefresh();
};

$("bulk-clear").onclick = () => {
  if (!queueIsFinished()) return; // never drop a running queue
  bulkQueue = null;
  for (const url of bulkObjectUrls) URL.revokeObjectURL(url);
  bulkObjectUrls = [];
  $("bulk-rows").innerHTML = "";
  $("bulk-summary").textContent = "";
  $("bulk-save-all").hidden = true;
  $("bulk-queue").hidden = true;
};

// --- Persona switcher: whose wardrobe are we viewing? ----------------

async function initPersonas() {
  await Persona.init({ single: true });
  currentPersonaId = Persona.ids()[0];
  const render = () => {
    Persona.render($("wardrobe-persona-picker"), { label: "" });
    currentPersonaId = Persona.ids()[0];
    // The form follows the viewed wardrobe, unless an item is being
    // edited (then its own persona stays selected on the form).
    if (!$("item-id").value) {
      formPersonaId = currentPersonaId;
      renderFormPersonas();
    }
    page = 1;
    loadPage();
  };
  Persona.onChange = render;
  render();
}

initPersonas(); // page data loads via render -> loadPage
