// App-shell caching only. API calls (fetch to /api/...) are never cached -
// budget totals must always be live, never stale offline data.
//
// Network-first for the shell files themselves: always try the live version
// first and only fall back to the cached copy if the network fails (e.g.
// actually offline). This is what makes app updates show up on reload
// instead of the PWA silently serving whatever it first cached.
//
// Bump this on every release that touches a shell file. Network-first mostly
// hides a stale cache, but not entirely: a page loaded while a deploy is
// propagating can take some files from the network and others from the cache,
// which is how a build ends up running new app.js against old i18n.js (seen
// in practice - untranslated keys rendering as "allTime"). A new cache name
// makes the activate handler drop the whole previous set at once, so the next
// load is all-new or all-old, never a mix.
const CACHE = "expense-tracker-shell-v13";
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
