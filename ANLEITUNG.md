# Chat — Anleitung für Anwender

Diese Anleitung erklärt Schritt für Schritt, wie du die Chat‑Web‑App benutzt.

**Was ist das?** Chat ist ein dauerhaft mitlaufender Archivierer für deinen
verschlüsselten XMPP/OMEMO‑Chat. Er hängt sich als zusätzliches Gerät an deinen
eigenen Account, empfängt alle 1:1‑Nachrichten, entschlüsselt sie sofort und legt
sie lesbar ab. So verpasst du keine Nachricht mehr, nur weil sie an ein gerade
inaktives Gerät (Büro, Home‑Office, Handy) ging — und kannst deinen Verlauf von
überall im Browser nachlesen und auch senden.

---

## 1. Anmelden

1. Öffne die Web‑Adresse, die dir bereitgestellt wurde (z. B. als Lesezeichen).
2. Gib deine **XMPP‑JID** (z. B. `vorname@firma.de`), dein **Passwort** und – falls
   gefragt – den **Server** ein.
3. Nach erfolgreicher Anmeldung bleibt dein Account **dauerhaft online** und
   archiviert im Hintergrund weiter — auch wenn du das Browser‑Fenster schließt.

> Dein Passwort wird nur verschlüsselt auf dem Server gespeichert, um die
> Verbindung zu halten. Die Anmeldung gilt pro Browser/Gerät.

---

## 2. Auf dem Smartphone installieren (empfohlen)

Du kannst die App wie eine echte App auf den Startbildschirm legen:

- **iPhone (Safari):** Teilen‑Symbol → **„Zum Home‑Bildschirm"**. Danach die so
  installierte App öffnen.
- **Android (Chrome):** Menü → **„App installieren"** bzw. „Zum Startbildschirm".

Das gibt dir ein App‑Icon und Vollbild — **und ist auf dem iPhone Voraussetzung für
Push‑Benachrichtigungen** (siehe Abschnitt 12).

---

## 3. Die Chat‑Übersicht

Auf der Startseite siehst du deine Gespräche als Kacheln:

- **Name, Vorschau und Uhrzeit** der letzten Nachricht – mit einer relativen
  Angabe davor („vor 5 Min", „gestern" …).
- **Grüne Zahl** = ungelesene Nachrichten.
- Tippe eine Kachel an, um den Verlauf zu öffnen.
- Oben kannst du über **„Neuer Chat: jid@…"** gezielt jemanden anschreiben.

---

## 4. Nachrichten lesen

- Im geöffneten Chat siehst du den Verlauf, neue Nachrichten erscheinen
  **automatisch** (kein Neuladen nötig).
- Sehr lange Verläufe laden nur die letzten Nachrichten; mit **„Ältere anzeigen"**
  blätterst du zurück. Ist lokal nichts mehr da, kannst du auf Klick **älteres vom
  Server nachladen**.
- `[nicht entschluesselbar]` bedeutet: Diese Nachricht wurde gesendet, bevor dein
  Archiv‑Gerät existierte/vertraut war – sie lässt sich technisch nicht mehr öffnen.

---

## 5. Nachrichten senden

- Schreibe unten ins Feld und tippe auf **Senden** (Pfeil).
- Der Status einer gesendeten Nachricht: **wird gesendet → gesendet → zugestellt**
  (Häkchen). Schlägt etwas fehl, erscheint eine rote **Fehler**‑Blase, die du mit
  dem **×** verwerfen kannst.

> Verschlüsseltes Senden geht nur an Empfänger mit OMEMO‑fähigem Gerät. Hat die
> Gegenseite kein solches Gerät, meldet die App „Empfänger hat kein vertrautes
> OMEMO‑Gerät".

---

## 6. Auf eine Nachricht antworten (Zitat)

- Fahre über eine Nachricht und tippe auf das **Antworten‑Symbol**.
- Die zitierte Nachricht wird als Block über deinem Text angezeigt und beim Senden
  vorangestellt – so weiß die Gegenseite, worauf du dich beziehst.

---

## 7. Anhänge (Bilder & Dateien)

- **Empfangen:** Bilder werden direkt im Verlauf angezeigt, andere Dateien als
  Anhang verlinkt.
- **Senden:** Tippe im Eingabebereich auf die **Büroklammer**, wähle eine Datei –
  sie wird sofort verschlüsselt hochgeladen und gesendet.
- **Drag & Drop (am Computer):** Ziehe eine oder mehrere Dateien einfach ins
  Chat‑Fenster und lasse sie los – sie werden direkt gesendet.
- Anhänge funktionieren in 1:1‑Chats (verschlüsselt), nicht in offenen Räumen.

---

## 8. Suche

- Über das **Lupen‑Symbol** durchsuchst du dein gesamtes Archiv.
- Treffer werden mit Umgebung und Hervorhebung angezeigt; ein Klick springt in den
  jeweiligen Chat.

---

## 9. Kacheln aufräumen: Minimieren & Schließen

Oben rechts auf jeder Kachel (beim Drüberfahren, am Handy dauerhaft):

- **Minimieren ( – ):** legt die Kachel in eine kompakte „Minimiert"‑Leiste am
  Listenende. Kommt eine **neue Nachricht**, klappt sie **automatisch wieder auf**.
- **Schließen ( × ):** blendet den Chat **dauerhaft** aus – auch bei neuen
  Nachrichten. **Nichts wird gelöscht.** Wiederherstellen über den Bereich
  **„Geschlossene Chats"** am Listenende oder durch direktes Öffnen des Chats.

---

## 10. Gruppenräume

- Unter **„Räume"** siehst du öffentliche Gruppenräume; du kannst beitreten, lesen
  und schreiben.
- **Achtung:** Gruppenräume sind **unverschlüsselt** (kein OMEMO). Inhalte sind dort
  serverseitig im Klartext.

---

## 11. Sicherheit: Verschlüsselung & Verifizierung

- 1:1‑Chats sind **Ende‑zu‑Ende verschlüsselt** (OMEMO).
- Im Chat‑Kopf öffnet das **Schild‑Symbol** die Sicherheitsseite: dort siehst du die
  OMEMO‑Geräte und Fingerprints deines Gegenübers und kannst Geräte **verifizieren**
  oder **sperren**.

---

## 12. Push‑Benachrichtigungen (pro Chat)

Du entscheidest **selbst für jeden Chat**, ob du benachrichtigt werden willst – so
bleiben laute Chats/Räume stumm.

1. Öffne den gewünschten Chat.
2. Tippe im Chat‑Kopf auf die **🔔 Glocke**.
3. Erlaube **Benachrichtigungen**, wenn der Browser fragt. Die Glocke wird farbig.

Ab dann bekommst du für **diesen** Chat eine Notiz, sobald eine neue Nachricht
eintrifft. Tippen öffnet den Chat.

**Aus Datenschutzgründen enthält die Notiz keinen Nachrichtentext**, nur einen
Hinweis wie „Neue Nachricht von …".

> **iPhone:** Push funktioniert nur, wenn die App **zum Home‑Bildschirm hinzugefügt**
> wurde (siehe Abschnitt 2) und du die Glocke **in der installierten App** aktivierst.
> Push setzt außerdem eine HTTPS‑Adresse voraus.

---

## 13. Darstellung anpassen (Settings)

Über das **Zahnrad‑Symbol** (Settings) stellst du ein:

- **Modus:** Auto / Hell / Dunkel
- **Farbe:** Akzentfarbe
- **Dichte:** Komfortabel / Kompakt
- **Ansicht:** Liste / Raster (mit Spaltenzahl)
- **Sortierung** der Chats: Aktivität / Ungelesen / Name

Die Einstellungen gelten pro Browser/Gerät.

---

## 14. Online‑Status

In der Kopfzeile siehst du deinen Verbindungsstatus (**Online** …). Über den
Schalter kannst du den Account vorübergehend offline nehmen; die
Hintergrund‑Archivierung läuft unabhängig vom Browser‑Fenster weiter, solange der
Account aktiviert ist.

---

## 15. Account & Daten löschen

Im **Settings‑Menü** ganz unten: **„Account und gespeicherte Daten auf diesem Server
löschen"**. Nach einer Sicherheitsabfrage werden dein Account, dein Archiv und das
Schlüsselmaterial **unwiderruflich** entfernt und du wirst abgemeldet. Bereits an
deine Gesprächspartner zugestellte Nachrichten bleiben davon unberührt.

---

## 16. Gut zu wissen (Grenzen)

- **Kein rückwirkendes Archiv:** Erst ab Inbetriebnahme deines Archiv‑Geräts werden
  Nachrichten mitgeschnitten. Älteres ist durch die Verschlüsselung (Forward Secrecy)
  nicht nachträglich lesbar.
- **Vertrauens‑Lücken:** Gegenstellen, die manuell verifizieren, senden erst nach
  Bestätigung deines Archiv‑Geräts auch an dieses – vorher kommt von ihnen nichts an.
- **Gruppenräume** sind unverschlüsselt (siehe Abschnitt 10).

---

## 17. Hilfe

Bei Problemen oder Fragen wende dich an die Administration/Bereitstellung in deiner
Organisation.
