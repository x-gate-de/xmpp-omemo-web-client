# -----------------------------------------------------------------------------
# Skript: src/manager.py
# Autor: Torben Belz
# Version: 1.3.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Account-Manager fuer den Multi-User-Betrieb: haelt je aktivem Account eine
#   dauerhafte XMPP/OMEMO-Verbindung (eigenes Archiv + OMEMO-State).
# Ablauf:
# - Pollt die Account-Registry; verbindet neue Accounts, trennt entfernte/
#   deaktivierte. Jeder Bot archiviert in das Account-eigene Verzeichnis.
# Betriebs- und Wartungshinweise:
# - Laeuft als ein Prozess im gemeinsamen asyncio-Loop.
# - Es werden keine Passwoerter geloggt.
# -----------------------------------------------------------------------------

import asyncio
import logging
import shutil
import time

from .daemon import build_daemon

logger = logging.getLogger(__name__)


class AccountManager:
    def __init__(self, registry, config):
        self._registry = registry
        self._config = config
        self._default_host = config["xmpp"].get("default_host") or ""
        self._default_port = int(config["xmpp"].get("default_port") or 5222)
        self._bots = {}
        # Watchdog: ab wann eine als getrennt erkannte Verbindung hart neu aufgebaut
        # wird (Backstop, falls slixmpps eigener Reconnect nicht greift).
        self._reconnect_after = float(config["xmpp"].get("reconnect_after_seconds", 60))
        self._down_since = {}  # jid -> monotone Zeit, seit der der Bot getrennt ist

    # Baut die per-Account-Konfiguration in der vom Daemon erwarteten Form.
    def _build_config(self, acc):
        jid = acc["jid"]
        return {
            "xmpp": {
                "jid": jid,
                "password": acc["password"],
                "resource": acc["resource"] or self._config["xmpp"].get("resource", "archiver"),
                "muc_nick": acc["muc_nick"],
                "tls_verify": self._config["xmpp"].get("tls_verify", True),
            },
            "omemo": {
                "state_path": self._registry.state_path(jid),
                "trust_policy": self._config["omemo"].get("trust_policy", "btbv"),
            },
            "archive": {"db_path": self._registry.archive_path(jid)},
            "push": self._config.get("push") or {},
        }

    def _connect(self, acc):
        jid = acc["jid"]
        try:
            self._registry.set_auth_state(jid, "connecting")
            bot = build_daemon(self._build_config(acc))
            bot.auto_reconnect = True
            # Auth-Ergebnis ueber die echte Verbindung zurueckmelden (Login-Validierung).
            bot.add_event_handler("session_start", lambda _e, j=jid: self._registry.set_auth_state(j, "ok"))
            # Verbindungsverlust im Auth-State spiegeln -> UI zeigt "Verbindet ..." statt
            # faelschlich "Online". Nur aus dem Zustand "ok" heraus, damit "failed"/
            # "pending" (Login-Validierung) nicht ueberschrieben werden.
            bot.add_event_handler("disconnected", lambda _e, j=jid: self._on_bot_disconnected(j))

            def _on_failed(_e, j=jid):
                # Falsche Zugangsdaten: als fehlgeschlagen markieren und deaktivieren,
                # damit nicht endlos weiterprobiert wird.
                logger.warning("Authentifizierung fehlgeschlagen: %s", j)
                self._registry.set_auth_state(j, "failed")
                self._registry.set_enabled(j, False)

            bot.add_event_handler("failed_auth", _on_failed)
            host = acc["host"] or self._default_host
            port = int(acc["port"] or self._default_port)
            if host:
                bot.connect(host, port)
            else:
                bot.connect()
            self._bots[jid] = bot
            logger.info("Account verbindet: %s", jid)
        except Exception as e:
            logger.error("Verbindung %s fehlgeschlagen: %s", jid, type(e).__name__)

    # Spiegelt einen Verbindungsabbruch in den Auth-State (fuer die UI-Anzeige).
    # Nur aus "ok" heraus -> "failed"/"pending" der Login-Validierung bleiben erhalten.
    def _on_bot_disconnected(self, jid):
        if self._registry.get_auth_state(jid) == "ok":
            self._registry.set_auth_state(jid, "connecting")

    def _disconnect(self, jid):
        bot = self._bots.pop(jid, None)
        self._down_since.pop(jid, None)
        if bot is not None:
            try:
                # Eigenen Reconnect des verworfenen Bots unterbinden, damit keine
                # Geister-Verbindung neben dem frisch aufgebauten Bot weiterlaeuft.
                bot.auto_reconnect = False
                bot.disconnect()
            except Exception:
                pass
            logger.info("Account getrennt: %s", jid)

    # Watchdog: erkennt tote Verbindungen und baut sie nach _reconnect_after neu auf.
    # Backstop fuer den Fall, dass slixmpps eigener Reconnect nicht greift (genau der
    # Ausfall, der zu stundenlanger stiller Offline-Zeit gefuehrt hat).
    def _check_health(self, jid, acc):
        bot = self._bots.get(jid)
        if bot is None:
            return
        if bot.is_connected():
            self._down_since.pop(jid, None)
            return
        now = time.monotonic()
        first = self._down_since.setdefault(jid, now)
        if now - first >= self._reconnect_after:
            logger.warning("Verbindung tot seit %.0fs -- baue %s neu auf", now - first, jid)
            self._disconnect(jid)
            self._connect(acc)

    # Endlosschleife: aktive Accounts mit den laufenden Bots abgleichen.
    async def run(self):
        logger.info("Account-Manager gestartet")
        while True:
            try:
                wanted = {a["jid"]: a for a in self._registry.enabled_accounts()}
                for jid, acc in wanted.items():
                    if jid not in self._bots:
                        self._connect(acc)
                    elif acc["auth_state"] == "pending":
                        # Web hat sich (erneut) angemeldet, evtl. mit neuem Passwort
                        # -> alte Verbindung trennen und mit aktuellen Daten neu verbinden.
                        self._disconnect(jid)
                        self._connect(acc)
                    else:
                        self._check_health(jid, acc)
                for jid in list(self._bots):
                    if jid not in wanted:
                        self._disconnect(jid)
                # Vorgemerkte Loeschungen ausfuehren -- erst wenn der Bot getrennt ist
                # (kein offener Zugriff mehr auf die Account-Daten).
                for jid in self._registry.pending_deletions():
                    if jid not in self._bots:
                        self._delete_account(jid)
            except Exception as e:
                logger.error("Manager-Schleife fehlgeschlagen: %s", type(e).__name__)
            await asyncio.sleep(3)

    # Loescht das Account-Verzeichnis (Archiv, OMEMO-State, Spool) und den Account-
    # Eintrag. Unwiderruflich -- nur nach ausdruecklicher Bestaetigung in der Web-UI.
    def _delete_account(self, jid):
        try:
            shutil.rmtree(self._registry.account_dir(jid), ignore_errors=True)
            self._registry.finalize_deletion(jid)
            logger.info("Account und Daten geloescht: %s", jid)
        except Exception as e:
            logger.error("Account-Loeschung %s fehlgeschlagen: %s", jid, type(e).__name__)
