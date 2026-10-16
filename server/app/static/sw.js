/* Bahi service worker: always try the server first, fall back to the saved copy when offline */
const SHELL = "bahi-shell-v12", DATA = "bahi-data-v1";
const FILES = ["/", "/index.html", "/style.css", "/app.js", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function networkFirst(req, cacheName, key) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req, { cache: "no-store" });
    if (res.ok || res.type === "opaque") cache.put(key || req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(key || req);
    if (!hit) throw err;
    return hit;
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/agent/") || url.pathname === "/api/logout" || url.pathname.includes("_pdf") || url.pathname.endsWith("/export") || url.pathname.startsWith("/api/backups")) return;

  if (url.origin === location.origin && url.pathname.startsWith("/api/")) {
    e.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (res.ok) (await caches.open(DATA)).put(req, res.clone());
        return res;
      } catch (err) {
        const hit = await caches.match(req, { cacheName: DATA });
        if (!hit) return new Response(JSON.stringify({ error: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } });
        const headers = new Headers(hit.headers); headers.set("X-From-Cache", "1");
        return new Response(await hit.blob(), { status: hit.status, headers });
      }
    })());
    return;
  }

  if (url.origin === location.origin) {
    const key = !url.pathname.includes(".") ? "/index.html" : url.pathname;
    e.respondWith(networkFirst(req, SHELL, key).catch(() => new Response("Offline", { status: 503 })));
    return;
  }
  // fonts: saved copy first, refresh in background
  e.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const hit = await cache.match(req);
    const net = fetch(req).then((res) => { if (res.ok || res.type === "opaque") cache.put(req, res.clone()); return res; }).catch(() => null);
    return hit || (await net) || new Response("", { status: 503 });
  })());
});
