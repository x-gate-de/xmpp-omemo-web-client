# Changelog

## [Unreleased]
- Optional: file attachments (OMEMO media, XEP-0454).
- Optional: MAM backfill to cover daemon downtime.
- Optional: account deletion (remove stored credentials + archive).

## [1.0.0] - 2026-06-13 - First stable release
First complete release of the always-online OMEMO archiver with web UI.
Bundles the full feature set developed so far (see the entries below):
multi-user login with encrypted-at-rest credentials, one permanently
connected daemon per account, OMEMO decryption and plaintext archive, web UI
with sending, live updates, list/grid view, theme switcher, full-text search,
quote replies, OMEMO verification, installable app icon / full screen, and
on-demand MAM backfill.

## [0.1.0] - 2026-06-13 - Initial public release
- Multi-user: log in with your own XMPP JID/password/server; credentials are
  validated against the XMPP server and stored encrypted (Fernet). Cookie session.
- Always-online per user: an account manager keeps every enabled account connected
  24/7 and archives in the background, independent of the web session.
- Online toggle per account in the app bar, with live status.
- Per-account OMEMO archiver (slixmpp + slixmpp-omemo): joins as an additional
  device, enables Message Carbons, decrypts on receive, stores plaintext to SQLite
  (separate from OMEMO state); per-user data isolation.
- Sending of encrypted 1:1 messages via a per-user outbox processed by the daemon,
  with send status (sent / delivered via XEP-0184 / error).
- Public group chats (MUC, cleartext): room discovery, join, receive and send.
- Messenger-style responsive UI with automatic dark mode (CSP-friendly, no CDNs).
- systemd units and an nginx reverse-proxy example under `deploy/`.
