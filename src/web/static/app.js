// -----------------------------------------------------------------------------
// Skript: src/web/static/app.js
// Autor: Torben Belz
// Version: 1.2.0
// Lizenz: AGPL-3.0-or-later (siehe LICENSE)
// Zweck:
// - Live-Aktualisierung der Web-UI per Polling (Konversation/Raum + Liste).
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

  // Archivierte Nachrichtenblase.
  function renderMessage(m) {
    var row = el("div", "row " + (m.direction === "out" ? "out" : "in"));
    row.setAttribute("data-id", m.id);
    row.setAttribute("data-ts", m.ts || "");
    var bubble = el("div", "msg");
    if (m.sender && m.direction === "in") bubble.appendChild(el("span", "sender", m.sender));
    if (m.decrypted) bubble.appendChild(document.createTextNode(m.body || ""));
    else bubble.appendChild(el("span", "undec", "[nicht entschluesselbar]"));
    var meta = el("div", "meta");
    meta.appendChild(el("span", null, m.ts));
    if (m.direction === "out") meta.appendChild(icon(m.status === "delivered" ? TICK2 : TICK));
    bubble.appendChild(meta);
    row.appendChild(bubble);
    return row;
  }

  // "wird gesendet"/"Fehler"-Blase aus der Outbox.
  function renderPending(p) {
    var row = el("div", "row out pending");
    var bubble = el("div", "msg");
    bubble.appendChild(document.createTextNode(p.body || ""));
    bubble.appendChild(el("div", "meta", p.status === "error" ? "Fehler" : "wird gesendet …"));
    row.appendChild(bubble);
    return row;
  }

  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.body.scrollHeight - 140;
  }

  function pollConversation(box, pendingBox) {
    var partner = box.getAttribute("data-partner");
    var lastId = parseInt(box.getAttribute("data-last-id") || "0", 10);
    fetch("/api/messages/" + encodeURIComponent(partner) + "?after_id=" + lastId, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var msgs = data.messages || [];
        // MAM-Backfill landet als Nachricht mit alter Zeit -> Seite neu laden,
        // damit alles korrekt chronologisch einsortiert wird.
        if (msgs.length) {
          var kids = box.children;
          var lastTs = kids.length ? kids[kids.length - 1].getAttribute("data-ts") : "";
          for (var k = 0; k < msgs.length; k++) {
            if (lastTs && msgs[k].ts && msgs[k].ts < lastTs) { window.location.reload(); return; }
          }
        }
        var stick = nearBottom();
        msgs.forEach(function (m) {
          box.appendChild(renderMessage(m));
          if (m.id > lastId) lastId = m.id;
        });
        box.setAttribute("data-last-id", lastId);
        pendingBox.textContent = "";
        (data.pending || []).forEach(function (p) { pendingBox.appendChild(renderPending(p)); });
        var hint = document.getElementById("empty-hint");
        if (hint && (box.children.length || pendingBox.children.length)) hint.style.display = "none";
        if (stick) window.scrollTo(0, document.body.scrollHeight);
      })
      .catch(function () {});
  }

  var SEND_ICON = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';
  function renderConvRow(it) {
    var tile = el("div", "list-row conv-tile" + (it.unread ? " has-unread" : ""));
    var a = el("a", "conv-open"); a.href = "/c/" + it.partner;
    a.appendChild(avatar(it.initials, it.hue, it.is_room));
    var main = el("span", "row-main");
    var top = el("span", "row-top");
    top.appendChild(el("span", "row-name", it.name));
    top.appendChild(el("span", "row-time", it.last));
    var sub = el("span", "row-sub");
    sub.appendChild(el("span", "row-preview", it.preview));
    if (it.unread) sub.appendChild(el("span", "pill unread", String(it.unread)));
    if (it.undecrypted) sub.appendChild(el("span", "pill warn", String(it.undecrypted)));
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
    // Antwort direkt aus der Kachel.
    var form = document.createElement("form");
    form.className = "tile-compose"; form.method = "post"; form.action = "/c/" + it.partner + "/send";
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
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (items) {
        if (!items) return;
        // Nicht neu aufbauen, waehrend in einer Kachel eine Antwort getippt wird.
        var ae = document.activeElement;
        if (ae && ae.closest && ae.closest("#conv-list .tile-compose")) return;
        items = sortItems(items);
        list.textContent = "";
        items.forEach(function (it) { list.appendChild(renderConvRow(it)); });
        var hint = document.getElementById("empty-hint");
        if (hint) hint.style.display = items.length ? "none" : "";
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

  var box = document.getElementById("messages");
  var list = document.getElementById("conv-list");
  if (box) {
    var pendingBox = document.getElementById("pending");
    window.scrollTo(0, document.body.scrollHeight);
    setInterval(function () { pollConversation(box, pendingBox); }, 3000);
  } else if (list) {
    listRefresh = function () { pollList(list); };
    // Bei gespeicherter Nicht-Standard-Sortierung sofort umsortieren (Server liefert Aktivitaet).
    if ((document.documentElement.getAttribute("data-sort") || "activity") !== "activity") listRefresh();
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
