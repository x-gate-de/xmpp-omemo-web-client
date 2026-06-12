# SPEC.md — Soll-Verhalten Chat

Dieses Dokument beschreibt das verbindliche Soll-Verhalten des Systems.
Abweichungen zwischen Code und SPEC gelten als Bug.

## Uebersicht

Chat ist ein dauerhaft laufender XMPP-Client, der als zusaetzliches OMEMO-Geraet
des eigenen Benutzeraccounts am Firmenchat (`xmpp.example.com`) teilnimmt. Er empfaengt
alle 1:1-Nachrichten, entschluesselt sie sofort (OMEMO, XEP-0384), speichert den Klartext
dauerhaft und stellt ihn ueber eine Web-UI ortsunabhaengig zum Nachlesen bereit. Damit
loest er das Problem, dass OMEMO-Nachrichten nur an gerade aktive Geraete zugestellt und
auf wechselnden Clients (Buero, Home Office, Mobil) verpasst werden.

Das System besteht aus zwei Prozessen, die sich nur ueber die Datenbank koppeln:
1. **Archiv-Daemon** — XMPP/OMEMO, immer online, schreibt Klartext.
2. **Web-UI** — liest die Datenbank, zeigt Verlaeufe.

## Funktionale Anforderungen

### F1 — XMPP-Verbindung und Geraeteregistrierung
- Eingabe: JID (`<user>@xmpp.example.com`), Passwort, Ressourcenname (Default `archiver`)
  aus `config.yaml`.
- Verarbeitung: Verbindung mit TLS-Verifikation; Anmeldung als eigene Ressource;
  Veroeffentlichung des OMEMO-Bundles/der Device-ID in der eigenen PEP-Geraeteliste
  (XEP-0163/0384); Aktivierung von Message Carbons (XEP-0280).
- Ausgabe: Daemon ist online und als zusaetzliches OMEMO-Geraet des Accounts gelistet.
- Fehlerverhalten: Bei Auth-/Verbindungsfehler klare Fehlermeldung (ohne Passwort),
  automatischer Reconnect mit Backoff.

### F2 — Stabile OMEMO-Identitaet
- Der Daemon haelt seine Identity-Keys und Device-ID dauerhaft im OMEMO-State.
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
  werden als „unlesbar" mit Metadaten protokolliert, nicht verworfen; der Daemon laeuft weiter.

### F4 — Trust-Politik
- Default: Blind Trust Before Verification (BTBV) — neue Geraete von Kontakten werden
  automatisch vertraut, solange der Account-Fingerprint nicht manuell verifiziert wurde.
- Die Politik ist in `config.yaml` konfigurierbar.
- Begruendung: Ein automatischer Archivierer kann Fingerprints nicht manuell verifizieren.

### F5 — Archivierung (Persistenz)
- Speicherung pro Nachricht: Zeitstempel (Empfang + ggf. originaler Stanza-Timestamp),
  Gespraechspartner-JID, Richtung (eingehend/ausgehend), Klartext, Nachrichten-ID,
  Entschluesselungsstatus.
- Eigene gesendete Nachrichten (via Carbons sichtbar) werden ebenfalls archiviert, damit
  der Verlauf vollstaendig ist.
- Datenhaltung: relationale DB (SQLite als Default; PostgreSQL 17 auf dem Host optional).
- OMEMO-State und Klartext-Archiv sind getrennt zu halten.

### F6 — Web-UI (Phase 1: nur lesend)
- Eingabe: HTTP-Request (hinter nginx-Reverse-Proxy, extern via traefik `chat.example.com`).
- Verarbeitung: Auflistung der Gespraechspartner; Anzeige des chronologischen Verlaufs
  je Partner; Suche/Filter nach Zeitraum und Partner.
- Ausgabe: HTML-Ansicht der archivierten Nachrichten.
- Zugriffsschutz: Die UI darf nur dem Account-Inhaber zugaenglich sein (Authentifizierung
  zwingend, da Klartext privater Nachrichten). Konkretes Verfahren in der Implementierung
  festzulegen (mind. Passwortschutz; bevorzugt vor traefik/nginx terminiert).

### F7 — Nachrichten senden (umgesetzt)
- Aus der Web-UI koennen Nachrichten gesendet werden (Antwort oder neue Konversation).
- Da nur der Daemon XMPP-Verbindung und OMEMO-State haelt, schreibt die Web-UI einen
  Sendeauftrag in die Outbox-Tabelle; ein Daemon-Task holt die Empfaenger-Geraeteliste,
  verschluesselt (OMEMO), sendet und archiviert die Nachricht als 'out'.
- Fehlerverhalten: Schlaegt die Verschluesselung/Sendung fehl, wird der Outbox-Eintrag
  als 'error' markiert (Kurzfehler ohne Inhalt), der Daemon laeuft weiter.

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

## Nicht-funktionale Anforderungen

- **Idempotenz:** Mehrfachzustellung (Carbons/Direktnachricht) darf keine Duplikate erzeugen.
- **Verfuegbarkeit:** Daemon laeuft als systemd-Service mit automatischem Reconnect/Restart.
- **Logging:** Wesentliche Schritte werden geloggt — ohne Klartext-Inhalte, Passwoerter
  oder Schluesselmaterial. Audit-relevant: Verbindungsstatus, Geraete-Trust-Entscheidungen,
  Entschluesselungsfehler.
- **Sicherheit:** `config.yaml` und OMEMO-State mit Dateirechten `0600`. TLS-Verifikation aktiv.
- **Wiederanlauf:** Nach Crash/Neustart nahtlose Fortsetzung ohne Neuregistrierung des Geraets.

## Abgrenzung (bewusst NICHT im Umfang)

- **Kein OMEMO in Gruppenraeumen.** Firmen-Gruppenchats sind unverschluesselt; MUC laeuft
  daher im Klartext. OMEMO-MUC ist ausgeschlossen.
- **Kein serverseitiger Eingriff** auf `xmpp.example.com` (nur User-Zugang vorhanden) — kein
  MAM-Modul, keine Server-Konfiguration.
- **Kein rueckwirkendes Archiv.** Nachrichten vor Inbetriebnahme des Daemons sind
  technisch nicht entschluesselbar.
- **Keine Garantie auf Vollstaendigkeit** bei manuell verifizierten Gegenstellen, bis diese
  dem Archiv-Geraet vertrauen.
- **Keine Datei-/Medienanhaenge** (XEP-0454 OMEMO-Media).
- **Keine Praesenz-/Tipp-Anzeigen**, keine Lesebestaetigungen nach aussen.
