// Service worker minimal : condition nécessaire pour que le navigateur
// propose "Ajouter à l'écran d'accueil". Pas de cache offline pour l'instant,
// à enrichir plus tard si tu veux un mode hors-ligne (cache des dernières
// analyses par exemple).

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Pass-through simple pour l'instant
  event.respondWith(fetch(event.request));
});
