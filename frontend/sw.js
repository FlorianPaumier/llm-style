// Service worker: offline shell for the llm-style app.
//
// Strategy: network-first for everything, falling back to the cached copy.
// The app is local-first (the backend IS the local machine), so "offline"
// mainly means: the server isn't running — show the last-seen UI instead
// of a browser error. API calls are never cached: wardrobe edits must
// never silently no-op.
const CACHE = "llm-style-v6-activity";
const SHELL = [
  "/",
  "/index.html",
  "/wardrobe.html",
  "/settings.html",
  "/install.html",
  "/app.js",
  "/categories.js",
  "/persona.js",
  "/wardrobe.js",
  "/settings.js",
  "/install.js",
  "/style.css",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((cache) =>
      Promise.allSettled(SHELL.map((u) => cache.add(new Request(u, { cache: "reload" }))))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;

  // API + photos: try network; if it fails, respond with a clear offline
  // error the frontend can show (do NOT serve stale JSON).
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(
      fetch(e.request).catch(
        () =>
          new Response(JSON.stringify({ detail: "Server unreachable — is the backend running?" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          })
      )
    );
    return;
  }

  // App shell: network-first, cache fallback. The request bypasses the
  // HTTP cache ("reload"): static files carry no Cache-Control header, so
  // a plain fetch() could serve a heuristically-fresh STALE script after
  // an update — exactly the persona.symbol bug.
  e.respondWith(
    fetch(new Request(e.request, { cache: "reload" }))
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() =>
        caches.match(e.request).then(
          (hit) =>
            hit ||
            caches.match(url.pathname === "/" ? "/index.html" : url.pathname)
        )
      )
  );
});
