self.addEventListener('install', (e) => {
  e.waitUntil(caches.open('money-app-v1').then(cache => cache.addAll([
    '/app/',
    '/app/index.html',
    '/app/manifest.json'
  ])));
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then(resp => resp || fetch(e.request))
  );
});

