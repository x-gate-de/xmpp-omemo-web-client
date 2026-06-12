# xmpp-omemo-web-client

An always-online XMPP client that joins your account as an additional **OMEMO**
device, receives and decrypts every 1:1 message, archives the plaintext, and
serves it through a small web UI you can reach from anywhere.

It solves a common OMEMO problem: because OMEMO encrypts **per device**, messages
only reach whichever client happens to be active. If you switch between phone,
office and home, you miss messages. This tool runs 24/7 as one extra device that
is always a recipient, so nothing slips through — and you can read (and reply to)
the full history from a browser.

> Status: works in production for the author. The web UI is in German.

## Why not just use an existing web client?

OMEMO ([XEP-0384](https://xmpp.org/extensions/xep-0384.html)) encrypts each
message separately to **every** published device of the recipient. Browser-based
web clients (Converse.js, JSXC, Movim) decrypt per browser, so a new browser on a
new machine cannot read history that was never encrypted to it. The only robust
answer is a single, always-online device with a stable identity that decrypts
each message the moment it arrives and stores it centrally. That is exactly what
this project is.

## Features

- **Always-online OMEMO archiver** for 1:1 chats (`slixmpp` + `slixmpp-omemo`).
- **Web UI** (FastAPI): conversation list, chat history, live updates (polling),
  unread markers, contact list from your roster.
- **Send** encrypted 1:1 messages from the browser, with status (sent / delivered
  via [XEP-0184](https://xmpp.org/extensions/xep-0184.html) receipts / error).
- **Public group chats (MUC)**: discover, join, read and post — group chats are
  handled in cleartext (no OMEMO in MUC, by design).
- Two small daemons, SQLite storage, no build step, CSP-friendly UI (no external
  CDNs, no inline scripts).

## Honest limitations

- **No retroactive archive.** The daemon only sees messages sent *after* its
  device exists. Forward secrecy makes earlier messages undecryptable.
- **Completeness is not guaranteed.** Contacts who have *manually verified* your
  account will only encrypt to the new archiver device after they trust it.
- **The server stores plaintext.** Decrypted private messages are written to
  disk — protect the host and the archive accordingly. This breaks the at-rest
  confidentiality promise of E2EE; understand the trade-off before deploying.
- **The daemon is visible in MUC rooms** as a participant with its own nick.

## Architecture

```
        XMPP server  ──OMEMO / Carbons / MUC──┐
                                              ▼
                            ┌─────────────────────────────────┐
                            │  Daemon (asyncio, always online) │
                            │  slixmpp + slixmpp-omemo         │
                            │  decrypt on receive, send, join  │
                            └───────┬───────────────┬──────────┘
                  OMEMO state (SQLite)        plaintext + outbox (SQLite)
                                                      │ read-only
                                              ┌───────▼─────────┐
                                              │  Web UI (FastAPI)│  behind a
                                              │  read + compose  │  reverse proxy
                                              └─────────────────┘
```

The daemon is the only component with an XMPP connection and the OMEMO state. The
web UI reads the archive and queues outgoing messages in an outbox table that the
daemon sends.

## Requirements

- Python >= 3.11 (tested on Debian 13 / Python 3.13)
- An XMPP account with OMEMO (you only need normal user access)
- A reverse proxy (e.g. nginx) for the web UI

## Setup

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
chmod 0600 config.yaml
# edit config.yaml: set jid, password, web.auth_password
```

Run the two parts:

```bash
OMEMO_WEB_CONFIG=$PWD/config.yaml python run_daemon.py --config $PWD/config.yaml
OMEMO_WEB_CONFIG=$PWD/config.yaml python run_web.py
```

For production, install the systemd units and reverse-proxy config in `deploy/`
(`omemo-web.service`, `omemo-web-ui.service`, `nginx-chat.example.com.conf`) and
adjust paths to your host. The web UI listens on `127.0.0.1:8080` by default and
is meant to sit behind a TLS-terminating proxy. Access requires HTTP Basic auth
(`web.auth_user` / `web.auth_password`).

## Configuration

All settings live in `config.yaml` (see `config.yaml.example`). The XMPP password
and the web password are only in `config.yaml` (file mode `0600`, never committed).

## Project layout

| Path | Description |
|------|-------------|
| `src/daemon.py` | Always-online OMEMO archiver + sender + MUC |
| `src/omemo_storage.py` | Persistent OMEMO state (SQLite) |
| `src/archive.py` | Plaintext archive + outbox |
| `src/schema.py` | Shared SQLite schema |
| `src/web/` | FastAPI web UI + templates + static assets |
| `run_daemon.py` / `run_web.py` | Entry points |
| `deploy/` | systemd units + nginx reverse-proxy example |
| `SPEC.md` | Behavioral specification |

## License

[AGPL-3.0-or-later](LICENSE). Copyright (C) 2026 Torben Belz.

If you run a modified version as a network service, the AGPL requires you to offer
the corresponding source to its users.
