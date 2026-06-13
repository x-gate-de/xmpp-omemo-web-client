#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Skript: run_daemon.py
# Autor: Torben Belz
# Version: 2.0.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Einstiegspunkt fuer den Multi-User Archiv-Daemon (Account-Manager).
# Ablauf:
# - Konfiguration + Account-Registry laden, Manager starten, Event-Loop laufen lassen.
# Betriebs- und Wartungshinweise:
# - Aufruf: python3 run_daemon.py --config /opt/omemo-web/config.yaml
# - Haelt je aktivem Account eine dauerhafte XMPP-Verbindung.
# -----------------------------------------------------------------------------

import argparse
import asyncio
import logging
import sys

from src.accounts import AccountRegistry
from src.config import ConfigError, load_config
from src.manager import AccountManager


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
    parser = argparse.ArgumentParser(description="Chat Multi-User Archiv-Daemon")
    parser.add_argument("--config", default="/opt/omemo-web/config.yaml", help="Pfad zur config.yaml")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 2

    _setup_logging(config["logging"])
    logger = logging.getLogger("run_daemon")

    registry = AccountRegistry(
        config["accounts"]["db_path"],
        config["security"]["fernet_key"],
        config["accounts"]["users_dir"],
    )
    manager = AccountManager(registry, config)

    # Eigenen Event-Loop einrichten; die slixmpp-Bots haengen sich hier ein.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(manager.run())
    logger.info("Daemon laeuft (Multi-User)")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
