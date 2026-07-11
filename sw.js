/* 農商雷達 Service Worker — 讓純前端站台可安裝、可離線。
   策略：
   - HTML / JSON 資料：network-first（連得上就拿最新，離線退回上次快取；HTML 再退回 index.html 殼）。
   - 圖示等靜態資源：cache-first。
   改版時把 CACHE 版本號 +1 即可讓舊快取失效（activate 會清掉非當前版本）。 */
const CACHE = "nongshang-radar-v5";
const SHELL = ["./", "./index.html", "./privacy.html", "./terms.html", "./manifest.json",
               "./icon-192.png", "./icon-512.png", "./icon.svg", "./apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL).catch(() => {}))   // 個別檔失敗不阻擋安裝
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;   // 只管同源；第三方(如地圖磚)直接放行

  const isHTML = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  const isJSON = url.pathname.endsWith(".json");

  if (isHTML || isJSON) {
    // network-first
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() =>
          caches.match(req).then((r) => r || (isHTML ? caches.match("./index.html") : undefined))
        )
    );
  } else {
    // cache-first
    e.respondWith(
      caches.match(req).then((r) =>
        r || fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
      )
    );
  }
});
