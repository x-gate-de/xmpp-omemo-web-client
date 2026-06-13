# -----------------------------------------------------------------------------
# Skript: src/archive.py
# Autor: Torben Belz
# Version: 1.2.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Schreibseite des Daemons: Archiv, Outbox, Kontakte (Roster) und MUC-Raeume.
# Betriebs- und Wartungshinweise:
# - Enthaelt entschluesselte private Nachrichten (Schutzbedarf HOCH). Rechte 0600.
# - Schema in src/schema.py (gemeinsam mit der Web-UI).
# -----------------------------------------------------------------------------

import logging
import os
import sqlite3
import time

from src.schema import ensure_schema

logger = logging.getLogger(__name__)


# Schreibzugriff des Daemons auf Archiv, Outbox, Kontakte und Raeume.
class MessageArchive:
    def __init__(self, path):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(path)
        ensure_schema(self._conn)
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.warning("Konnte Dateirechte fuer Archiv nicht setzen: %s", path)

    # Speichert eine Nachricht idempotent. Rueckgabe: True wenn neu gespeichert.
    # ts: expliziter Zeitstempel (z. B. MAM-Originalzeit); None = jetzt.
    def store(self, partner_jid, direction, body, stanza_id, decrypted=True,
              namespace=None, sender=None, status=None, msg_id=None, ts=None):
        dedup_key = f"{direction}:{partner_jid}:{sender or ''}:{stanza_id}"
        try:
            self._conn.execute(
                "INSERT INTO messages "
                "(dedup_key, partner_jid, direction, body, decrypted, ts_received, namespace, sender, status, msg_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dedup_key, partner_jid, direction, body, 1 if decrypted else 0,
                 ts if ts is not None else time.time(), namespace, sender, status, msg_id),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # Prueft, ob eine Nachricht bereits archiviert ist (Dedup vor OMEMO-Entschluesselung).
    def has(self, partner_jid, direction, sender, stanza_id):
        key = f"{direction}:{partner_jid}:{sender or ''}:{stanza_id}"
        return self._conn.execute("SELECT 1 FROM messages WHERE dedup_key = ?", (key,)).fetchone() is not None

    # --- MAM (aeltere Nachrichten nachladen) --------------------------------

    def claim_pending_mam(self):
        rows = self._conn.execute(
            "SELECT id, target_jid, kind FROM mam_requests WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def mark_mam_done(self, req_id, ok=True):
        self._conn.execute(
            "UPDATE mam_requests SET status = ? WHERE id = ?", ("done" if ok else "error", req_id)
        )
        self._conn.commit()

    def mam_oldest(self, target):
        row = self._conn.execute("SELECT oldest_ts FROM mam_state WHERE target_jid = ?", (target,)).fetchone()
        return row[0] if row else None

    def set_mam_oldest(self, target, ts):
        self._conn.execute(
            "INSERT INTO mam_state (target_jid, oldest_ts) VALUES (?, ?) "
            "ON CONFLICT(target_jid) DO UPDATE SET oldest_ts = excluded.oldest_ts",
            (target, ts),
        )
        self._conn.commit()

    def oldest_message_ts(self, target):
        row = self._conn.execute(
            "SELECT MIN(ts_received) FROM messages WHERE partner_jid = ?", (target,)
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    # Markiert eine gesendete Nachricht als zugestellt (Empfangsbestaetigung XEP-0184).
    def mark_delivered(self, msg_id):
        self._conn.execute(
            "UPDATE messages SET status = 'delivered' WHERE msg_id = ? AND direction = 'out'",
            (msg_id,),
        )
        self._conn.commit()

    # --- Outbox -------------------------------------------------------------

    def claim_pending_outbox(self):
        rows = self._conn.execute(
            "SELECT id, recipient_jid, body, kind FROM outbox WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def mark_outbox_sent(self, outbox_id):
        self._conn.execute(
            "UPDATE outbox SET status = 'sent', sent_ts = ? WHERE id = ?",
            (time.time(), outbox_id),
        )
        self._conn.commit()

    def mark_outbox_error(self, outbox_id, error):
        self._conn.execute(
            "UPDATE outbox SET status = 'error', error = ? WHERE id = ?",
            (str(error)[:200], outbox_id),
        )
        self._conn.commit()

    # --- Kontakte (Roster) --------------------------------------------------

    def upsert_contact(self, jid, name, subscription):
        self._conn.execute(
            "INSERT INTO contacts (jid, name, subscription) VALUES (?, ?, ?) "
            "ON CONFLICT(jid) DO UPDATE SET name = excluded.name, subscription = excluded.subscription",
            (jid, name, subscription),
        )
        self._conn.commit()

    # --- MUC ----------------------------------------------------------------

    def set_available_rooms(self, rooms):
        # rooms: Liste von (room_jid, name). Tabelle komplett ersetzen.
        self._conn.execute("DELETE FROM muc_available")
        now = time.time()
        self._conn.executemany(
            "INSERT OR REPLACE INTO muc_available (room_jid, name, updated_ts) VALUES (?, ?, ?)",
            [(r[0], r[1], now) for r in rooms],
        )
        self._conn.commit()

    def joined_rooms(self):
        rows = self._conn.execute(
            "SELECT room_jid, nick FROM mucs WHERE joined = 1"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def is_room(self, jid):
        row = self._conn.execute(
            "SELECT 1 FROM mucs WHERE room_jid = ? UNION SELECT 1 FROM muc_available WHERE room_jid = ?",
            (jid, jid),
        ).fetchone()
        return row is not None
