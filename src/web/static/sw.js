// -----------------------------------------------------------------------------
// Skript: src/web/static/sw.js
// Autor: Torben Belz
// Version: 1.1.0
// Lizenz: AGPL-3.0-or-later (siehe LICENSE)
// Zweck:
// - Service Worker fuer Web Push: zeigt eingehende Push-Notizen an und oeffnet
//   beim Antippen die betreffende Konversation.
// Hinweis:
// - Der Push-Payload enthaelt bewusst keinen Nachrichteninhalt, nur einen Hinweis.
// - renotify=true: bei gleichem tag (= Chat) wird erneut alarmiert, nicht stumm
//   ersetzt (sonst bleibt das Telefon ab der zweiten Nachricht ruhig).
// -----------------------------------------------------------------------------

self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  var title = data.title || "Chat";
  var body = data.body || "Neue Nachricht";
  var url = data.url || "/";
  event.waitUntil(self.registration.showNotification(title, {
    body: body,
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    data: { url: url },
    tag: url,
    renotify: true
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        if ("focus" in list[i]) {
          if (list[i].navigate) { try { list[i].navigate(url); } catch (e) {} }
          return list[i].focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
