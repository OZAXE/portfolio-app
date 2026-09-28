// Mode hors-ligne : l'appli (page, icônes, Chart.js) et les données du screener sont gardées sur
// l'appareil. En ligne, la version du réseau est toujours préférée (mises à jour immédiates) ; sans
// réseau, ou s'il met trop de temps à répondre, la dernière copie est servie.
// Les appels à l'API ne passent pas par ici : le dernier portefeuille est gardé par la page elle-même.

const SHELL_CACHE = "shell-v3";
const DATA_CACHE = "data-v1";
const PREFS_CACHE = "prefs-v1";  // apparence choisie dans Réglages (écrite par la page)
const ICONS = ["barres", "courbe", "anneau", "euro", "clair", "violet"];
const CHART_JS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js";
const SHELL = ["./", "manifest.json", "icon-192.png", "icon-512.png"];
const PAGE_TIMEOUT_MS = 4000;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE)
    // Chart.js à part : un CDN indisponible ne doit pas empêcher l'installation (il sera gardé au premier usage)
    .then((cache) => cache.addAll(SHELL).then(() => cache.add(CHART_JS).catch(() => {})))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL_CACHE, DATA_CACHE, PREFS_CACHE].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Réseau d'abord, copie gardée à jour ; sans réponse avant `timeout` ms, la copie est servie
// (le réseau continue en arrière-plan et met la copie à jour pour la prochaine fois)
function networkFirst(request, cacheName, cacheKey, timeout) {
  const network = fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(cacheName).then((cache) => cache.put(cacheKey || request, copy));
    }
    return response;
  });
  const cached = () => caches.match(cacheKey || request, { ignoreSearch: true });
  const fallback = network.catch(() => cached().then((hit) => hit || Promise.reject(new Error("hors ligne"))));
  if (!timeout) return fallback;
  const slow = new Promise((resolve) => setTimeout(resolve, timeout)).then(cached).then((hit) => hit || fallback);
  return Promise.race([fallback, slow]);
}

function cacheFirst(request, cacheName) {
  return caches.match(request).then((hit) => hit || fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(cacheName).then((cache) => cache.put(request, copy));
    }
    return response;
  }));
}

// Manifest de l'appli installée : icône et couleur de fond choisies dans Réglages > Apparence
async function manifestWithPrefs(request) {
  const response = await networkFirst(request, SHELL_CACHE);
  const prefs = await caches.open(PREFS_CACHE).then((c) => c.match("appearance")).then((r) => (r ? r.json() : {})).catch(() => ({}));
  const manifest = await response.clone().json();
  if (ICONS.includes(prefs.icon) && prefs.icon !== "barres") {
    manifest.icons = [192, 512].map((size) => ({ src: `icons/${prefs.icon}-${size}.png`, sizes: `${size}x${size}`, type: "image/png" }));
  }
  if (/^#[0-9a-fA-F]{6}$/.test(prefs.bg || "")) manifest.background_color = manifest.theme_color = prefs.bg;
  return new Response(JSON.stringify(manifest), { headers: { "Content-Type": "application/manifest+json" } });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.endsWith("/manifest.json")) {
    event.respondWith(manifestWithPrefs(request).catch(() => fetch(request)));
    return;
  }

  if (request.mode === "navigate") {
    // Toutes les pages (/, /#market...) sont la même : une seule copie, sous "./"
    event.respondWith(networkFirst(request, SHELL_CACHE, new URL("./", self.registration.scope).href, PAGE_TIMEOUT_MS));
  } else if (url.origin === self.location.origin) {
    event.respondWith(networkFirst(request, SHELL_CACHE));
  } else if (url.href === CHART_JS) {
    event.respondWith(cacheFirst(request, SHELL_CACHE));  // version figée dans l'adresse : ne change jamais
  } else if (url.hostname === "raw.githubusercontent.com" && url.pathname.includes("/screener-data/")) {
    event.respondWith(networkFirst(request, DATA_CACHE));  // screener, super investisseurs... de la dernière nuit
  }
  // Le reste (API sur Render, ntfy...) passe directement par le réseau
});
