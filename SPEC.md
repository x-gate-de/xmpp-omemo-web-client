# SPEC.md — Soll-Verhalten Chat

Dieses Dokument beschreibt das verbindliche Soll-Verhalten des Systems.
Abweichungen zwischen Code und SPEC gelten als Bug.

## Uebersicht

Chat ist ein dauerhaft laufender XMPP-Client, der als zusaetzliches OMEMO-Geraet
eines Benutzeraccounts am Firmenchat (`xmpp.example.com`) teilnimmt. Er empfaengt alle
1:1-Nachrichten, entschluesselt sie sofort (OMEMO, XEP-0384), speichert den Klartext
dauerhaft und stellt ihn ueber eine Web-UI ortsunabhaengig zum Nachlesen und Senden
bereit. Damit loest er das Problem, dass OMEMO-Nachrichten nur an gerade aktive Geraete
zugestellt und auf wechselnden Clients (Buero, Home Office, Mobil) verpasst werden.

Das System ist **mehrbenutzerfaehig**: Jeder Nutzer meldet sich mit seinen eigenen
XMPP-Zugangsdaten an. Fuer jeden aktiven Account wird dauerhaft eine eigene
XMPP/OMEMO-Verbindung gehalten und ein eigenes Klartext-Archiv gefuehrt. Ein Nutzer
sieht ausschliesslich sein eigenes Archiv.

Logische Komponenten, gekoppelt nur ueber Datenbanken:
1. **Account-Registry/Manager** — verwaltet die Accounts (Zugangsdaten verschluesselt)
   und haelt fuer jeden aktivierten Account einen Archiv-Daemon online.
2. **Archiv-Daemon (je Account)** — XMPP/OMEMO, immer online, schreibt Klartext.
3. **Web-UI** — Login, Lesen, Senden, Suchen, Verwalten (Trust, Online-Status).

## Funktionale Anforderungen

### F1 — Mehrbenutzer-Login und XMPP-Verbindung
- Eingabe: Anmeldung in der Web-UI mit XMPP-JID, Passwort und (optional) Serverhost.
  Globale Vorgaben (Standard-Host, Ressourcenname, Schluessel) liegen in `config.yaml`.
- Verarbeitung: Die Zugangsdaten werden beim Login gegen den XMPP-Server geprueft.
  Bei Erfolg wird der Account in der Account-Registry (`accounts.db`) angelegt/aktiviert,
  das Passwort **verschluesselt** gespeichert (Fernet, Schluessel `security.fernet_key`
  aus `config.yaml`), und eine Cookie-Session gesetzt. Der Manager verbindet jeden
  aktivierten Account dauerhaft mit TLS-Verifikation als eigene Ressource (Default
  `archiver`), veroeffentlicht das OMEMO-Bundle/die Device-ID in der PEP-Geraeteliste
  (XEP-0163/0384) und aktiviert Message Carbons (XEP-0280).
- Ausgabe: Der Daemon des Accounts ist online und als zusaetzliches OMEMO-Geraet gelistet.
- Fehlerverhalten: Bei Auth-/Verbindungsfehler klare Fehlermeldung (ohne Passwort),
  der Account-Status wird auf `failed` gesetzt; automatischer Reconnect mit Backoff fuer
  zuvor erfolgreich verbundene Accounts.

### F2 — Stabile OMEMO-Identitaet (je Account)
- Jeder Daemon haelt seine Identity-Keys und Device-ID dauerhaft im OMEMO-State
  (eigener Store je Account).
- Bei Neustart wird derselbe State geladen — KEINE Neuregistrierung.
- Geht der State verloren, gilt der Daemon zwingend als neues Geraet; das ist zu
  protokollieren und erfordert erneuten Trust durch die Gegenstellen.

### F3 — Empfang und Entschluesselung
- Eingabe: eingehende `message`-Stanzas (direkt und als Carbon-Kopie), Typ `chat`.
- Verarbeitung: OMEMO-Entschluesselung sofort beim Empfang (Forward Secrecy erlaubt
  kein spaeteres Entschluesseln). Duplikate (Carbon + Direktzustellung) werden idempotent
  behandelt — eine Nachricht wird nur einmal entschluesselt/gespeichert.
- Ausgabe: Klartext-Nachricht persistiert (siehe F5).
- Fehlerverhalten: Nicht entschluesselbare Nachrichten (fremdes Geraet, fehlender Key)
  werden als „unlesbar" mit Metadaten gespeichert, nicht verworfen; der Daemon laeuft weiter.

### F4 — Trust-Politik
- Default: Blind Trust Before Verification (BTBV) — neue Geraete von Kontakten werden
  automatisch vertraut, solange der Account-Fingerprint nicht manuell verifiziert wurde.
- Manuelle Verifizierung/Sperrung einzelner Geraete ist ueber die Web-UI moeglich
  (siehe F14).
- Begruendung: Ein automatischer Archivierer kann Fingerprints nicht selbst verifizieren.

### F5 — Archivierung (Persistenz, je Account)
- Speicherung pro Nachricht: Zeitstempel (Empfang + ggf. originaler Stanza-Timestamp),
  Gespraechspartner-JID, Richtung (eingehend/ausgehend), Klartext, Nachrichten-ID,
  Absender-Nick (bei Raeumen), Entschluesselungs- und Sendestatus.
- Eigene gesendete Nachrichten (via Carbons oder eigener Versand) werden ebenfalls
  archiviert; die eigene Stanza-ID wird mitgefuehrt, um beim MAM-Nachladen Duplikate
  zu erkennen.
- Datenhaltung: ein eigenes SQLite-Archiv je Account (WAL-Modus).
- OMEMO-State und Klartext-Archiv sind getrennt zu halten.

### F6 — Web-UI: Zugriff und Lesen
- Eingabe: HTTP-Request (hinter nginx-Reverse-Proxy, extern via traefik `chat.example.com`).
- Zugriffsschutz: Die UI ist nur nach Login mit gueltigen XMPP-Zugangsdaten zugaenglich
  (Cookie-Session). Jeder Nutzer sieht ausschliesslich sein eigenes Archiv. Da Klartext
  privater Nachrichten verarbeitet wird, ist die Authentifizierung zwingend.
- Verarbeitung/Ausgabe: Auflistung der Gespraechspartner (mit Vorschau, letzter Aktivitaet,
  Ungelesen-Markierung); chronologischer Verlauf je Partner; Senden, Suche, Verwaltung
  (siehe folgende F).

### F7 — Nachrichten senden
- Aus der Web-UI koennen Nachrichten gesendet werden (Antwort oder neue Konversation).
- Da nur der Daemon XMPP-Verbindung und OMEMO-State haelt, schreibt die Web-UI einen
  Sendeauftrag in die Outbox-Tabelle; ein Daemon-Task holt die Empfaenger-Geraeteliste,
  verschluesselt (OMEMO), sendet und archiviert die Nachricht als 'out'.
- Fehlerverhalten: Schlaegt Verschluesselung/Sendung fehl, wird der Outbox-Eintrag als
  'error' markiert (Kurzfehler ohne Inhalt), der Daemon laeuft weiter.

### F8 — Live-Aktualisierung und Lesezustand
- Die Web-UI aktualisiert Konversationsliste und Verlauf per Polling (JSON-Endpunkte),
  ohne manuelles Neuladen.
- Ungelesen-Markierung je Konversation ueber einen Lesezustand (read_state); das Oeffnen
  bzw. Nachladen einer Konversation setzt sie auf gelesen.

### F9 — Sende-Status
- Ausgehende 1:1-Nachrichten zeigen den Status: "wird gesendet" (Outbox offen),
  "gesendet" (versendet), "Fehler" (Verschluesselung/Sendung fehlgeschlagen),
  "zugestellt" (Empfangsbestaetigung XEP-0184 vom Empfaenger erhalten).

### F10 — Kontaktliste (Roster)
- Der Daemon persistiert das Roster (contacts). Die Web-UI zeigt die Kontakte mit
  Namen und JID; ein Klick startet/oeffnet die 1:1-Konversation.

### F11 — Oeffentliche Gruppenraeume (MUC, unverschluesselt)
- Der Daemon entdeckt die MUC-Dienste/Raeume des Servers (muc_available).
- Die Web-UI listet verfuegbare und beigetretene Raeume; Beitreten markiert den Raum,
  der Daemon betritt ihn (ohne Verlaufswiederholung) und bleibt verbunden.
- Gruppennachrichten werden unverschluesselt empfangen/gesendet und mit Absender-Nick
  archiviert. OMEMO wird im MUC nicht verwendet (Firmen-Gruppenchats sind unverschluesselt).
- Hinweis: Der Daemon ist als Teilnehmer im Raum praesent (eigener Nick).

### F12 — Volltextsuche
- Suche ueber das gesamte (entschluesselte) Archiv des angemeldeten Nutzers.
- Ausgabe: Treffer mit Kontext-Snippet, Hervorhebung des Suchbegriffs und Sprung zur
  jeweiligen Konversation.

### F13 — Antworten auf eine Nachricht (Zitat)
- Zu einer einzelnen Nachricht kann gezielt geantwortet werden; der Composer zeigt eine
  Zitat-Vorschau. Beim Senden wird das Zitat als vorangestellte „> "-Zeilen uebertragen
  (von jedem Client verstanden, OMEMO-kompatibel) und in der UI als eigener Block
  dargestellt. Mehrzeilige Nachrichten bleiben erhalten.

### F14 — OMEMO-Verifizierung (Fingerprints)
- Je 1:1-Kontakt zeigt eine Sicherheitsseite die OMEMO-Geraete mit Fingerprint und
  Trust-Status (eigene Geraete und die des Kontakts), daemon-seitig geholt.
- Geraete des Kontakts koennen als verifiziert markiert oder gesperrt werden; die
  Aenderung erfolgt ueber den Daemon (set_trust) und wirkt auf die OMEMO-Sitzungen.

### F15 — Paginierung und MAM-Nachladen (nur auf Klick)
- Die Chat-Ansicht laedt nur die letzten 50 Nachrichten (Keyset nach Zeit/ID) und oeffnet
  damit auch bei zehntausenden Nachrichten sofort.
- „Aeltere anzeigen" haengt zunaechst lokal vorhandene aeltere Nachrichten seitenweise an
  (Scrollposition bleibt erhalten).
- Sind lokal keine aelteren mehr vorhanden, kann der Server-Verlauf (MAM, XEP-0313) auf
  Klick nachgeladen werden: Der Daemon fragt ein 30-Tage-Fenster vor dem bisher aeltesten
  Stand des Ziels an. Es gibt **kein** automatisches MAM-Nachladen.
- MAM-Ergebnisse werden vor der Entschluesselung dedupliziert, um den Double-Ratchet-State
  nicht durch bereits bekannte Nachrichten zu stoeren.

### F16 — Online-Schalter je Account
- In der App-Bar laesst sich der „Immer-online"-Zustand des eigenen Accounts umschalten;
  der Status wird live angezeigt. Die Hintergrund-Archivierung des Accounts laeuft
  unabhaengig von der Web-Session weiter, solange der Account aktiviert ist.

### F17 — Darstellung und Bedien-Ergonomie (clientseitig)
- Umschaltbare Ansicht (Liste/Raster) inkl. Spaltenzahl und Zeilen-Vorschau im Raster.
- Design-Umschalter: Modus (Auto/Hell/Dunkel), Akzentfarbe, Dichte, Sortierung der
  Chats (Aktivitaet/Ungelesen/Name). Einstellungen werden pro Browser in localStorage
  gehalten und vor dem ersten Rendern angewandt.
- Relative Zeitangabe ("gerade eben", "vor X Min/Std", "gestern", "vor X Tagen") vor dem
  absoluten Zeitstempel der letzten Nachricht; clientseitig laufend aktualisiert.
- **Minimieren** einer Kachel: legt sie in eine kompakte Ablage; eine neue Nachricht klappt
  sie automatisch wieder auf. Auswahl pro Browser gespeichert.
- **Schliessen** einer Kachel: blendet die Konversation dauerhaft aus — auch bei neuen
  Nachrichten. Die archivierten Daten bleiben erhalten; Wiederherstellen ueber den Bereich
  „Geschlossene Chats" oder durch direktes Oeffnen des Chats. Minimieren und Schliessen
  schliessen sich gegenseitig aus.
- Nicht entschluesselbare Nachrichten werden inline gekennzeichnet; es entsteht **kein**
  dauerhaftes, nicht aufloesbares Alarm-Zaehlerbadge in der Chatliste.

### F18 — Installierbar (App-Icon / Vollbild)
- Die Web-UI liefert ein Web-App-Manifest und Icons, sodass sie auf dem Geraet
  installierbar ist und im Vollbild (standalone) startet.
- Bewusst **ohne** Service Worker und **ohne** Push-Benachrichtigungen.

### F19 — Anhaenge anzeigen und senden (OMEMO-Media, XEP-0454/0363)
- **Empfang/Anzeige:** 1:1-Anhaenge kommen als `aesgcm://`-URL an: die Datei liegt
  AES-256-GCM-verschluesselt auf dem HTTP-Upload-Server, Schluessel und IV stehen im
  URL-Fragment. Ein entschluesselnder Media-Proxy (`/media/{msg_id}`, nur fuer den
  angemeldeten Account) holt die Datei und liefert den Klartext aus. Bilder werden
  inline angezeigt, andere Dateitypen als Anhang verlinkt; die Liste zeigt `[Bild]`/
  `[Anhang]` statt der Roh-URL.
- **Senden (nur 1:1):** Die Web-UI legt die ausgewaehlte Datei im Account-Spool ab und
  schreibt einen Media-Auftrag in die Outbox. Der Daemon verschluesselt sie AES-256-GCM,
  laedt sie per HTTP File Upload (XEP-0363) hoch und sendet die `aesgcm://`-URL
  ausschliesslich im OMEMO-verschluesselten Body (kein Klartext-OOB, damit das
  Schluesselmaterial nicht offenliegt). Danach wird die Spool-Datei geloescht und die
  Nachricht als 'out' archiviert.
- Sicherheit: Laden/Anzeigen nur von der eigenen XMPP-Domain (SSRF-Schutz), Groessen-
  limit (30 MB); Schluesselmaterial bleibt serverseitig; Auslieferung mit
  `Cache-Control: private` und `nosniff`.
- In unverschluesselten Gruppenraeumen sind Anhaenge nicht vorgesehen.

### F20 — Account und Daten loeschen
- Im Settings-Menue kann der angemeldete Nutzer seinen Account und alle auf dem
  Server gespeicherten Daten loeschen. Vor der Ausfuehrung erscheint eine
  Bestaetigungsseite ("Willst du das wirklich?").
- Bei Bestaetigung wird der Account in der Registry zur Loeschung vorgemerkt und
  sofort deaktiviert; der Nutzer wird abgemeldet. Der Daemon-Manager trennt die
  Verbindung und entfernt anschliessend das Account-Verzeichnis (Klartext-Archiv,
  OMEMO-State, Spool) sowie den Registry-Eintrag (verschluesselte Zugangsdaten) --
  erst nachdem kein offener DB-Zugriff mehr besteht.
- Unwiderruflich. Bereits an Gegenstellen zugestellte Nachrichten sind nicht betroffen.

### F21 — Push-Benachrichtigungen (Web Push, selektiv)
- Push ist **pro Konversation/Raum** aktivierbar (Glocke im Chat-Kopf). Nur aktivierte
  Chats loesen eine Benachrichtigung aus; laute Raeume bleiben standardmaessig stumm.
- **Inhaltslos:** Der Push-Payload enthaelt keinen Nachrichtentext, nur einen Hinweis
  ("Neue Nachricht von/in <Name>") und einen Deep-Link auf den Chat. So verlaesst kein
  privater Inhalt den Server Richtung Push-Dienst (Apple/Google).
- Umsetzung: Service Worker im Wurzel-Scope (`/sw.js`); VAPID-Schluesselpaar in
  `config.yaml` (privat = geheim, nur Server; oeffentlich = Application Server Key).
  Geraete-Abos und die Auswahl je Account liegen im Account-Archiv
  (`push_subscriptions`, `push_prefs`). Der Daemon versendet bei eingehender
  Live-Nachricht (1:1 + Raum) via VAPID; abgelaufene Abos (HTTP 404/410) werden entfernt.
- Voraussetzungen: sicherer Kontext (HTTPS); auf iPhone ab iOS 16.4 nur als zum
  Home-Bildschirm hinzugefuegte App. Ohne konfigurierte VAPID-Schluessel ist Push
  vollstaendig deaktiviert (keine Glocke).

### F22 — Read-API (nur lesend, token-authentifiziert)
- Abruf des **eigenen** Archivs ueber HTTP fuer Skripte/Integrationen. Authentifizierung
  per **Bearer-Token je Account** (`Authorization: Bearer <token>`); der Account ergibt
  sich aus dem Token. Token werden in den **Settings** erzeugt und widerrufen und nur als
  **SHA-256-Hash** gespeichert — der Klartext wird einmalig bei der Erzeugung angezeigt.
- Endpunkte:
  - `GET /api/v1/chats` — Liste der Chats (JID, Name, `is_room`, Anzahl, letzte Aktivitaet).
  - `GET /api/v1/messages` — Nachrichten ueber ein Zeitfenster. Parameter: `partner`
    (eine oder mehrere JIDs, kommagetrennt; leer = alle), `hours` (Default 24) bzw.
    alternativ `from`/`to` als Unix-Sekunden, `limit` (bis 20000, Default 5000).
    Bei mehr Treffern als `limit` ist `truncated` = true.
  - `GET /api/feed` — inkrementeller Polling-Feed. Parameter: `since` (Unix-Zeit),
    `limit` (Default 200, max 1000), `include_outgoing` (Default false),
    `include_muc` (Default true). Aufsteigend nach Zeit sortiert; die Antwort liefert
    `next_since` als Cursor fuers naechste Polling. Items tragen eine **stabile
    `external_id`** (= Nachrichten-ID) fuer externe Dedup, dazu `title`, `body`,
    `sender`, `ts_source`, `url` (Deep-Link).
- **Keine Schluessel/Anhaenge nach aussen:** Anhaenge werden nicht ausgeliefert, nur als
  Hinweis im `body` ("[Anhang: ...]"); nicht entschluesselte Nachrichten als
  "[verschluesselt]". Kein OMEMO-Material, keine Read-State-/Historie-Pflicht.
- **Mandantentrennung und Erreichbarkeit:** Ein Token greift ausschliesslich auf das
  Archiv des eigenen Accounts zu. Die API ist wie die Web-UI erreichbar; eine ggf.
  konfigurierte Netz-/Geo-Begrenzung bleibt aktiv (kein Sonderweg fuer die API).

## Nicht-funktionale Anforderungen

- **Mandantentrennung:** Je Account ein eigenes Archiv; ein Nutzer hat ausschliesslich
  Zugriff auf seine eigenen Daten.
- **Vertraulichkeit der Zugangsdaten:** XMPP-Passwoerter werden ruhend verschluesselt
  gespeichert (Fernet); der Schluessel liegt nur in `config.yaml` (Rechte 0600).
- **Idempotenz:** Mehrfachzustellung (Carbons/Direktnachricht) und MAM-Nachladen duerfen
  keine Duplikate erzeugen.
- **Verfuegbarkeit:** Daemon/Manager und Web laufen als systemd-Services mit automatischem
  Reconnect/Restart. Der Manager fuehrt einen Verbindungs-Watchdog (prueft je Poll die
  Verbindung, baut tote Verbindungen nach `xmpp.reconnect_after_seconds` neu auf) und ein
  aktives Keepalive (XEP-0199) -> kein stundenlanges stilles Offline. Solange keine Sitzung
  steht, wird **nicht** gesendet: ausgehende Nachrichten bleiben in der Outbox und gehen
  nach dem Reconnect raus (kein stiller Verlust). Die Online-Anzeige spiegelt den echten
  Verbindungszustand.
- **Logging:** Wesentliche Schritte werden geloggt — ohne Klartext-Inhalte, Passwoerter
  oder Schluesselmaterial. Audit-relevant: Verbindungsstatus, Geraete-Trust-Entscheidungen,
  Entschluesselungsfehler.
- **Sicherheit:** `config.yaml` und OMEMO-State mit Dateirechten `0600`. TLS-Verifikation aktiv.
- **Login-Haertung (oeffentlicher Betrieb):** Da der Login unbekannte JIDs ueber eine
  echte XMPP-Verbindung des Chat-Servers validiert und alle Logins sich eine Quell-IP
  teilen, ist der Login gedrosselt: Bremse je Client-IP, globale Drossel der
  XMPP-Validierungen und optionale JID-Domain-Whitelist (`xmpp.allowed_domains`) -
  fremde Domains werden ohne XMPP-Kontakt abgewiesen. Bekannte Accounts mit falschem
  Passwort werden ohne XMPP-Kontakt abgelehnt. Session-Cookie mit Secure-Flag.
- **Wiederanlauf:** Nach Crash/Neustart nahtlose Fortsetzung ohne Neuregistrierung des Geraets.

## Abgrenzung (bewusst NICHT im Umfang)

- **Kein OMEMO in Gruppenraeumen.** Firmen-Gruppenchats sind unverschluesselt; MUC laeuft
  daher im Klartext. OMEMO-MUC ist ausgeschlossen.
- **Kein serverseitiger Eingriff** auf `xmpp.example.com` (nur User-Zugang vorhanden): keine
  Server-Konfiguration, kein eigenes MAM-Modul. MAM wird ausschliesslich als Client-Abfrage
  (XEP-0313) und nur auf Klick genutzt (siehe F15).
- **Kein automatisches MAM-Nachladen** (Schutz grosser Raeume vor Massenabfragen).
- **Kein rueckwirkendes Archiv** vor Inbetriebnahme des Daemon-Geraets: Forward Secrecy
  macht aeltere OMEMO-Nachrichten technisch nicht entschluesselbar (MAM liefert sie ggf.,
  aber nicht entschluesselbar).
- **Keine Garantie auf Vollstaendigkeit** bei manuell verifizierten Gegenstellen, bis diese
  dem Archiv-Geraet vertrauen.
- **Anhaenge nur in 1:1 (OMEMO-Media, XEP-0454/0363).** In unverschluesselten
  Gruppenraeumen werden keine Anhaenge gesendet/angezeigt (siehe F19).
- **Keine Push-Benachrichtigungen / kein Service Worker.**
- **Keine Praesenz-/Tipp-Anzeigen**, keine Lesebestaetigungen nach aussen.
