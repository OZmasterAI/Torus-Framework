// Service worker for offline shell caching — network-first
var CACHE_NAME = "torus-voice-v3";
var SHELL_URLS = ["/", "/style.css", "/app.js", "/manifest.json"];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(SHELL_URLS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names
          .filter(function (n) { return n !== CACHE_NAME; })
          .map(function (n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  if (event.request.url.includes("/ws") || event.request.url.includes("/health")) {
    return;
  }
  // Network-first: try server, fall back to cache for offline
  event.respondWith(
    fetch(event.request).then(function (resp) {
      var clone = resp.clone();
      caches.open(CACHE_NAME).then(function (cache) {
        cache.put(event.request, clone);
      });
      return resp;
    }).catch(function () {
      return caches.match(event.request);
    })
  );
});
