// -----------------------------------------------------------------------------
// Skript: src/web/static/theme.js
// Autor: Torben Belz
// Version: 1.1.0
// Lizenz: AGPL-3.0-or-later (siehe LICENSE)
// Zweck:
// - Setzt die gespeicherten Design-Einstellungen (Modus, Akzentfarbe, Ansicht,
//   Spalten) VOR dem ersten Paint, damit nichts aufflackert. Blockierend im <head>.
// -----------------------------------------------------------------------------

(function () {
  try {
    var keys = ["theme", "accent", "view", "cols", "sort", "lines"];
    for (var i = 0; i < keys.length; i++) {
      var v = localStorage.getItem(keys[i]);
      if (v) document.documentElement.setAttribute("data-" + keys[i], v);
    }
  } catch (e) {}
})();
