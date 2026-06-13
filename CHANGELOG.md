# Changelog

## [Unreleased]
- Close chats (permanently hide): in addition to minimize, each tile has a close
  button (x). Closed chats disappear from the list entirely and stay hidden even
  on new messages (unlike minimized ones); the archived data is preserved. Restore
  via the collapsed "Closed chats (N)" section at the end of the list or by opening
  the chat directly. Stored per browser in localStorage; close and minimize are
  mutually exclusive.
- Relative time in the chat list: a relative label ("just now", "X min ago",
  "X h ago", "yesterday", "X days ago") is shown before the absolute timestamp
  of the last message. Computed client-side from `last_ts` and kept current by
  the periodic list re-render.
- Minimize conversation tiles: a minimize button moves an unused tile into a
  compact "minimized" tray at the end of the list; its content is preserved.
  Click the chip to reopen. A new incoming message (detected via `last_ts`)
  re-expands the tile automatically. The selection is stored per browser in
  localStorage.
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
