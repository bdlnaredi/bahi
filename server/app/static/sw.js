/* Bahi service worker: always try the server first, fall back to the saved copy when offline */
const SHELL = "bahi-shell-v37", DATA = "bahi-data-v1";
// saved data is found whatever order a screen puts its settings in (the app's "download for offline" uses the same key)
function dataKey(u) {
  const url = new URL(u);
  const p = [...url.searchParams.entries()].filter(([, v]) => v !== "").sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  return url.origin + url.pathname + (p.length ? "?" + new URLSearchParams(p).toString() : "");
}
const FILES = ["/", "/index.html", "/style.css", "/app.js", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/* The server counts as down when it doesn't answer, answers with a gateway error (Cloudflare's 502/530 when
   Unraid is off), or takes too long; then the saved copy is used, so the app keeps working with the server off. */
const DOWN = (res) => res.status >= 500;
const later = (ms) => new Promise((r) => setTimeout(() => r("slow"), ms));

async function serverOr(req, cache, key, ms, mark) {
  const net = fetch(req, { cache: "no-store" }).then((res) => {
    if (res.ok || res.type === "opaque") cache.put(key, res.clone());
    return res;
  });
  const saved = async () => {
    const hit = await cache.match(key);
    if (!hit || !mark) return hit;
    const headers = new Headers(hit.headers); headers.set("X-From-Cache", "1");
    return new Response(await hit.blob(), { status: hit.status, headers });
  };
  try {
    const res = await Promise.race([net, later(ms)]);
    if (res === "slow") return (await saved()) || (await net);     // slow: the saved copy now, the server's answer refreshes it
    if (DOWN(res)) return (await saved()) || res;
    return res;
  } catch (err) {
    const hit = await saved();
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
        return await serverOr(req, await caches.open(DATA), dataKey(req.url), 8000, true);
      } catch (err) {
        return new Response(JSON.stringify({ error: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } });
      }
    })());
    return;
  }

  if (url.origin === location.origin) {
    const key = !url.pathname.includes(".") ? "/index.html" : url.pathname;
    e.respondWith((async () => serverOr(req, await caches.open(SHELL), key, 4000, false))().catch(() => new Response("Offline", { status: 503 })));
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
