/* Fietscoach service worker.
   Pagina's: eerst het netwerk, zonder verbinding de laatst geladen versie.
   Opmaak, letters en iconen: direct uit de cache, op de achtergrond ververst.
   Formulieren (POST) gaan altijd gewoon naar de server. */
const VERSIE = 'fietscoach-1';
const BASIS = ['/static/styles.css', '/static/fonts/fonts.css', '/static/icoon-192.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSIE).then(c => c.addAll(BASIS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== VERSIE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function bewaarbaar(r) {
  // Niet bewaren: fouten, en doorverwijzingen (bv. naar de inlogpagina van Authelia).
  return r && r.ok && !r.redirected && r.type === 'basic';
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).then(r => {
      if (bewaarbaar(r)) { const kopie = r.clone(); caches.open(VERSIE).then(c => c.put(url.pathname, kopie)); }
      return r;
    }).catch(() => caches.match(url.pathname).then(r => r || caches.match('/'))
      .then(r => r || new Response('<h1>Offline</h1><p>Nog geen opgeslagen versie van deze pagina.</p>',
        {headers: {'Content-Type': 'text/html; charset=utf-8'}}))));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.open(VERSIE).then(c => c.match(req).then(bewaard => {
      const vers = fetch(req).then(r => { if (bewaarbaar(r)) c.put(req, r.clone()); return r; }).catch(() => bewaard);
      return bewaard || vers;
    })));
  }
});
