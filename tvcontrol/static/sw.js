const CACHE_NAME = 'ignocontrol-shell-v1';
const PRECACHE_ASSETS = [
    '/',
    '/static/css/app.css',
    '/static/js/app.js',
    '/icon.png',
    '/manifest.json'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_ASSETS);
        }).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    // Only cache GET requests for static assets and shell
    if (event.request.method !== 'GET') return;

    const url = new URL(event.request.url);
    if (url.origin === self.location.origin) {
        if (url.pathname.startsWith('/static/') || url.pathname === '/icon.png' || url.pathname === '/manifest.json') {
            event.respondWith(
                caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) {
                        // Fetch in background to revalidate cache
                        fetch(event.request).then((networkResponse) => {
                            if (networkResponse && networkResponse.status === 200) {
                                caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
                            }
                        }).catch(() => {});
                        return cachedResponse;
                    }
                    return fetch(event.request);
                })
            );
        }
    }
});
