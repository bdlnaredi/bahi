/* Bahi service worker: app shell offline, last-seen data when the server can't be reached */
const SHELL = "bahi-shell-v2", DATA = "bahi-data-v1";
const FILES = ["/", "/index.html", "/style.css", "/app.js", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/agent/") || url.pathname === "/api/logout") return;

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

  // app shell and fonts: serve saved copy at once, refresh it in the background
  e.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const key = url.origin === location.origin && !url.pathname.includes(".") ? "/index.html" : req;
    const hit = await cache.match(key);
    const net = fetch(req).then((res) => { if (res.ok || res.type === "opaque") cache.put(key, res.clone()); return res; }).catch(() => null);
    return hit || (await net) || new Response("Offline", { status: 503 });
  })());
});
