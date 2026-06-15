// -----------------------------------------------------------------------------
// Skript: src/web/static/app.js
// Autor: Torben Belz
// Version: 1.9.0
// Lizenz: AGPL-3.0-or-later (siehe LICENSE)
// Zweck:
// - Live-Aktualisierung der Web-UI per Polling (Konversation/Raum + Liste).
// - Minimieren/Wiederoeffnen von Konversationskacheln (lokal gespeichert);
//   eine neue Nachricht klappt eine minimierte Kachel automatisch wieder auf.
// - Schliessen von Chats (dauerhaft ausgeblendet, Daten bleiben; wiederherstellbar
//   ueber "Geschlossene Chats" oder durch direktes Oeffnen).
// - Relative Zeitangabe ("vor X Min") vor dem Zeitstempel der letzten Nachricht.
// - Anhaenge (OMEMO-Media): Bilder werden inline angezeigt, Dateien verlinkt
//   (Auslieferung entschluesselt ueber den /media-Proxy).
// Hinweis:
// - Nutzerinhalte werden ueber textContent eingefuegt (XSS-Schutz). SVG-Icons
//   stammen aus statischen Markup-Konstanten, nicht aus Nutzerdaten.
// -----------------------------------------------------------------------------

(function () {
  "use strict";

  var TICK = '<svg class="tick" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l5 5L20 6"/></svg>';
  var TICK2 = '<svg class="tick delivered" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1 13l4 4L13 7"/><path d="M11 13l4 4L23 7"/></svg>';

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // Statisches SVG-Markup als Element (keine Nutzerdaten).
  function icon(markup) {
    var span = document.createElement("span");
    span.style.display = "inline-flex";
    span.innerHTML = markup;
    return span.firstChild;
  }

  function avatar(initials, hue, room) {
    var a = el("span", "avatar" + (room ? " room" : ""), initials);
    a.style.setProperty("--h", hue);
    return a;
  }

  // Minimierte (geschlossene) Konversationen: Map partner -> last_ts beim Schliessen.
  // Persistiert in localStorage, damit die Auswahl Reloads ueberlebt. Trifft spaeter
  // eine neuere Nachricht ein (groesseres last_ts), klappt die Kachel automatisch
  // wieder auf -- so geht kein Eingang verloren, nur der Platz wird freigeraeumt.
  function getCollapsed() {
    try { return JSON.parse(localStorage.getItem("collapsed") || "{}") || {}; } catch (e) { return {}; }
  }
  function setCollapsed(map) {
    try { localStorage.setItem("collapsed", JSON.stringify(map)); } catch (e) {}
  }
  function collapseConv(partner, ts) {
    var m = getCollapsed(); m[partner] = ts || 0; setCollapsed(m);
    if (listRefresh) listRefresh();
  }
  function expandConv(partner) {
    var m = getCollapsed(); delete m[partner]; setCollapsed(m);
    if (listRefresh) listRefresh();
  }

  // Geschlossene Konversationen: Liste von partner-JIDs in localStorage. Anders als
  // beim Minimieren bleiben sie ausgeblendet -- auch bei neuen Nachrichten. Sichtbar
  // wieder nur ueber den Bereich "Geschlossene Chats" oder durch direktes Oeffnen.
  function getClosed() {
    try { var a = JSON.parse(localStorage.getItem("closed") || "[]"); return Array.isArray(a) ? a : []; } catch (e) { return []; }
  }
  function setClosed(arr) {
    try { localStorage.setItem("closed", JSON.stringify(arr)); } catch (e) {}
  }
  function closeConv(partner) {
    var a = getClosed(); if (a.indexOf(partner) < 0) a.push(partner); setClosed(a);
    // Aus dem Minimiert-Zustand entfernen, damit eine Konversation nicht doppelt gilt.
    var m = getCollapsed(); if (m[partner] != null) { delete m[partner]; setCollapsed(m); }
    if (listRefresh) listRefresh();
  }
  function reopenConv(partner) {
    setClosed(getClosed().filter(function (p) { return p !== partner; }));
    if (listRefresh) listRefresh();
  }

  // Relative Zeitangabe ("vor 5 Min") aus epoch-Sekunden (last_ts). Bleibt aktuell,
  // weil die Konversationsliste regelmaessig neu gerendert wird.
  function relTime(ts) {
    if (!ts) return "";
    var s = Math.floor(Date.now() / 1000 - ts);
    if (s < 0) s = 0;
    if (s < 45) return "gerade eben";
    if (s < 3600) { var m = Math.round(s / 60); return "vor " + (m || 1) + " Min"; }
    if (s < 86400) return "vor " + Math.round(s / 3600) + " Std";
    if (s < 172800) return "gestern";
    return "vor " + Math.round(s / 86400) + " Tagen";
  }

  // --- Web Push ------------------------------------------------------------
  var swReg = null;
  function urlB64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(base64), arr = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  }
  function ensureServiceWorker() {
    if (!("serviceWorker" in navigator)) return Promise.reject(new Error("unsupported"));
    if (swReg) return Promise.resolve(swReg);
    return navigator.serviceWorker.register("/sw.js").then(function (r) { swReg = r; return r; });
  }
  // Permission + Abo sicherstellen und an den Server melden.
  function ensurePushSubscription() {
    return fetch("/api/push/config", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (cfg) {
        if (!cfg || !cfg.enabled || !cfg.publicKey) throw new Error("push-disabled");
        if (!("Notification" in window) || !("PushManager" in window)) throw new Error("unsupported");
        return Notification.requestPermission().then(function (perm) {
          if (perm !== "granted") throw new Error("denied");
          return ensureServiceWorker().then(function (reg) {
            return reg.pushManager.getSubscription().then(function (sub) {
              return sub || reg.pushManager.subscribe({
                userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(cfg.publicKey)
              });
            });
          });
        });
      })
      .then(function (sub) {
        return fetch("/api/push/subscribe", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(sub)
        });
      });
  }
  // Service Worker beim Laden registrieren (fuer den Empfang vorhandener Abos).
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").then(function (r) { swReg = r; }).catch(function () {});
  }

  // Archivierte Nachrichtenblase.
  function renderMessage(m) {
    var row = el("div", "row " + (m.direction === "out" ? "out" : "in"));
    row.setAttribute("data-id", m.id);
    row.setAttribute("data-ts", m.ts || "");
    var bubble = el("div", "msg");
    if (m.sender && m.direction === "in") bubble.appendChild(el("span", "sender", m.sender));
    if (m.decrypted && m.media) {
      // Anhang (entschluesselt ueber den /media-Proxy ausgeliefert).
      var ml = document.createElement("a");
      ml.href = m.media.url; ml.target = "_blank"; ml.rel = "noopener";
      if (m.media.kind === "image") {
        ml.className = "msg-media";
        var img = document.createElement("img");
        img.className = "msg-img"; img.src = m.media.url; img.loading = "lazy";
        img.alt = m.media.name || "Bild";
        ml.appendChild(img);
      } else {
        ml.className = "msg-file";
        ml.textContent = "Anhang: " + (m.media.name || "Datei");
      }
      bubble.appendChild(ml);
    } else if (m.decrypted) {
      if (m.quote) bubble.appendChild(el("div", "msg-quote", m.quote));
      bubble.appendChild(el("div", "msg-text", m.text || ""));
    } else {
      bubble.appendChild(el("span", "undec", "[nicht entschluesselbar]"));
    }
    if (m.decrypted && m.text) {
      var rb = document.createElement("button");
      rb.type = "button"; rb.className = "reply-btn"; rb.title = "Antworten"; rb.setAttribute("aria-label", "Antworten");
      rb.setAttribute("data-quote", m.text);
      rb.setAttribute("data-who", m.sender ? m.sender : (m.direction === "out" ? "Du" : (window.__convName || "")));
      rb.appendChild(icon(REPLY_ICON));
      bubble.appendChild(rb);
    }
    var meta = el("div", "meta");
    meta.appendChild(el("span", null, m.ts));
    if (m.direction === "out") meta.appendChild(icon(m.status === "delivered" ? TICK2 : TICK));
    bubble.appendChild(meta);
    row.appendChild(bubble);
    return row;
  }

  // "wird gesendet"/"Fehler"-Blase aus der Outbox.
  function renderPending(p) {
    var row = el("div", "row out pending" + (p.status === "error" ? " failed" : ""));
    var bubble = el("div", "msg");
    bubble.appendChild(document.createTextNode(p.body || ""));
    var info = p.status === "error" ? ("Fehler: " + (p.error || "unbekannt")) : "wird gesendet …";
    bubble.appendChild(el("div", "meta", info));
    if (p.status === "error" && p.id) {
      // Fehlgeschlagenen Auftrag verwerfen (Formular-POST -> Reload).
      var box = document.getElementById("messages");
      var partner = box ? box.getAttribute("data-partner") : "";
      var form = document.createElement("form");
      form.className = "dismiss-form"; form.method = "post";
      form.action = "/c/" + partner + "/dismiss/" + p.id;
      var b = document.createElement("button");
      b.type = "submit"; b.className = "dismiss-btn"; b.title = "Verwerfen";
      b.setAttribute("aria-label", "Fehlgeschlagene Nachricht verwerfen");
      b.textContent = "×";
      form.appendChild(b); bubble.appendChild(form);
    }
    row.appendChild(bubble);
    return row;
  }

  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.body.scrollHeight - 140;
  }

  var SEND_ICON = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';
  var REPLY_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>';
  var MIN_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>';
  var CLOSE_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

  // Kompakter Platzhalter fuer eine weggelegte Konversation; onClick holt sie zurueck.
  function renderConvChip(it, onClick) {
    var chip = document.createElement("button");
    chip.type = "button"; chip.className = "conv-chip";
    chip.title = "Wieder oeffnen: " + it.name;
    chip.appendChild(avatar(it.initials, it.hue, it.is_room));
    chip.appendChild(el("span", "chip-name", it.name));
    if (it.unread) chip.appendChild(el("span", "pill unread", String(it.unread)));
    chip.addEventListener("click", onClick);
    return chip;
  }

  function renderConvRow(it) {
    var tile = el("div", "list-row conv-tile" + (it.unread ? " has-unread" : ""));
    var a = el("a", "conv-open"); a.href = "/c/" + it.partner;
    a.appendChild(avatar(it.initials, it.hue, it.is_room));
    var main = el("span", "row-main");
    var top = el("span", "row-top");
    top.appendChild(el("span", "row-name", it.name));
    var rel = relTime(it.last_ts);
    if (rel) top.appendChild(el("span", "row-rel", rel));
    top.appendChild(el("span", "row-time", it.last));
    var sub = el("span", "row-sub");
    sub.appendChild(el("span", "row-preview", it.preview));
    if (it.unread) sub.appendChild(el("span", "pill unread", String(it.unread)));
    main.appendChild(top); main.appendChild(sub);
    if (it.recent && it.recent.length) {
      var rec = el("span", "conv-recent");
      for (var j = 0; j < it.recent.length; j++) {
        rec.appendChild(el("span", "cr-line " + (it.recent[j].direction === "out" ? "out" : "in"), it.recent[j].text));
      }
      main.appendChild(rec);
    }
    a.appendChild(main);
    tile.appendChild(a);
    // Kachel-Aktionen oben rechts: Minimieren (kehrt bei neuer Nachricht zurueck)
    // und Schliessen (bleibt ausgeblendet; Daten bleiben erhalten).
    var actions = el("span", "tile-actions");
    var minBtn = document.createElement("button");
    minBtn.type = "button"; minBtn.className = "tile-act tile-min"; minBtn.title = "Minimieren";
    minBtn.setAttribute("aria-label", "Konversation minimieren");
    minBtn.appendChild(icon(MIN_ICON));
    minBtn.addEventListener("click", function (e) {
      e.preventDefault(); e.stopPropagation();
      collapseConv(it.partner, it.last_ts || 0);
    });
    var closeBtn = document.createElement("button");
    closeBtn.type = "button"; closeBtn.className = "tile-act tile-close"; closeBtn.title = "Chat schliessen (ausblenden)";
    closeBtn.setAttribute("aria-label", "Konversation schliessen");
    closeBtn.appendChild(icon(CLOSE_ICON));
    closeBtn.addEventListener("click", function (e) {
      e.preventDefault(); e.stopPropagation();
      closeConv(it.partner);
    });
    actions.appendChild(minBtn); actions.appendChild(closeBtn);
    tile.appendChild(actions);
    // Antwort direkt aus der Kachel.
    var form = document.createElement("form");
    form.className = "tile-compose"; form.method = "post"; form.action = "/c/" + it.partner + "/send";
    form.setAttribute("data-partner", it.partner);
    var input = document.createElement("input");
    input.type = "text"; input.name = "body"; input.placeholder = "Antwort …"; input.autocomplete = "off";
    input.setAttribute("aria-label", "Antwort");
    var btn = document.createElement("button"); btn.type = "submit"; btn.setAttribute("aria-label", "Senden");
    btn.appendChild(icon(SEND_ICON));
    form.appendChild(input); form.appendChild(btn);
    tile.appendChild(form);
    return tile;
  }

  // Sortiert die Konversationen nach der gewaehlten Einstellung. JS-sort ist stabil,
  // daher behalten gleichrangige Eintraege die Aktivitaets-Reihenfolge der API.
  function sortItems(items) {
    var sort = document.documentElement.getAttribute("data-sort") || "activity";
    if (sort === "name") {
      return items.slice().sort(function (a, b) {
        var x = (a.name || "").toLowerCase(), y = (b.name || "").toLowerCase();
        return x < y ? -1 : (x > y ? 1 : 0);
      });
    }
    if (sort === "unread") {
      return items.slice().sort(function (a, b) { return (b.unread || 0) - (a.unread || 0); });
    }
    return items; // activity: API-Reihenfolge (neueste zuerst)
  }

  function pollList(list) {
    fetch("/api/conversations", { credentials: "same-origin" })
      .then(function (r) {
        // Abgelaufene Session -> nicht still einfrieren, sondern zur Anmeldung.
        if (r.status === 401) { window.location.href = "/login"; return null; }
        return r.ok ? r.json() : null;
      })
      .then(function (items) {
        if (!items) return;
        // Nur pausieren, solange tatsaechlich ein (nicht-leerer) Antwort-Entwurf getippt
        // wird -- damit das Tile beim Tippen nicht wegspringt. Ein bloss fokussiertes,
        // leeres Antwortfeld darf die Liste NICHT einfrieren (sonst aktualisiert ein
        // Tab nie mehr, wenn der Cursor in einem leeren Feld steht).
        var ae = document.activeElement;
        var focusPartner = null;
        if (ae && ae.closest && ae.closest("#conv-list .tile-compose")) {
          if ((ae.value || "").trim()) return;
          var ff = ae.closest(".tile-compose");
          focusPartner = ff ? ff.getAttribute("data-partner") : null;
        }
        items = sortItems(items);
        // Geschlossene ganz ausblenden; Minimierte in die Ablage; eine seither neuere
        // Nachricht klappt eine minimierte (nicht: geschlossene) Kachel automatisch auf.
        var closedArr = getClosed();
        var closedSet = {};
        closedArr.forEach(function (p) { closedSet[p] = true; });
        var collapsed = getCollapsed();
        var dirty = false, visible = [], hidden = [], gone = [];
        items.forEach(function (it) {
          if (closedSet[it.partner]) { gone.push(it); return; }
          var marker = collapsed[it.partner];
          if (marker != null && !(it.last_ts > marker)) {
            hidden.push(it);
          } else {
            if (marker != null) { delete collapsed[it.partner]; dirty = true; }
            visible.push(it);
          }
        });
        if (dirty) setCollapsed(collapsed);
        list.textContent = "";
        visible.forEach(function (it) { list.appendChild(renderConvRow(it)); });
        if (hidden.length) {
          var tray = el("div", "collapsed-tray");
          tray.appendChild(el("span", "tray-label", "Minimiert (" + hidden.length + ")"));
          var chips = el("div", "tray-chips");
          hidden.forEach(function (it) {
            chips.appendChild(renderConvChip(it, (function (p) { return function () { expandConv(p); }; })(it.partner)));
          });
          tray.appendChild(chips);
          list.appendChild(tray);
        }
        if (gone.length) {
          // Eigener, standardmaessig eingeklappter Bereich -- geschlossene Chats bleiben
          // unsichtbar, sind aber jederzeit wiederherstellbar (Daten bleiben erhalten).
          var det = document.createElement("details");
          det.className = "closed-section";
          var sum = document.createElement("summary");
          sum.textContent = "Geschlossene Chats (" + gone.length + ")";
          det.appendChild(sum);
          var cchips = el("div", "tray-chips");
          gone.forEach(function (it) {
            cchips.appendChild(renderConvChip(it, (function (p) { return function () { reopenConv(p); }; })(it.partner)));
          });
          det.appendChild(cchips);
          list.appendChild(det);
        }
        var hint = document.getElementById("empty-hint");
        if (hint) hint.style.display = items.length ? "none" : "";
        // Fokus auf das (leere) Antwortfeld zurueckholen, das vor dem Neuaufbau aktiv war.
        if (focusPartner) {
          var sel = '.tile-compose[data-partner="' + focusPartner.replace(/["\\]/g, "\\$&") + '"] input[name=body]';
          var again = list.querySelector(sel);
          if (again) again.focus();
        }
      })
      .catch(function () {});
  }

  // Wird gesetzt, sobald eine Konversationsliste auf der Seite ist (fuer Re-Render bei Sortwechsel).
  var listRefresh = null;

  // Design-Umschalter (Modus, Akzentfarbe, Ansicht, Spalten, Sortierung): sofort anwenden + merken.
  var DESIGN_KEYS = ["theme", "accent", "view", "cols", "sort", "lines", "density"];
  var DESIGN_DEFAULT = { theme: "auto", accent: "blue", view: "list", cols: "auto", sort: "activity", lines: "4", density: "comfortable" };
  function applyDesign(key, val) {
    document.documentElement.setAttribute("data-" + key, val);
    try { localStorage.setItem(key, val); } catch (e) {}
    markDesign();
    if (key === "sort" && listRefresh) listRefresh();
    var menu = document.querySelector("details.design-menu");
    if (menu) menu.removeAttribute("open");
  }
  function markDesign() {
    for (var k = 0; k < DESIGN_KEYS.length; k++) {
      var key = DESIGN_KEYS[k];
      var cur = document.documentElement.getAttribute("data-" + key) || DESIGN_DEFAULT[key];
      var els = document.querySelectorAll("[data-" + key + "-set]");
      for (var i = 0; i < els.length; i++) {
        els[i].classList.toggle("active", els[i].getAttribute("data-" + key + "-set") === cur);
      }
    }
  }
  (function () {
    var bound = false;
    function bind(b, key) {
      b.addEventListener("click", function () { applyDesign(key, b.getAttribute("data-" + key + "-set")); });
    }
    for (var k = 0; k < DESIGN_KEYS.length; k++) {
      var key = DESIGN_KEYS[k];
      var els = document.querySelectorAll("[data-" + key + "-set]");
      for (var i = 0; i < els.length; i++) { bind(els[i], key); bound = true; }
    }
    if (bound) markDesign();
  })();

  // Login-Wartemodus: Validierungsstatus pollen (vom Daemon-Manager gesetzt).
  var wait = document.getElementById("login-wait");
  if (wait) {
    setInterval(function () {
      fetch("/api/login_status", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          if (d.status === "ok") window.location.href = "/";
          else if (d.status === "failed") window.location.href = "/login?error=1";
        })
        .catch(function () {});
    }, 1500);
    return;
  }

  // Online-Status live halten (App-Bar-Toggle): Verbindet … -> Online etc.
  var onlineBtn = document.getElementById("online-btn");
  if (onlineBtn) {
    var refreshOnline = function () {
      fetch("/api/account_status", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) {
          if (!s) return;
          var lbl = document.getElementById("online-label");
          var val = document.getElementById("online-value");
          if (lbl) lbl.textContent = s.label;
          if (val) val.value = s.next;
          onlineBtn.className = "online-btn " + s.cls;
        })
        .catch(function () {});
    };
    setInterval(refreshOnline, 3000);
  }

  // OMEMO-Geraete / Verifizierung
  var contactDevices = document.getElementById("contact-devices");
  if (contactDevices) {
    var devPartner = contactDevices.getAttribute("data-partner");
    var TRUST = {
      verified: { label: "Verifiziert", cls: "ok" },
      trusted: { label: "Vertraut (blind)", cls: "muted" },
      undecided: { label: "Unbestaetigt", cls: "warn" },
      distrusted: { label: "Gesperrt", cls: "bad" }
    };
    function devBtn(d, value, label, cls) {
      var b = el("button", cls, label); b.type = "button";
      b.addEventListener("click", function () {
        b.disabled = true;
        fetch("/devices/" + encodeURIComponent(devPartner) + "/trust", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: "identity_hex=" + encodeURIComponent(d.identity_hex) + "&value=" + value
        }).then(function () { setTimeout(loadDevices, 1500); }).catch(function () { b.disabled = false; });
      });
      return b;
    }
    function devCard(d) {
      var card = el("div", "dev-card");
      var head = el("div", "dev-head");
      head.appendChild(el("span", "dev-id", "Geraet " + d.device_id));
      var t = TRUST[d.trust] || TRUST.undecided;
      head.appendChild(el("span", "dev-trust " + t.cls, t.label));
      card.appendChild(head);
      card.appendChild(el("div", "dev-fp", d.fingerprint || ""));
      if (!d.is_own) {
        var actions = el("div", "dev-actions");
        if (d.trust !== "verified") actions.appendChild(devBtn(d, "verify", "Verifizieren", "btn"));
        if (d.trust !== "distrusted") actions.appendChild(devBtn(d, "distrust", "Sperren", "btn ghost"));
        card.appendChild(actions);
      }
      return card;
    }
    function loadDevices() {
      fetch("/api/devices/" + encodeURIComponent(devPartner), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (devs) {
          if (!devs) return;
          var own = document.getElementById("own-devices");
          own.textContent = ""; contactDevices.textContent = "";
          var o = [], c = [], i;
          for (i = 0; i < devs.length; i++) { (devs[i].is_own ? o : c).push(devs[i]); }
          if (!o.length) own.appendChild(el("p", "dev-loading", "—"));
          for (i = 0; i < o.length; i++) own.appendChild(devCard(o[i]));
          if (!c.length) contactDevices.appendChild(el("p", "dev-loading", "Noch keine Geraete geladen (Aktualisierung laeuft) …"));
          for (i = 0; i < c.length; i++) contactDevices.appendChild(devCard(c[i]));
        }).catch(function () {});
    }
    loadDevices();
    var devTries = 0;
    var devTimer = setInterval(function () { devTries++; loadDevices(); if (devTries >= 6) clearInterval(devTimer); }, 2500);
  }

  var box = document.getElementById("messages");
  var list = document.getElementById("conv-list");
  if (box) {
    var pendingBox = document.getElementById("pending");
    var convPartner = box.getAttribute("data-partner");
    var lastId = parseInt(box.getAttribute("data-last-id") || "0", 10);
    var loadingOlder = false;

    // Wer einen Chat oeffnet, will ihn sehen: aus geschlossen/minimiert entfernen,
    // damit er beim Zurueckkehren zur Liste wieder normal erscheint.
    setClosed(getClosed().filter(function (p) { return p !== convPartner; }));
    var _cm = getCollapsed(); if (_cm[convPartner] != null) { delete _cm[convPartner]; setCollapsed(_cm); }

    // Live: neue Nachrichten anhaengen. Erkennt MAM-Nachladungen (alte Zeit) und laedt
    // dann die Seite neu fuer korrekte Chronologie -- ausser waehrend manuellem Nachladen.
    function pollConversation() {
      fetch("/api/messages/" + encodeURIComponent(convPartner) + "?after_id=" + lastId, { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          var msgs = data.messages || [];
          if (loadingOlder) {
            // Nur Cursor mitziehen, nicht anhaengen/neu laden (Paginierung haengt selbst an).
            msgs.forEach(function (m) { if (m.id > lastId) lastId = m.id; });
            pendingBox.textContent = "";
            (data.pending || []).forEach(function (p) { pendingBox.appendChild(renderPending(p)); });
            return;
          }
          if (msgs.length) {
            var kids = box.children;
            var lastTs = kids.length ? kids[kids.length - 1].getAttribute("data-ts") : "";
            for (var k = 0; k < msgs.length; k++) {
              if (lastTs && msgs[k].ts && msgs[k].ts < lastTs) { window.location.reload(); return; }
            }
          }
          var stick = nearBottom();
          msgs.forEach(function (m) { box.appendChild(renderMessage(m)); if (m.id > lastId) lastId = m.id; });
          pendingBox.textContent = "";
          (data.pending || []).forEach(function (p) { pendingBox.appendChild(renderPending(p)); });
          var hint = document.getElementById("empty-hint");
          if (hint && (box.children.length || pendingBox.children.length)) hint.style.display = "none";
          if (stick) window.scrollTo(0, document.body.scrollHeight);
        })
        .catch(function () {});
    }
    window.scrollTo(0, document.body.scrollHeight);
    setInterval(pollConversation, 3000);

    // --- Antworten auf eine bestimmte Nachricht (Zitat) ---
    window.__convName = (document.querySelector(".conv-head .name") || {}).textContent || "";
    box.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest(".reply-btn") : null;
      if (!btn) return;
      e.preventDefault();
      var quote = btn.getAttribute("data-quote") || "";
      var who = btn.getAttribute("data-who") || "";
      var qi = document.getElementById("reply-quote");
      var pv = document.getElementById("reply-preview");
      if (qi) qi.value = quote;
      var w = document.getElementById("reply-who"); if (w) w.textContent = "Antwort an " + who;
      var t = document.getElementById("reply-text"); if (t) t.textContent = quote.length > 120 ? quote.slice(0, 120) + "…" : quote;
      if (pv) pv.hidden = false;
      var ci = document.querySelector(".composer input[name=body]"); if (ci) ci.focus();
    });
    var replyCancel = document.getElementById("reply-cancel");
    if (replyCancel) replyCancel.addEventListener("click", function () {
      var qi = document.getElementById("reply-quote"); if (qi) qi.value = "";
      var pv = document.getElementById("reply-preview"); if (pv) pv.hidden = true;
    });

    // Anhang: bei Dateiauswahl den Composer direkt absenden (Upload -> Daemon).
    var attach = document.getElementById("attach-input");
    if (attach) attach.addEventListener("change", function () {
      if (attach.files && attach.files.length && attach.form) {
        if (attach.form.requestSubmit) attach.form.requestSubmit(); else attach.form.submit();
      }
    });

    // Push-Glocke: pro Chat an/aus. Beim Aktivieren wird (einmalig) das Geraet abonniert.
    var bell = document.getElementById("push-bell");
    if (bell) {
      var bellPartner = bell.getAttribute("data-partner");
      var setBell = function (on) {
        bell.classList.toggle("on", !!on);
        bell.setAttribute("aria-pressed", on ? "true" : "false");
      };
      fetch("/api/push/pref/" + encodeURIComponent(bellPartner), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (st) { if (st) setBell(st.enabled); }).catch(function () {});
      bell.addEventListener("click", function () {
        var on = bell.getAttribute("aria-pressed") !== "true";
        bell.disabled = true;
        (on ? ensurePushSubscription() : Promise.resolve()).then(function () {
          return fetch("/api/push/pref/" + encodeURIComponent(bellPartner), {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: "value=" + (on ? "1" : "0")
          });
        }).then(function () { setBell(on); bell.disabled = false; })
          .catch(function (e) {
            bell.disabled = false;
            var msg = e && e.message;
            if (msg === "denied") alert("Benachrichtigungen sind im Browser blockiert. Bitte in den Browser-Einstellungen erlauben.");
            else if (msg === "unsupported") alert("Dein Browser/Geraet unterstuetzt keine Web-Push. (iPhone: App zum Home-Bildschirm hinzufuegen.)");
            else alert("Push konnte nicht aktiviert werden.");
          });
      });
    }

    // --- Paginierung: aeltere Nachrichten nachladen (lokal, dann per MAM) ---
    var older = document.getElementById("loadolder");
    if (older) {
      var olderBtn = document.getElementById("loadolder-btn");
      var cursorTs = parseFloat(older.getAttribute("data-oldest-ts") || "0");
      var cursorId = parseInt(older.getAttribute("data-oldest-id") || "0", 10);
      var localExhausted = older.getAttribute("data-has-more") === "0";

      function prependMessages(msgs) {
        if (!msgs.length) return;
        var scroller = document.scrollingElement || document.documentElement;
        var prevH = scroller.scrollHeight, prevTop = scroller.scrollTop;
        var frag = document.createDocumentFragment();
        msgs.forEach(function (m) { frag.appendChild(renderMessage(m)); if (m.id > lastId) lastId = m.id; });
        box.insertBefore(frag, box.firstChild);
        cursorTs = msgs[0].ts_raw; cursorId = msgs[0].id;
        scroller.scrollTop = prevTop + (scroller.scrollHeight - prevH);  // Scrollposition erhalten
      }
      function loadLocal() {
        return fetch("/api/older/" + encodeURIComponent(convPartner) + "?before_ts=" + cursorTs + "&before_id=" + cursorId,
          { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; });
      }
      function setLabel() { olderBtn.textContent = localExhausted ? "Aeltere vom Server laden" : "Aeltere anzeigen"; }

      olderBtn.addEventListener("click", function () {
        if (olderBtn.disabled) return;
        olderBtn.disabled = true;
        if (!localExhausted) {
          olderBtn.textContent = "Laedt …";
          loadLocal().then(function (d) {
            if (d && d.messages.length) prependMessages(d.messages);
            localExhausted = !(d && d.has_more);
            setLabel(); olderBtn.disabled = false;
          }).catch(function () { setLabel(); olderBtn.disabled = false; });
          return;
        }
        // Lokal erschoepft -> vom Server (MAM) holen, dann lokal nachladen.
        olderBtn.textContent = "Lade vom Server …";
        loadingOlder = true;
        fetch("/c/" + encodeURIComponent(convPartner) + "/loadmore", { method: "POST", credentials: "same-origin" })
          .then(function () {
            var tries = 0;
            (function poll() {
              tries++;
              loadLocal().then(function (d) {
                if (d && d.messages.length) {
                  prependMessages(d.messages);
                  localExhausted = !(d && d.has_more);
                  loadingOlder = false; setLabel(); olderBtn.disabled = false;
                } else if (tries < 6) { setTimeout(poll, 1500); }
                else { loadingOlder = false; olderBtn.textContent = "Aeltere vom Server laden"; olderBtn.disabled = false; }
              }).catch(function () { loadingOlder = false; setLabel(); olderBtn.disabled = false; });
            })();
          })
          .catch(function () { loadingOlder = false; setLabel(); olderBtn.disabled = false; });
      });
    }
  } else if (list) {
    listRefresh = function () { pollList(list); };
    // Sofort per JS rendern: bringt Minimieren-Knoepfe und die "Minimiert"-Ablage und
    // wendet gespeicherte Sortierung sowie minimierte Kacheln direkt an.
    listRefresh();
    setInterval(listRefresh, 5000);

    // Antworten direkt aus der Kachel (ohne Seitenwechsel), per Delegation.
    list.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form.classList || !form.classList.contains("tile-compose")) return;
      e.preventDefault();
      var input = form.querySelector("input[name=body]");
      var text = input ? input.value.trim() : "";
      if (!text) return;
      fetch(form.action, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "body=" + encodeURIComponent(text)
      }).then(function () {
        // Optimistisch sofort anzeigen; der Daemon versendet und archiviert im Hintergrund.
        var rec = form.parentNode.querySelector(".conv-recent");
        if (rec) rec.appendChild(el("span", "cr-line out", "Du: " + text));
        if (input) input.value = "";
      }).catch(function () {});
    });
  }
})();
