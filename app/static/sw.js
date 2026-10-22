// Mrigel service worker: keeps the app shell (CSS, JS, fonts, icons) and an offline page.
// Signed-in pages are never cached: they hold buyers' names and phones.
var VERSION = "mrigel-v2";
var SHELL = ["/static/app.css", "/static/app.js", "/static/favicon.svg", "/static/icon-192.png", "/offline",
  "/static/fonts/ibm-plex-sans-arabic-arabic-400-normal.woff2", "/static/fonts/ibm-plex-sans-arabic-latin-400-normal.woff2"];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(VERSION).then(function (cache) { return cache.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== VERSION; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf("/static/") === 0) {
    // static files: cache first, refresh in the background
    event.respondWith(caches.open(VERSION).then(function (cache) {
      return cache.match(request, { ignoreSearch: true }).then(function (hit) {
        var network = fetch(request).then(function (response) {
          if (response.ok) cache.put(request, response.clone());
          return response;
        }).catch(function () { return hit; });
        return hit || network;
      });
    }));
    return;
  }
  if (request.mode === "navigate") {
    // pages: always the network; the offline page only when there is none
    event.respondWith(fetch(request).catch(function () { return caches.match("/offline"); }));
  }
});
