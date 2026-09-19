const CACHE = "sketchbot-setup-v1";
const FILES = ["./", "./index.html", "./style.css", "./assets/setup.js", "./assets/setup.css",
  "./manifest.webmanifest", "./assets/icon-192.png", "./assets/icon-512.png", "./assets/studio-preview.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(names => Promise.all(names.filter(name => name.startsWith("sketchbot-setup-") && name !== CACHE)
    .map(name => caches.delete(name)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  if (event.request.method !== "GET" || !event.request.url.startsWith(self.registration.scope)) return;
  const url = new URL(event.request.url);
  if (url.pathname.endsWith("install.sh")) return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) { const copy = response.clone(); caches.open(CACHE).then(cache => cache.put(event.request, copy)); }
    return response;
  }).catch(async () => (await caches.match(event.request)) || new Response("Offline asset unavailable", { status: 503 })));
});