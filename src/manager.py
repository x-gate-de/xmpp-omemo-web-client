# -----------------------------------------------------------------------------
# Skript: src/manager.py
# Autor: Torben Belz
# Version: 1.0.0
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

from .daemon import build_daemon

logger = logging.getLogger(__name__)


class AccountManager:
    def __init__(self, registry, config):
        self._registry = registry
        self._config = config
        self._default_host = config["xmpp"].get("default_host") or ""
        self._default_port = int(config["xmpp"].get("default_port") or 5222)
        self._bots = {}

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
        }

    def _connect(self, acc):
        jid = acc["jid"]
        try:
            self._registry.set_auth_state(jid, "connecting")
            bot = build_daemon(self._build_config(acc))
            # Auth-Ergebnis ueber die echte Verbindung zurueckmelden (Login-Validierung).
            bot.add_event_handler("session_start", lambda _e, j=jid: self._registry.set_auth_state(j, "ok"))

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

    def _disconnect(self, jid):
        bot = self._bots.pop(jid, None)
        if bot is not None:
            try:
                bot.disconnect()
            except Exception:
                pass
            logger.info("Account getrennt: %s", jid)

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
                for jid in list(self._bots):
                    if jid not in wanted:
                        self._disconnect(jid)
            except Exception as e:
                logger.error("Manager-Schleife fehlgeschlagen: %s", type(e).__name__)
            await asyncio.sleep(3)
