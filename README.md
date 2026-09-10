# xmpp-omemo-web-client

A multi-user, always-online XMPP client: each user logs in with their own XMPP
credentials, and the server keeps that account connected as an additional
**OMEMO** device 24/7 — receiving and decrypting every 1:1 message, archiving the
plaintext, and serving it through a small web UI reachable from anywhere.

It solves a common OMEMO problem: because OMEMO encrypts **per device**, messages
only reach whichever client happens to be active. If you switch between phone,
office and home, you miss messages. This tool runs as one extra device that is
always a recipient, so nothing slips through — and you can read (and reply to) the
full history from a browser, even when you are not logged in.

> Status: works in production for the author. The web UI is in German.

## Why not just use an existing web client?

OMEMO ([XEP-0384](https://xmpp.org/extensions/xep-0384.html)) encrypts each
message separately to **every** published device of the recipient. Browser-based
web clients (Converse.js, JSXC, Movim) decrypt per browser, so a new browser on a
new machine cannot read history that was never encrypted to it. The only robust
answer is a single, always-online device with a stable identity that decrypts each
message the moment it arrives and stores it centrally. That is what this project is.

## Features

- **Multi-user**: log in with XMPP JID + password + server (default prefilled).
  Credentials are validated against the real XMPP server and stored encrypted.
- **Always-online per user**: an account manager keeps every enabled account
  connected 24/7; archiving continues even when nobody is logged into the web UI.
- **Online toggle**: each user can switch their account online/offline from the
  app bar (with live status).
- **Web UI** (FastAPI): conversation list, history, live updates (polling), unread
  markers, contact list from the roster — per user, isolated.
- **Send** encrypted 1:1 messages with status (sent / delivered via
  [XEP-0184](https://xmpp.org/extensions/xep-0184.html) receipts / error).
- **Delivery detail**: one tick means handed to the server, two ticks mean a client
  on the other side acknowledged receipt. Click the ticks to see *which* devices
  acknowledged — client, version, platform, resource and time; the count next to the
  ticks shows how many. Clients are identified passively from entity capabilities
  ([XEP-0115](https://xmpp.org/extensions/xep-0115.html)) plus a single software
  version query ([XEP-0092](https://xmpp.org/extensions/xep-0092.html)) per unknown
  resource. Acknowledged means received, not read — chat markers
  ([XEP-0333](https://xmpp.org/extensions/xep-0333.html)) are not evaluated.
- **Group chats (MUC)**: the room list is built from two sources — the server's
  service discovery (public rooms only) **and the user's bookmarks**
  ([XEP-0402](https://xmpp.org/extensions/xep-0402.html), plus the two older
  [XEP-0048](https://xmpp.org/extensions/xep-0048.html) stores). A private room is
  not discoverable server-side, so without the bookmarks it is invisible. Rooms only
  a client keeps locally can be added by typing the room JID. Joining is always a
  deliberate click, never automatic — not even for an `autojoin` bookmark.
- **Encrypted rooms**: OMEMO group messages are decrypted and archived. Sending into
  an encrypted room is refused — cleartext there would lie open on the server and
  show up as unencrypted for everyone else; the composer is hidden in such rooms.
  Open rooms remain cleartext, as designed.
- **Design presets** (gear → Design): "Standard" (light/dark, six accent colours)
  and "Leitstand" — a dark, hairline, monospace look in which colour only carries
  meaning. Dark-only, so the mode and accent pickers are hidden in it. The choice
  lives in the browser, not on the account.
- No build step, CSP-friendly UI (no external CDNs, no inline scripts), dark mode.

## Security model & honest limitations

- **Stored credentials**: to stay always-online, each user's XMPP password is
  stored, encrypted with a server-side Fernet key (`security.fernet_key`). Anyone
  with the server and that key can decrypt them — protect both.
- **Plaintext archive**: decrypted private messages are written to disk per user.
  This breaks the at-rest confidentiality promise of E2EE; understand the trade-off.
- **No retroactive archive**: a device only sees messages sent *after* it exists
  (forward secrecy). Completeness also depends on peers encrypting to the new device.
- **The daemon is visible in MUC rooms** as a participant with its own nick.
- A wrong login cannot disturb an already-connected account (no overwrite/disable).

## Architecture

```
   XMPP server ──OMEMO / Carbons / MUC──┐  (one connection per enabled account)
                                        ▼
                    ┌───────────────────────────────────┐
                    │  Daemon: account manager (asyncio) │
                    │  one bot per account, decrypt+send  │
                    └───────┬───────────────┬────────────┘
        accounts.db (creds) │               │ per-user archive + OMEMO state
        encrypted passwords  │               │ (users/<slug>/)
                             ▼               ▼
                      ┌────────────────────────────┐
                      │  Web UI (FastAPI)           │  behind a reverse proxy
                      │  login (session) + per-user │
                      └────────────────────────────┘
```

The daemon holds the XMPP connections and OMEMO state. The web UI authenticates a
user against their stored account, shows that user's archive, and queues outgoing
messages in a per-user outbox the daemon sends. Login is validated through the
manager's real connection (`auth_state` pending → ok/failed), so the web never
opens its own fragile XMPP connection.

## Requirements

- Python >= 3.11 (tested on Debian 13 / Python 3.13)
- One or more XMPP accounts with OMEMO (only normal user access needed)
- A reverse proxy (e.g. nginx) for the web UI

## Setup

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
chmod 0600 config.yaml
# generate the two server keys and put them into config.yaml:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # -> security.fernet_key
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                  # -> security.session_secret
```

Run the two parts:

```bash
OMEMO_WEB_CONFIG=$PWD/config.yaml python run_daemon.py --config $PWD/config.yaml   # account manager
OMEMO_WEB_CONFIG=$PWD/config.yaml python run_web.py                                # web UI
```

For production, install the systemd units and reverse-proxy config in `deploy/`
(`omemo-web.service`, `omemo-web-ui.service`, `nginx-chat.example.com.conf`) and
adjust paths to your host. The web UI listens on `127.0.0.1:8080` and is meant to
sit behind a TLS-terminating proxy.

## Usage

Open the web UI and log in with an XMPP JID, password and server. The account is
validated, then kept online and archived in the background. Returning users with an
already-validated account log in instantly. Use the online toggle in the app bar to
pause/resume an account; logging out only ends the browser session — archiving
continues.

## Read API

Read-only access to your **own** archive via a **per-account Bearer token**. Tokens are
created/revoked in Settings (gear → "API-Token"); only the SHA-256 hash is stored and the
plaintext token is shown exactly once. The API is reachable like the web UI (any
configured network/geo restriction stays in effect).

    # list chats
    curl -H "Authorization: Bearer <TOKEN>" https://chat.example.com/api/v1/chats

    # one chat / several / all over a time window
    curl -H "Authorization: Bearer <TOKEN>" \
      "https://chat.example.com/api/v1/messages?partner=room@conference...&hours=24"
    curl -H "Authorization: Bearer <TOKEN>" \
      "https://chat.example.com/api/v1/messages?hours=24"            # all chats
    curl -H "Authorization: Bearer <TOKEN>" \
      "https://chat.example.com/api/v1/messages?partner=a@x,b@x&hours=48"  # selected

    # incremental polling feed (returns next_since for the following call)
    curl -H "Authorization: Bearer <TOKEN>" \
      "https://chat.example.com/api/feed?since=<ts>&limit=200&include_outgoing=false&include_muc=true"

`/api/feed` items carry a stable `external_id` (= message id) for reliable external
dedup, plus `title`, `body` (attachments only as a hint), `sender`, `ts_source`, `url`.
Full API documentation: API.md. See also SPEC.md, section F22.

## Configuration

All settings live in `config.yaml` (see `config.yaml.example`). It holds global
defaults and the two server keys; **user credentials are never in this file** —
they come from the web login and are stored encrypted in `accounts.db`.

## Project layout

| Path | Description |
|------|-------------|
| `src/accounts.py` | Account registry (encrypted credentials, per-user paths) |
| `src/manager.py` | Account manager: one always-online connection per account |
| `src/daemon.py` | Per-account OMEMO archiver + sender + MUC |
| `src/omemo_storage.py` | Persistent OMEMO state (SQLite) |
| `src/archive.py` | Plaintext archive + outbox |
| `src/schema.py` | Shared per-user SQLite schema |
| `src/web/` | FastAPI web UI (login/session) + templates + static assets |
| `run_daemon.py` / `run_web.py` | Entry points |
| `deploy/` | systemd units + nginx reverse-proxy example |
| `SPEC.md` | Behavioral specification |

## License

[AGPL-3.0-or-later](LICENSE). Copyright (C) 2026 Torben.

If you run a modified version as a network service, the AGPL requires you to offer
the corresponding source to its users.
