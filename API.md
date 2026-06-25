# Read-API — Dokumentation

Stand: 2026-06-25 · App-Version 1.5.0 · `app.py` 2.9.0

Diese Read-API stellt das **Klartext-Archiv eines Accounts** nur lesend zur
Verfuegung. Sie ist fuer die Anbindung nachgelagerter Systeme gedacht.
Schreibende Operationen gibt es nicht.

---

## 1. Grundlagen

| Punkt | Wert |
|---|---|
| Basis-URL | `https://chat.example.com` |
| Protokoll | HTTPS, JSON (`Content-Type: application/json; charset=utf-8`) |
| Methoden | ausschliesslich `GET` |
| Authentifizierung | Bearer-Token je Account (siehe 2.) |
| Zeichencodierung | UTF-8 |

**Erreichbarkeit / Netzgrenze.** Die API laeuft unter demselben Hostnamen wie
die Web-UI und unterliegt **derselben Zugriffsbegrenzung**. Eine ggf.
konfigurierte Netz-/Geo-Begrenzung der Web-UI gilt unveraendert auch fuer die
API; es gibt **keinen Sonderweg**.

**Mandantentrennung.** Ein Token gehoert zu genau einem Account und liefert
ausschliesslich dessen Archiv. Der Account wird aus dem Token abgeleitet; es gibt
keinen Parameter, um einen fremden Account anzusprechen.

---

## 2. Authentifizierung

Jeder Request traegt den Token im Header:

    Authorization: Bearer <TOKEN>

Alternativ wird `X-API-Key: <TOKEN>` akzeptiert (gleiche Wirkung).

**Token-Lebenszyklus.** Token werden vom Account-Inhaber in der Web-UI verwaltet:
Zahnrad (Settings) → **„API-Token"** (`/settings/api`).

- Erzeugen: optionale Bezeichnung angeben → der Klartext-Token wird **einmalig**
  angezeigt. Danach ist er nicht mehr abrufbar (es wird nur ein SHA-256-Hash
  gespeichert).
- Widerrufen: jederzeit ueber dieselbe Seite. Ein widerrufener Token ist sofort
  ungueltig.
- Ein Account kann mehrere Token haben (z. B. je Integration einen).

**Fehlende/ungueltige Authentifizierung** → HTTP `401`:

    {"detail": "Ungueltiger oder fehlender API-Token"}

---

## 3. Konventionen

- **Zeitstempel** sind Unix-Sekunden als Gleitkommazahl (`ts`, `ts_source`,
  `since`, `next_since`, `from`, `to`). Zusaetzlich liefern Antworten ein
  ISO-8601-Feld (`*_iso`, lokale Serverzeit) zur Lesbarkeit.
- **JIDs** sind die XMPP-Adressen des Gespraechspartners bzw. Raums
  (`name@example.com` oder `room@conference.example.com`).
- **Raum vs. 1:1**: `is_room = true` kennzeichnet einen Gruppenraum (MUC,
  unverschluesselt); `false` einen 1:1-Chat (OMEMO).
- **Richtung** (`direction`): `in` = empfangen, `out` = selbst gesendet.

---

## 4. Endpunkte

### 4.1 `GET /api/v1/chats` — Liste der Chats

Liefert alle Gespraechspartner/Raeume des Accounts (ohne Zeitfilter).

Antwort:

    {
      "account": "user@example.com",
      "chats": [
        {
          "partner": "noc@conference.example.com",
          "name": "noc",
          "is_room": true,
          "count": 59971,
          "last_ts": 1782404628.6083646,
          "last_iso": "2026-06-25T18:23:48.608365"
        }
      ]
    }

| Feld | Typ | Bedeutung |
|---|---|---|
| `partner` | string | JID des Chats/Raums (Schluessel fuer `partner=` in 4.2) |
| `name` | string | Anzeigename (Kontakt- bzw. Raumname, sonst lokaler JID-Teil) |
| `is_room` | bool | Gruppenraum (true) oder 1:1 (false) |
| `count` | int | Anzahl gespeicherter Nachrichten in diesem Chat |
| `last_ts` | float | Zeitpunkt der letzten Nachricht (Unix-Sekunden) |
| `last_iso` | string | dito als ISO-8601 |

---

### 4.2 `GET /api/v1/messages` — Nachrichten ueber ein Zeitfenster

Zweck: gezielter Abruf eines, mehrerer oder aller Chats ueber einen Zeitraum.

Parameter (alle optional, Query-String):

| Parameter | Default | Bedeutung |
|---|---|---|
| `partner` | (leer = alle) | eine oder mehrere JIDs, **kommagetrennt** |
| `hours` | `24` | Fenstergroesse in Stunden ab jetzt rueckwaerts |
| `from` | — | Alternativ: Fensterbeginn als Unix-Sekunden (ueberschreibt `hours`) |
| `to` | jetzt | Alternativ: Fensterende als Unix-Sekunden |
| `limit` | `5000` | Obergrenze; max. `20000`. Bei mehr Treffern `truncated=true` |

Das Fenster ist beidseitig inklusive (`since <= ts <= until`). Sortierung
**aufsteigend** nach Zeit.

Anwendungsfaelle:

    # ein Chat (z. B. ein Raum), letzte 24 Stunden
    GET /api/v1/messages?partner=room@conference.example.com&hours=24

    # alle Chats, letzte 24 Stunden
    GET /api/v1/messages?hours=24

    # ausgewaehlte Chats, letzte 48 Stunden
    GET /api/v1/messages?partner=a@example.com,b@example.com&hours=48

    # fester Zeitraum per Unix-Zeit
    GET /api/v1/messages?from=1782300000&to=1782400000

Antwort:

    {
      "account": "user@example.com",
      "partners": ["room@conference.example.com"],
      "since": 1782318228.0,
      "since_iso": "2026-06-24T18:23:48",
      "until": 1782404628.0,
      "until_iso": "2026-06-25T18:23:48",
      "count": 2,
      "truncated": false,
      "messages": [
        {
          "partner": "room@conference.example.com",
          "name": "On-call",
          "direction": "in",
          "sender": "Max Mustermann",
          "ts": 1782400000.12,
          "ts_iso": "2026-06-25T17:06:40",
          "decrypted": true,
          "text": "Bin ab 18 Uhr erreichbar.",
          "media": null
        }
      ]
    }

| Feld (Nachricht) | Typ | Bedeutung |
|---|---|---|
| `partner` | string | JID des Chats/Raums |
| `name` | string | Anzeigename des Chats/Raums |
| `direction` | string | `in` (empfangen) / `out` (gesendet) |
| `sender` | string\|null | Anzeigename des Absenders (v. a. in Raeumen relevant) |
| `ts` / `ts_iso` | float / string | Empfangszeit |
| `decrypted` | bool | true = Klartext verfuegbar; false = nicht entschluesselbar |
| `text` | string\|null | Nachrichtentext. `null` bei Anhang oder `decrypted=false` |
| `media` | object\|null | bei Anhang: `{ "kind": "...", "name": "..." }`, sonst `null` |

`partners` in der Antwort ist die Liste der angefragten JIDs oder der String
`"all"`, wenn kein `partner` gesetzt war.

---

### 4.3 `GET /api/feed` — Inkrementeller Polling-Feed

Zweck: laufendes Abholen neuer Nachrichten (Push-/Benachrichtigungs-Pipeline).
Liefert nur ein Zeitfenster ab `since` vorwaerts und einen Cursor fuer den
naechsten Aufruf. **Keine Historie vor `since`.**

Parameter (Query-String):

| Parameter | Default | Bedeutung |
|---|---|---|
| `since` | `0` | Cursor: nur Nachrichten ab diesem Zeitpunkt (Unix-Sekunden) |
| `limit` | `200` | Obergrenze je Aufruf; max. `1000` |
| `include_outgoing` | `false` | `true` = auch selbst gesendete Nachrichten |
| `include_muc` | `true` | `false` = Gruppenraeume ausblenden (nur 1:1) |

Sortierung **aufsteigend** nach Zeit (`ts_source ASC`, bei Gleichstand `id ASC`).

Antwort:

    {
      "account": "user@example.com",
      "count": 1,
      "next_since": 1782400000.12,
      "items": [
        {
          "external_id": 12001,
          "title": "On-call",
          "body": "Bin ab 18 Uhr erreichbar.",
          "sender": "Max Mustermann",
          "ts_source": 1782400000.12,
          "ts_iso": "2026-06-25T17:06:40",
          "is_room": true,
          "url": "/c/room@conference.example.com"
        }
      ]
    }

| Feld (Item) | Typ | Bedeutung |
|---|---|---|
| `external_id` | int | **Stabile, eindeutige Nachrichten-ID** (= `messages.id`). Cursor-unabhaengig, ideal als Dedup-Schluessel |
| `title` | string | Chat-/Raumname (Anzeigetitel) |
| `body` | string | Nachrichtentext; bei Anhang `"[Anhang: <Name>]"`, bei nicht entschluesselbarer Nachricht `"[verschluesselt]"` |
| `sender` | string\|null | Absender-Anzeigename |
| `ts_source` | float | Quell-Zeitpunkt (Empfangszeit) |
| `ts_iso` | string | dito als ISO-8601 |
| `is_room` | bool | Gruppenraum (true) / 1:1 (false) |
| `url` | string | Deep-Link in die Web-UI (`/c/<JID>`) |

#### Polling-Ablauf

1. Erster Aufruf mit `since=<jetzt-minus-Puffer>` (oder `0` fuer „alles, was da
   ist", begrenzt durch `limit`).
2. Items verarbeiten. **`next_since` aus der Antwort merken.**
3. Naechster Aufruf mit `since=<next_since>`.
4. Wiederholen (empfohlenes Intervall: 30–60 s).

**Wichtig zur Dedup.** Das Fenster wird mit `ts_source >= since` gebildet (nicht
`>`), damit bei identischen Zeitstempeln keine Nachricht verloren geht. Dadurch
kann das Item am Cursor-Rand beim Folge-Poll **erneut** geliefert werden. Der
Konsument muss deshalb ueber `external_id` deduplizieren — diese ID ist stabil und
eindeutig. Liefert ein Aufruf keine Items, bleibt `next_since == since`.

Bewusst **nicht** enthalten: Anhaenge/Medien (nur Hinweis im `body`), Read-State,
OMEMO-Infos, Historie vor `since`.

---

## 5. Fehler

| HTTP | Bedeutung | Body |
|---|---|---|
| `401` | Token fehlt/ungueltig/widerrufen | `{"detail": "Ungueltiger oder fehlender API-Token"}` |
| `422` | Ungueltiger Parameter (z. B. `hours=abc`) | FastAPI-Validierungsfehler |

Bei `truncated=true` (nur `/api/v1/messages`) wurden mehr Treffer gefunden als
`limit`; das Fenster verkleinern oder `limit` erhoehen (max. 20000).

---

## 6. Hinweise zum Datenbestand

- **Nicht-entschluesselbare Nachrichten** erscheinen mit `decrypted=false` bzw.
  `body="[verschluesselt]"`. Ursache ist i. d. R. eine OMEMO-Trust-Luecke
  (Nachricht wurde nicht an das Archiv-Geraet verschluesselt). Solche Eintraege
  koennen vom Konsumenten ignoriert oder gesondert behandelt werden.
- **Anhaenge** werden bewusst nicht ausgeliefert (kein Schluesselmaterial). Es
  bleibt ein Hinweis im Text (`text=null` + `media`-Objekt bzw. `body="[Anhang: …]"`).
- **Raeume** sind unverschluesselt; ein lauter Raum kann sehr viele Nachrichten
  liefern — fuer Benachrichtigungen ggf. `include_muc=false` oder gezielt per
  `partner=` filtern.

---

## 7. Schnelltest (curl)

    TOKEN=<in den Settings erzeugter Token>

    curl -H "Authorization: Bearer $TOKEN" \
      https://chat.example.com/api/v1/chats

    curl -H "Authorization: Bearer $TOKEN" \
      "https://chat.example.com/api/v1/messages?hours=24"

    curl -H "Authorization: Bearer $TOKEN" \
      "https://chat.example.com/api/feed?since=0&limit=50"
