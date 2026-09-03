// App-shell caching only. API calls (fetch to /api/...) are never cached -
// budget totals must always be live, never stale offline data.
//
// Network-first for the shell files themselves: always try the live version
// first and only fall back to the cached copy if the network fails (e.g.
// actually offline). This is what makes app updates show up on reload
// instead of the PWA silently serving whatever it first cached.
const CACHE = "expense-tracker-shell-v9";
const SHELL_FILES = ["./", "./index.html", "./style.css", "./app.js", "./i18n.js", "./config.js", "./manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/webhook/")) return;

  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});
