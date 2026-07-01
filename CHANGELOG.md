# Changelog

## [Unreleased]
- Optional: MAM backfill to cover daemon downtime.

## [1.6.1] - 2026-07-01
- Fix reconnect storm (regression from the 1.6.0 watchdog). After a longer
  disconnect the watchdog built a SECOND bot for the same account; both bound the
  same resource `/archiver` and kicked each other off the server -> continuous flap
  (connect/disconnect every few seconds), nothing archived. Root cause: in slixmpp
  1.16 the connection does not reconnect itself after a drop, so the keepalive
  reconnect and the watchdog rebuild ran in parallel. Fix: the watchdog no longer
  builds a new bot but reconnects the EXISTING one (`bot.connect()`, slixmpp
  backoff), so there is always exactly one connection per account -> no resource
  conflict, no storm.

## [1.6.0] - 2026-06-26
- Connection robustness (bugfix: hours-long silent offline + message loss). After a
  dropped connection the daemon could stay offline for hours without reconnecting;
  messages sent via the web UI were marked "sent" but never reached the server.
  - Reconnect watchdog in the manager: checks `is_connected()` each poll and rebuilds
    dead connections after `xmpp.reconnect_after_seconds` (default 60).
  - Active keepalive (XEP-0199, 60s/30s): detects dead/half-open connections within
    1-2 minutes instead of waiting for a long TCP timeout.
  - Offline send guard: messages are only sent when a session is actually up;
    otherwise they stay in the outbox ("sending …") and go out after reconnect --
    no more silent loss.
  - Online indicator now reflects the real connection: "connecting …" instead of a
    false "online" on drop (auth state reset on `disconnected`).

## [1.5.0] - 2026-06-25
- Read API (read-only, per-account Bearer token): query your own archive from
  scripts and integrations. Tokens are created/revoked in Settings and stored only
  as a SHA-256 hash (the plaintext is shown exactly once on creation).
  - `GET /api/v1/chats`: list of chats (JID, name, room flag, count, last activity).
  - `GET /api/v1/messages?partner=<JID[,JID...]>&hours=24`: messages of one, several
    or all chats over a time window (alternatively `from`/`to` as unix seconds;
    `limit` up to 20000, `truncated` flag when there are more hits).
  - `GET /api/feed?since=<ts>&limit=200&include_outgoing=false&include_muc=true`:
    incremental polling feed (ascending by time, returns `next_since`). Items carry
    a stable `external_id` (= message id) for reliable external dedup, plus `title`,
    `body` (attachments only as a hint), `sender`, `ts_source`, `url` (deep link).
  - Reachable like the web UI; any configured network/geo restriction stays in effect.
- Login hardening (public deployment): per-IP brute-force brake (default 5 failed
  attempts / 5 min) and a global throttle on triggered XMPP validations (default
  5/min) -> prevents login floods from getting the chat server fail2ban-blocked at
  the XMPP server (all logins share one source IP). Optional JID domain allowlist
  (xmpp.allowed_domains): only your own domain(s) are allowed, foreign JIDs are
  rejected without contacting any XMPP server. Session cookie now Secure (HTTPS
  only). Thresholds configurable in config.yaml.

## [1.4.0] - 2026-06-15
- Attachments via drag & drop: drag one or more files into the chat window and drop
  them to send as attachments (1:1 only, same path as the paperclip). With a "drop
  here" overlay and a 30 MB per-file limit.
- Push polish: the notification title is now the chat/sender name (instead of
  "Chat"). iOS automatically appends "from <app name>", which previously produced
  a redundant "Chat from Chat"; now e.g. "Tom Ziegler / from Chat / New message".
- Sticky conversation header (name/bell/shield) below the app bar, so the push bell
  stays reachable even in very long threads (no scrolling to the top).
- Settings menu: tidied the account-deletion entry (trash icon, single-line
  "Account loeschen"; full wording in the tooltip and on the confirmation page).

## [1.3.0] - 2026-06-15
- User guide (German) + help link: step-by-step guide ANLEITUNG.md (login, install
  to phone, read/send, attachments, search, minimize/close, rooms, encryption/
  verification, push, settings, account deletion, limits). The Settings menu links
  to it ("Hilfe & Anleitung").
- Push notifications (Web Push, selective per chat): enable push per person/room via
  the bell in the chat header. Only selected chats trigger a notification, so busy
  rooms stay silent. Content-less for privacy: the notification only shows "New
  message from/in <name>" plus a deep link to the chat -- no message text leaves the
  server toward the push service. Building blocks: service worker (/sw.js), VAPID keys
  in config.yaml (scripts/gen_vapid.py), per-account device subscriptions + selection
  (push_subscriptions/push_prefs), daemon-side send on incoming live messages (1:1 +
  room), pruning of expired subscriptions (HTTP 404/410). Requires HTTPS; on iPhone
  (iOS 16.4+) only as an app added to the Home Screen. New dependency: pywebpush.

## [1.2.0] - 2026-06-15
- Settings menu + account deletion: the "Design" menu is now "Settings" (gear
  icon). A new entry "Delete account and stored data on this server" leads to a
  confirmation page ("Are you sure?"). On confirm, the account (encrypted
  credentials), the message archive and the OMEMO state are irreversibly deleted
  and the user is logged out. The web UI marks the deletion (disables the account);
  the daemon manager disconnects and removes the account directory only once no DB
  handle is open (no race on open files).

## [1.1.0] - 2026-06-15
- Readable send errors + dismissable failures + version hint: encryption/send
  errors now show a readable message (e.g. "recipient has no trusted OMEMO device")
  instead of the technical exception name; failed outbox jobs can be dismissed via
  an "x" (clears the red error bubble; deletes only 'error' rows); the design menu
  shows a small product-version footer ("X-Chat <version>") linking to this changelog.
- Send attachments (OMEMO media, XEP-0454/0363): you can now send files/images
  in 1:1 chats (paperclip in the composer; picking a file sends it immediately).
  Flow: the web UI spools the file and queues a media job; the daemon AES-256-GCM-
  encrypts it, uploads it via HTTP File Upload (XEP-0363) and sends the aesgcm://
  URL (key+IV in the fragment) only inside the OMEMO-encrypted body (no cleartext
  OOB, so the key stays secret). The spool file is then deleted and the message is
  archived as 'out' (inline display as on receive). New dependency: aiohttp
  (needed by slixmpp for the upload). nginx: client_max_body_size 32m (default is
  1 MB); web limit 30 MB. 1:1 only (OMEMO); not in plaintext group rooms.
- Display attachments (OMEMO media, XEP-0454): images from 1:1 chats arrive as
  `aesgcm://` links (the file is AES-256-GCM-encrypted on the HTTP upload server,
  key+IV in the URL fragment). A new decrypting media proxy `/media/{msg_id}`
  (session-auth) fetches the file and serves the plaintext; images render inline,
  other files are linked. The list shows `[Bild]`/`[Anhang]` instead of the raw
  link. Security: fetch only from the account's own XMPP domain (SSRF guard),
  30 MB limit, nosniff, Cache-Control private; key material stays server-side.
- Bugfix: the conversation list stopped live-updating whenever any reply field
  had focus — even an empty one. As a result a tab froze when the cursor sat in an
  empty "Reply …" field (visible across machines: one window live, the other
  frozen). Now the list only pauses while a non-empty draft is being typed; focus
  on an empty field is preserved across the rebuild. Also: on an expired session
  (HTTP 401) the page redirects to login instead of silently freezing.
- MUC nick without the "-web" suffix: the archiver appeared in public rooms as
  "<user>-web", confusing other participants. Since it is just another resource
  of the same account and the server allows multi-session with the same nick, it
  now joins under the plain username ("<user>"). Login stores muc_nick = username.
- Bugfix: do not archive or display empty messages. Other own clients regularly
  send empty messages (e.g. OMEMO-encrypted chat states/markers with no text)
  that arrived as an empty body and showed up as "(empty)". The daemon no longer
  archives empty bodies (live plain + OMEMO and MAM backfill check the body after
  decryption), and the web UI filters already-archived empty rows out of all read
  queries (conversation list incl. preview/recent, thread view, pagination).
  Undecryptable messages (decrypted=0) remain visible.
- SPEC.md brought up to date: multi-user login (F1), session-based access control
  for the web UI (F6), and new requirements F12-F18 (full-text search, quote
  replies, OMEMO verification, pagination and on-demand MAM backfill, online
  toggle, presentation/ergonomics incl. minimize/close and relative time,
  installability). Non-functional requirements and scope updated accordingly.
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
