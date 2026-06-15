# -----------------------------------------------------------------------------
# Skript: src/config.py
# Autor: Torben Belz
# Version: 2.0.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Laedt und validiert die YAML-Konfiguration (Multi-User-Betrieb).
# Ablauf:
# - YAML einlesen, Pflichtfelder pruefen, Defaults setzen.
# Betriebs- und Wartungshinweise:
# - Zugangsdaten kommen NICHT mehr aus der config, sondern aus der Account-
#   Registry (Login). Die config haelt nur globale Einstellungen + Server-Keys.
# -----------------------------------------------------------------------------

import logging
import os

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


# Laedt die Konfiguration aus einer YAML-Datei und validiert die Pflichtfelder.
def load_config(path):
    if not os.path.isfile(path):
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {path}")

    with open(path, encoding="utf8") as f:
        data = yaml.safe_load(f) or {}

    # Globale XMPP-Defaults (werden beim Login vorbelegt).
    xmpp = data.get("xmpp") or {}
    xmpp.setdefault("default_host", "")
    xmpp.setdefault("default_port", 5222)
    xmpp.setdefault("resource", "archiver")
    xmpp.setdefault("tls_verify", True)
    data["xmpp"] = xmpp

    omemo = data.get("omemo") or {}
    omemo.setdefault("trust_policy", "btbv")
    data["omemo"] = omemo

    accounts = data.get("accounts") or {}
    accounts.setdefault("db_path", "/var/lib/omemo-web/accounts.db")
    accounts.setdefault("users_dir", "/var/lib/omemo-web/users")
    data["accounts"] = accounts

    # Server-Keys sind Pflicht: ohne sie kein Verschluesseln/Sessions.
    security = data.get("security") or {}
    if not security.get("fernet_key"):
        raise ConfigError("security.fernet_key fehlt (Schluessel fuer Passwort-Verschluesselung)")
    if not security.get("session_secret"):
        raise ConfigError("security.session_secret fehlt (Schluessel fuer Web-Sessions)")
    data["security"] = security

    web = data.get("web") or {}
    web.setdefault("bind_host", "127.0.0.1")
    web.setdefault("bind_port", 8080)
    web.setdefault("base_path", "/")
    data["web"] = web

    log = data.get("logging") or {}
    log.setdefault("level", "INFO")
    log.setdefault("file", None)
    data["logging"] = log

    # Web Push (optional). Leere Schluessel = Push deaktiviert.
    push = data.get("push") or {}
    push.setdefault("vapid_private_key", "")
    push.setdefault("vapid_public_key", "")
    push.setdefault("vapid_subject", "")
    data["push"] = push

    return data
