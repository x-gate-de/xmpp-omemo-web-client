# -----------------------------------------------------------------------------
# Skript: src/daemon.py
# Autor: Torben Belz
# Version: 1.2.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Always-Online XMPP-Client: empfaengt/entschluesselt 1:1-OMEMO-Nachrichten,
#   nimmt an oeffentlichen (unverschluesselten) Gruppenraeumen teil, archiviert
#   alles und versendet aus der Outbox (1:1 OMEMO, Gruppe als Klartext).
# Ablauf:
# - Anmeldung; Roster persistieren; MUC-Dienste/Raeume entdecken; beigetretene
#   Raeume betreten; Carbons aktivieren; eingehende Nachrichten archivieren;
#   Empfangsbestaetigungen (XEP-0184) auswerten; Outbox abarbeiten.
# Betriebs- und Wartungshinweise:
# - Entschluesselung sofort beim Empfang (Forward Secrecy).
# - Trust-Politik fuer den unbeaufsichtigten Archivierer: TOAKAFA.
# - Gruppenchats sind serverseitig unverschluesselt; kein OMEMO im MUC.
# - Es werden keine Nachrichteninhalte geloggt.
# -----------------------------------------------------------------------------

import asyncio
import datetime
import logging
import sys
import time

from slixmpp import ClientXMPP, JID
from slixmpp.plugins import register_plugin
from slixmpp_omemo import TrustLevel, XEP_0384

from .archive import MessageArchive
from .omemo_storage import SqliteOmemoStorage

logger = logging.getLogger(__name__)


# Konkrete OMEMO-Plugin-Implementierung (Storage + Trust-Politik).
class XEP_0384Impl(XEP_0384):
    default_config = {
        "state_db_path": None,
        "fallback_message": "Diese Nachricht ist OMEMO-verschluesselt.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__storage = None

    def plugin_init(self):
        if not self.state_db_path:
            raise ValueError("state_db_path fuer das OMEMO-Plugin nicht gesetzt")
        self.__storage = SqliteOmemoStorage(self.state_db_path)
        super().plugin_init()

    @property
    def storage(self):
        return self.__storage

    @property
    def _btbv_enabled(self):
        return True

    async def _devices_blindly_trusted(self, blindly_trusted, identifier):
        logger.info("OMEMO: Geraete blind vertraut (%s): %d", identifier, len(blindly_trusted))

    async def _prompt_manual_trust(self, manually_trusted, identifier):
        # Unbeaufsichtigter Archivierer: TOAKAFA (alle Geraete vertrauen).
        session_manager = await self.get_session_manager()
        for device in manually_trusted:
            await session_manager.set_trust(
                device.bare_jid, device.identity_key, TrustLevel.TRUSTED.value
            )
            logger.warning("OMEMO: Geraet automatisch vertraut (TOAKAFA): %s", device.bare_jid)


register_plugin(XEP_0384Impl)


# Der Always-Online-Client.
class ArchiverBot(ClientXMPP):
    def __init__(self, config, archive):
        xmpp_cfg = config["xmpp"]
        jid = f"{xmpp_cfg['jid']}/{xmpp_cfg['resource']}"
        super().__init__(jid, xmpp_cfg["password"])

        self._config = config
        self._archive = archive
        self._own_bare = self.boundjid.bare
        # Nick fuer Gruppenraeume (Default: lokaler Teil der JID).
        self._muc_nick = xmpp_cfg.get("muc_nick") or self.boundjid.local
        self._joined_rooms = set()
        self._loops_started = False

        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0060")  # PubSub
        self.register_plugin("xep_0199")  # Ping
        self.register_plugin("xep_0280")  # Message Carbons
        self.register_plugin("xep_0334")  # Message Processing Hints
        self.register_plugin("xep_0045")  # Multi-User Chat
        self.register_plugin("xep_0184")  # Empfangsbestaetigungen
        self.register_plugin("xep_0313")  # Message Archive Management (MAM)
        self.register_plugin(
            "xep_0384",
            {"state_db_path": config["omemo"]["state_path"]},
            module=sys.modules[__name__],
        )

        self.add_event_handler("session_start", self._on_session_start)
        self.add_event_handler("message", self._on_message)
        self.add_event_handler("carbon_received", self._on_carbon_received)
        self.add_event_handler("carbon_sent", self._on_carbon_sent)
        self.add_event_handler("groupchat_message", self._on_groupchat)
        self.add_event_handler("receipt_received", self._on_receipt)
        self.add_event_handler("roster_update", lambda _e: self._persist_roster())

    async def _on_session_start(self, _event):
        self.send_presence()
        await self.get_roster()
        self._persist_roster()
        try:
            await self["xep_0280"].enable()
            logger.info("Message Carbons aktiviert")
        except Exception as e:
            logger.warning("Carbons konnten nicht aktiviert werden: %s", type(e).__name__)
        try:
            await self["xep_0384"].get_session_manager()
            logger.info("OMEMO-Geraet veroeffentlicht/aktiv")
        except Exception as e:
            logger.error("OMEMO-Initialisierung fehlgeschlagen: %s", type(e).__name__)
        logger.info("Daemon online als %s", self.boundjid.full)

        # Hintergrundaufgaben nur einmal starten (session_start feuert bei Reconnect).
        if not self._loops_started:
            self._loops_started = True
            asyncio.create_task(self._discover_rooms())
            asyncio.create_task(self._outbox_loop())

    # Roster in die contacts-Tabelle schreiben (Quelle der Userliste in der UI).
    def _persist_roster(self):
        try:
            roster = self.client_roster
            for jid in roster.keys():
                if jid == self._own_bare:
                    continue
                item = roster[jid]
                self._archive.upsert_contact(jid, item["name"] or "", item["subscription"] or "")
        except Exception as e:
            logger.warning("Roster-Persistenz fehlgeschlagen: %s", type(e).__name__)

    # Oeffentliche MUC-Raeume des Servers entdecken und speichern.
    async def _discover_rooms(self):
        try:
            domain = self.boundjid.domain
            services = await self["xep_0030"].get_items(jid=domain)
            available = []
            for svc in services["disco_items"]["items"]:
                svc_jid = svc[0]
                try:
                    info = await self["xep_0030"].get_info(jid=svc_jid)
                    identities = info["disco_info"]["identities"]
                    is_muc = any(cat == "conference" for cat, _typ, _lang, _name in identities)
                    if not is_muc:
                        continue
                    rooms = await self["xep_0030"].get_items(jid=svc_jid)
                    for r in rooms["disco_items"]["items"]:
                        available.append((r[0], r[2] or r[0]))
                except Exception:
                    continue
            self._archive.set_available_rooms(available)
            logger.info("MUC-Raeume entdeckt: %d", len(available))
        except Exception as e:
            logger.warning("MUC-Discovery fehlgeschlagen: %s", type(e).__name__)

    # Betritt alle als beigetreten markierten Raeume, die noch nicht aktiv sind.
    async def _join_pending_rooms(self):
        for room_jid, nick in self._archive.joined_rooms():
            if room_jid in self._joined_rooms:
                continue
            try:
                # maxhistory=0: keine Verlaufswiederholung -> ab jetzt archivieren.
                await self["xep_0045"].join_muc(JID(room_jid), nick or self._muc_nick, maxhistory="0")
                self._joined_rooms.add(room_jid)
                logger.info("Raum betreten: %s", room_jid)
            except Exception as e:
                logger.warning("Raum %s konnte nicht betreten werden: %s", room_jid, type(e).__name__)

    # --- Empfang ------------------------------------------------------------

    async def _archive_stanza(self, stanza, partner_jid, direction):
        if stanza["type"] not in ("chat", "normal"):
            return
        stanza_id = stanza["id"] or ""
        xep_0384 = self["xep_0384"]
        namespaces = xep_0384.is_encrypted(stanza)

        if not namespaces:
            body = stanza["body"]
            if not body:
                return
            if self._archive.store(partner_jid, direction, body, stanza_id, decrypted=True):
                logger.info("Archiviert (plain, %s) %s", direction, partner_jid)
            return

        namespace = next(iter(namespaces))
        try:
            message, _info = await xep_0384.decrypt_message(stanza)
            body = message["body"] or ""
            if self._archive.store(partner_jid, direction, body, stanza_id, decrypted=True, namespace=namespace):
                logger.info("Archiviert (omemo, %s) %s", direction, partner_jid)
        except Exception as e:
            logger.warning("Entschluesselung fehlgeschlagen (%s) %s: %s", direction, partner_jid, type(e).__name__)
            self._archive.store(partner_jid, direction, None, stanza_id, decrypted=False, namespace=namespace)

    async def _on_message(self, stanza):
        # Gruppenchat laeuft ueber groupchat_message; Carbons ueber eigene Handler.
        if stanza["type"] == "groupchat":
            return
        partner = stanza["from"].bare
        if partner == self._own_bare:
            return
        await self._archive_stanza(stanza, partner, "in")

    async def _on_carbon_received(self, stanza):
        inner = stanza["carbon_received"]
        partner = inner["from"].bare
        if partner == self._own_bare:
            return
        await self._archive_stanza(inner, partner, "in")

    async def _on_carbon_sent(self, stanza):
        inner = stanza["carbon_sent"]
        partner = inner["to"].bare
        await self._archive_stanza(inner, partner, "out")

    # Gruppennachricht (unverschluesselt) archivieren.
    async def _on_groupchat(self, stanza):
        room = stanza["from"].bare
        nick = stanza["from"].resource
        body = stanza["body"]
        if not body or not nick:
            return
        # Eigene (reflektierte) Nachrichten als 'out' markieren.
        direction = "out" if nick == self._muc_nick else "in"
        stanza_id = stanza["id"] or ""
        self._archive.store(room, direction, body, stanza_id, decrypted=True, sender=nick)

    # Empfangsbestaetigung (XEP-0184) -> Nachricht als zugestellt markieren.
    async def _on_receipt(self, stanza):
        try:
            receipt_id = stanza["receipt"]
            if receipt_id:
                self._archive.mark_delivered(receipt_id)
        except Exception:
            pass

    # --- Senden -------------------------------------------------------------

    async def _outbox_loop(self):
        while True:
            try:
                await self._join_pending_rooms()
                for outbox_id, recipient, body, kind in self._archive.claim_pending_outbox():
                    if kind == "groupchat":
                        await self._send_groupchat(outbox_id, recipient, body)
                    else:
                        await self._send_chat(outbox_id, recipient, body)
                # Anfragen, aeltere Nachrichten per MAM nachzuladen, abarbeiten.
                for req_id, target, kind in self._archive.claim_pending_mam():
                    await self._backfill(req_id, target, kind)
            except Exception as e:
                logger.error("Outbox-Verarbeitung fehlgeschlagen: %s", type(e).__name__)
            await asyncio.sleep(2)

    # Verschluesselt (OMEMO) und sendet eine 1:1-Nachricht, archiviert als 'out'.
    async def _send_chat(self, outbox_id, recipient, body):
        recipient_jid = JID(recipient)
        xep_0384 = self["xep_0384"]
        try:
            await xep_0384.refresh_device_lists({recipient_jid})
            plain = self.make_message(mto=recipient_jid, mbody=body, mtype="chat")
            encrypted, errors = await xep_0384.encrypt_message(plain, {recipient_jid})
            if errors:
                logger.warning("OMEMO-Verschluesselung an %s mit %d Fehlern", recipient, len(errors))
            if encrypted is None:
                self._archive.mark_outbox_error(outbox_id, "Verschluesselung fehlgeschlagen")
                return
            # Eigene Message-ID + Empfangsbestaetigung auf der gesendeten Stanza.
            msg_id = self.new_id()
            encrypted["id"] = msg_id
            encrypted["request_receipt"] = True
            encrypted.send()
            # stanza_id = echte Message-ID, damit ein spaeteres MAM-Ergebnis dedupliziert.
            self._archive.store(recipient, "out", body, msg_id,
                                decrypted=True, namespace="send", status="sent", msg_id=msg_id)
            self._archive.mark_outbox_sent(outbox_id)
            logger.info("Gesendet (1:1) an %s", recipient)
        except Exception as e:
            logger.warning("Senden (1:1) an %s fehlgeschlagen: %s", recipient, type(e).__name__, exc_info=True)
            self._archive.mark_outbox_error(outbox_id, type(e).__name__)

    # Sendet eine Gruppennachricht (unverschluesselt). Die Reflexion wird archiviert.
    async def _send_groupchat(self, outbox_id, room, body):
        try:
            if room not in self._joined_rooms:
                await self["xep_0045"].join_muc(JID(room), self._muc_nick, maxhistory="0")
                self._joined_rooms.add(room)
            self.send_message(mto=JID(room), mbody=body, mtype="groupchat")
            self._archive.mark_outbox_sent(outbox_id)
            logger.info("Gesendet (Gruppe) an %s", room)
        except Exception as e:
            logger.warning("Senden (Gruppe) an %s fehlgeschlagen: %s", room, type(e).__name__)
            self._archive.mark_outbox_error(outbox_id, type(e).__name__)

    # --- MAM: aeltere Nachrichten nachladen ---------------------------------

    # Laedt ein 30-Tage-Fenster vor dem bisher aeltesten Stand des Ziels nach.
    async def _backfill(self, req_id, target, kind):
        try:
            oldest = self._archive.mam_oldest(target)
            if oldest is None:
                oldest = self._archive.oldest_message_ts(target) or time.time()
            end_dt = datetime.datetime.fromtimestamp(oldest, datetime.timezone.utc)
            start_dt = end_dt - datetime.timedelta(days=30)
            mam = self["xep_0313"]
            if kind == "muc":
                # MUC-Archiv des Raums (unverschluesselt -> voll lesbar).
                iterator = mam.iterate(jid=JID(target), start=start_dt, end=end_dt)
            else:
                # Eigenes Archiv, gefiltert auf den Gespraechspartner.
                iterator = mam.iterate(with_jid=JID(target), start=start_dt, end=end_dt)
            count = 0
            async for result_msg in iterator:
                try:
                    if await self._archive_mam_result(result_msg, target, kind):
                        count += 1
                except Exception:
                    continue
            self._archive.set_mam_oldest(target, start_dt.timestamp())
            self._archive.mark_mam_done(req_id, True)
            logger.info("MAM-Backfill %s (%s): %d neue Nachrichten", target, kind, count)
        except Exception as e:
            logger.warning("MAM-Backfill %s fehlgeschlagen: %s", target, type(e).__name__)
            self._archive.mark_mam_done(req_id, False)

    # Verarbeitet ein einzelnes MAM-Ergebnis; Rueckgabe True wenn neu archiviert.
    async def _archive_mam_result(self, result_msg, target, kind):
        result = result_msg["mam_result"]
        forwarded = result["forwarded"]
        inner = forwarded["stanza"]
        ts = None
        try:
            stamp = forwarded["delay"]["stamp"]
            if stamp:
                ts = stamp.timestamp()
        except Exception:
            ts = None
        stanza_id = inner["id"] or result["id"] or ""

        if kind == "muc":
            nick = inner["from"].resource
            body = inner["body"]
            if not body or not nick:
                return False
            direction = "out" if nick == self._muc_nick else "in"
            return self._archive.store(target, direction, body, stanza_id, decrypted=True, sender=nick, ts=ts)

        # 1:1
        direction = "out" if inner["from"].bare == self._own_bare else "in"
        # Dedup VOR der Entschluesselung: bereits archivierte Nachrichten nicht erneut
        # OMEMO-entschluesseln (wuerde den Double-Ratchet-Zustand stoeren).
        if self._archive.has(target, direction, "", stanza_id):
            return False
        namespaces = self["xep_0384"].is_encrypted(inner)
        if namespaces:
            ns = next(iter(namespaces))
            try:
                decrypted, _info = await self["xep_0384"].decrypt_message(inner)
                return self._archive.store(target, direction, decrypted["body"] or "", stanza_id,
                                           decrypted=True, namespace=ns, ts=ts)
            except Exception:
                # Vor unserer Geraete-Existenz gesendet / Schluessel weg -> unlesbar.
                return self._archive.store(target, direction, None, stanza_id,
                                           decrypted=False, namespace=ns, ts=ts)
        body = inner["body"]
        if not body:
            return False
        return self._archive.store(target, direction, body, stanza_id, decrypted=True, ts=ts)


# Baut den Daemon aus der Konfiguration und liefert die laufbereite Instanz.
def build_daemon(config):
    archive = MessageArchive(config["archive"]["db_path"])
    bot = ArchiverBot(config, archive)
    return bot
