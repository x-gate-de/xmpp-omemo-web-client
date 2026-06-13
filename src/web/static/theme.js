// -----------------------------------------------------------------------------
// Skript: src/web/static/theme.js
// Autor: Torben Belz
// Version: 1.0.0
// Lizenz: AGPL-3.0-or-later (siehe LICENSE)
// Zweck:
// - Setzt das gespeicherte Theme (Modus + Akzentfarbe) VOR dem ersten Paint,
//   damit es beim Laden nicht kurz aufflackert. Laeuft blockierend im <head>.
// -----------------------------------------------------------------------------

(function () {
  try {
    var t = localStorage.getItem("theme");
    if (t) document.documentElement.setAttribute("data-theme", t);
    var a = localStorage.getItem("accent");
    if (a) document.documentElement.setAttribute("data-accent", a);
  } catch (e) {}
})();
