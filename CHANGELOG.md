# Changelog

## [Unreleased]
- Optional: file attachments (OMEMO media, XEP-0454).
- Optional: MAM backfill to cover daemon downtime.

## [0.1.0] - 2026-06-12 - Initial public release
- Always-online OMEMO archiver for 1:1 chats (slixmpp + slixmpp-omemo): joins as
  an additional device, enables Message Carbons, decrypts on receive, archives
  plaintext to SQLite (separate from OMEMO state).
- Web UI (FastAPI, mandatory HTTP Basic auth): conversation list, history, live
  updates via polling, unread markers, contact list from the roster.
- Sending of encrypted 1:1 messages via an outbox processed by the daemon, with
  send status (sent / delivered via XEP-0184 / error).
- Public group chats (MUC, cleartext): room discovery, join, receive and send.
- Messenger-style responsive UI with automatic dark mode (CSP-friendly, no CDNs).
- systemd units and an nginx reverse-proxy example under `deploy/`.
