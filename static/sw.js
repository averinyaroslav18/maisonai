// Кэшируем только оболочку интерфейса; данные и файлы всегда берутся с компьютера.
const V = "mai-v15";
const SHELL = ["/", "/app.css", "/js/app.js", "/js/lib.js", "/js/fx.js", "/js/orb.js", "/js/icons.js", "/vendor/three.module.min.js", "/vendor/RoomEnvironment.js", "/fonts/inter-var.woff2", "/fonts/plexmono-Regular.woff2", "/fonts/plexmono-Medium.woff2", "/fonts/plexmono-SemiBold.woff2"];
self.addEventListener("install", e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api/") || u.pathname.startsWith("/files/")) return;
  e.respondWith(fetch(e.request).then(r => { const cp = r.clone(); caches.open(V).then(c => c.put(e.request, cp)); return r; }).catch(() => caches.match(e.request)));
});
