#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Skript: run_daemon.py
# Autor: Torben Belz
# Version: 1.0.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Einstiegspunkt fuer den Chat Archiv-Daemon.
# Ablauf:
# - Konfiguration laden, Logging einrichten, Daemon verbinden und Event-Loop starten.
# Betriebs- und Wartungshinweise:
# - Aufruf: python3 run_daemon.py --config /opt/omemo-web/config.yaml
# - Laeuft im Betrieb als systemd-Service mit automatischem Reconnect.
# -----------------------------------------------------------------------------

import argparse
import logging
import sys

from src.config import ConfigError, load_config
from src.daemon import build_daemon


def _setup_logging(log_cfg):
    level = getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_cfg.get("file"):
        handlers.append(logging.FileHandler(log_cfg["file"], encoding="utf8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(description="Chat Archiv-Daemon")
    parser.add_argument(
        "--config",
        default="/opt/omemo-web/config.yaml",
        help="Pfad zur config.yaml",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 2

    _setup_logging(config["logging"])
    logger = logging.getLogger("run_daemon")

    bot = build_daemon(config)
    # TLS-Verifikation ist Standard; slixmpp verifiziert das Serverzertifikat.
    logger.info("Verbinde mit XMPP-Server ...")
    xmpp_cfg = config["xmpp"]
    # Expliziten Host nutzen, falls die JID-Domain (example.com) per DNS-SRV nicht
    # auf den XMPP-Host (xmpp.example.com) aufloest. Sonst Standard-SRV-Aufloesung.
    if xmpp_cfg.get("host"):
        bot.connect(xmpp_cfg["host"], int(xmpp_cfg.get("port", 5222)))
    else:
        bot.connect()
    # slixmpp 1.16 hat kein process(); der asyncio-Loop laeuft dauerhaft und
    # slixmpp reconnectet bei Verbindungsabbruch selbsttaetig.
    bot.loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
