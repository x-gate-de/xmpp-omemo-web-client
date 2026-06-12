# -----------------------------------------------------------------------------
# Skript: src/config.py
# Autor: Torben Belz
# Version: 1.0.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Laedt und validiert die YAML-Konfiguration fuer Daemon und Web-UI.
# Ablauf:
# - YAML-Datei einlesen, Pflichtfelder pruefen, Defaults setzen.
# Betriebs- und Wartungshinweise:
# - config.yaml enthaelt das XMPP-Passwort und gehoert nicht ins Repository.
# -----------------------------------------------------------------------------

import logging
import os

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


# Laedt die Konfiguration aus einer YAML-Datei und validiert die Pflichtfelder.
# Rueckgabe: verschachteltes dict. Wirft ConfigError bei fehlenden Pflichtwerten.
def load_config(path):
    if not os.path.isfile(path):
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {path}")

    with open(path, encoding="utf8") as f:
        data = yaml.safe_load(f) or {}

    xmpp = data.get("xmpp") or {}
    # Pflichtfelder fuer die XMPP-Anmeldung. Ohne JID/Passwort kein Betrieb.
    if not xmpp.get("jid"):
        raise ConfigError("xmpp.jid fehlt in der Konfiguration")
    if not xmpp.get("password"):
        raise ConfigError("xmpp.password fehlt in der Konfiguration")

    # Defaults ergaenzen, damit der Rest des Codes sich auf Werte verlassen kann.
    xmpp.setdefault("resource", "archiver")
    xmpp.setdefault("tls_verify", True)
    data["xmpp"] = xmpp

    omemo = data.get("omemo") or {}
    omemo.setdefault("state_path", "/var/lib/omemo-web/omemo_state.sqlite")
    omemo.setdefault("trust_policy", "btbv")
    data["omemo"] = omemo

    archive = data.get("archive") or {}
    archive.setdefault("db_path", "/var/lib/omemo-web/messages.sqlite")
    data["archive"] = archive

    web = data.get("web") or {}
    web.setdefault("bind_host", "127.0.0.1")
    web.setdefault("bind_port", 8080)
    web.setdefault("base_path", "/")
    # Pflicht-Login fuer die Web-UI (Klartext privater Nachrichten).
    web.setdefault("auth_user", None)
    web.setdefault("auth_password", None)
    data["web"] = web

    log = data.get("logging") or {}
    log.setdefault("level", "INFO")
    log.setdefault("file", None)
    data["logging"] = log

    return data
