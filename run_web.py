#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Skript: run_web.py
# Autor: Torben Belz
# Version: 1.0.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Einstiegspunkt fuer die Web-UI (uvicorn + FastAPI), nur lesend.
# Ablauf:
# - Konfiguration laden, Bind-Adresse/Port bestimmen, uvicorn starten.
# Betriebs- und Wartungshinweise:
# - Aufruf: OMEMO_WEB_CONFIG=/opt/omemo-web/config.yaml python3 run_web.py
# - Lauscht lokal; externer Zugriff ueber nginx/traefik.
# -----------------------------------------------------------------------------

import os
import sys

import uvicorn

from src.config import load_config


def main():
    cfg_path = os.environ.get("OMEMO_WEB_CONFIG", "/opt/omemo-web/config.yaml")
    # Pfad an die App weiterreichen, die ihn beim Import erneut liest.
    os.environ["OMEMO_WEB_CONFIG"] = cfg_path
    web = load_config(cfg_path)["web"]
    uvicorn.run(
        "src.web.app:app",
        host=web["bind_host"],
        port=int(web["bind_port"]),
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
