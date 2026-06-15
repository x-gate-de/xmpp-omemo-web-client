# -----------------------------------------------------------------------------
# Skript: src/web/app.py
# Autor: Torben Belz
# Version: 2.7.1
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Multi-User-Web-UI: Login mit XMPP-Zugangsdaten (gegen den XMPP-Server
#   validiert), Cookie-Session, je Nutzer ein eigenes Archiv.
# Ablauf:
# - Beim Login wird ein XMPP-Bind getestet; bei Erfolg wird der Account in der
#   Registry angelegt/aktiviert (Passwort verschluesselt) und eine Session gesetzt.
#   Der Daemon-Manager verbindet den Account dauerhaft.
# Betriebs- und Wartungshinweise:
# - Zeigt entschluesselte private Nachrichten (Schutzbedarf HOCH).
# -----------------------------------------------------------------------------

import os
import sqlite3
import ssl
import time
import urllib.request
import uuid
from datetime import datetime
from urllib.parse import urlparse

import jinja2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from src.accounts import AccountRegistry
from src.config import load_config
from src.schema import ensure_schema

CONFIG_PATH = os.environ.get("OMEMO_WEB_CONFIG", "/opt/omemo-web/config.yaml")
config = load_config(CONFIG_PATH)

_xmpp = config["xmpp"]
_registry = AccountRegistry(
    config["accounts"]["db_path"], config["security"]["fernet_key"], config["accounts"]["users_dir"]
)

app = FastAPI(title="Chat", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config["security"]["session_secret"], same_site="lax")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=True,
)

# Cache-Busting: Versionskennung aus den mtimes der statischen Assets.
_static_dir = os.path.join(os.path.dirname(__file__), "static")


def _asset_version():
    try:
        return str(int(max(os.path.getmtime(os.path.join(_static_dir, f)) for f in ("style.css", "app.js"))))
    except OSError:
        return "1"


_env.globals["asset_ver"] = _asset_version()

# Produktversion (Anzeige im Design-Menue, verlinkt auf den oeffentlichen Changelog).
APP_VERSION = "1.4.0"
CHANGELOG_URL = "https://github.com/x-gate-de/xmpp-omemo-web-client/blob/main/CHANGELOG.md"
HELP_URL = "https://github.com/x-gate-de/xmpp-omemo-web-client/blob/main/ANLEITUNG.md"
_env.globals["app_version"] = APP_VERSION
_env.globals["changelog_url"] = CHANGELOG_URL
_env.globals["help_url"] = HELP_URL

# Web Push: aktiv, wenn VAPID-Schluessel konfiguriert sind.
_push = config.get("push") or {}
_PUSH_PUBLIC = _push.get("vapid_public_key") or ""
_PUSH_ENABLED = bool(_PUSH_PUBLIC and (_push.get("vapid_private_key") or ""))


# --- Authentifizierung ------------------------------------------------------

class NotAuthenticated(Exception):
    pass


# Liefert den eingeloggten Account oder erzwingt Login.
def require_account(request: Request):
    jid = request.session.get("jid")
    if not jid or not _registry.exists(jid):
        raise NotAuthenticated()
    return {"jid": jid, "archive_path": _registry.archive_path(jid)}


@app.exception_handler(NotAuthenticated)
async def _on_not_auth(request: Request, _exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Nicht angemeldet"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


# --- DB-Zugriff (je Account) ------------------------------------------------

def _open_ro(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _open_rw(db_path):
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_db(db_path):
    conn = _open_rw(db_path)
    try:
        ensure_schema(conn)
    finally:
        conn.close()


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _initials(name, jid):
    base = (name or "").strip() or (jid or "").split("@")[0]
    parts = [p for p in base.replace(".", " ").replace("_", " ").replace("-", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (base[:2] or "?").upper()


def _hue(s):
    return sum(ord(c) for c in (s or "")) % 360


def _like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Baut einen Snippet um den ersten Treffer und zerlegt ihn in Segmente
# (match=True fuer die Fundstelle) zur sicheren Hervorhebung im Template.
def _highlight(text, q):
    text = (text or "").replace("\n", " ")
    low, ql = text.lower(), q.lower()
    idx = low.find(ql)
    if idx < 0:
        return [{"text": text[:160] + ("…" if len(text) > 160 else ""), "match": False}]
    start = max(0, idx - 60)
    end = min(len(text), idx + len(q) + 110)
    snippet = ("… " if start > 0 else "") + text[start:end] + (" …" if end < len(text) else "")
    segs, s_low, i = [], snippet.lower(), 0
    while True:
        j = s_low.find(ql, i)
        if j < 0:
            segs.append({"text": snippet[i:], "match": False})
            break
        if j > i:
            segs.append({"text": snippet[i:j], "match": False})
        segs.append({"text": snippet[j:j + len(q)], "match": True})
        i = j + len(q)
    return segs


# Leere Nachrichten (z.B. von anderen eigenen Clients gesendete Chat-States/Marker,
# die ohne echten Text als leerer Body ankamen) sollen nicht angezeigt werden.
# Unlesbare Nachrichten (decrypted=0) bleiben sichtbar. `prefix` ist der Tabellen-Alias
# inkl. Punkt ("", "m.", "x.") fuer die jeweilige Query.
def _nonempty(prefix=""):
    return "(%sdecrypted = 0 OR (%sbody IS NOT NULL AND trim(%sbody) <> ''))" % (prefix, prefix, prefix)


# Volltextsuche ueber das (entschluesselte) Archiv des Nutzers.
def _search(db_path, q, limit=100):
    pat = "%" + _like_escape(q) + "%"
    conn = _open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT m.id, m.partner_jid, m.direction, m.body, m.ts_received, m.sender, "
            "  (SELECT name FROM contacts c WHERE c.jid = m.partner_jid) AS contact_name, "
            "  (SELECT name FROM muc_available a WHERE a.room_jid = m.partner_jid) AS room_name, "
            "  EXISTS(SELECT 1 FROM mucs g WHERE g.room_jid = m.partner_jid) AS is_room "
            "FROM messages m WHERE m.decrypted = 1 AND m.body LIKE ? ESCAPE '\\' "
            "ORDER BY m.ts_received DESC LIMIT ?",
            (pat, limit),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        is_room = bool(r["is_room"])
        name = r["contact_name"] or r["room_name"] or r["partner_jid"]
        out.append({
            "partner": r["partner_jid"], "name": name, "is_room": is_room,
            "ts": _fmt_ts(r["ts_received"]), "direction": r["direction"], "sender": r["sender"],
            "initials": _initials(name if name != r["partner_jid"] else "", r["partner_jid"]),
            "hue": _hue(r["partner_jid"]), "segments": _highlight(r["body"], q),
        })
    return out


# Online-Status eines Accounts fuer die Anzeige + den Umschalter.
# "next" ist der Wert, den der Toggle-Button setzt (Gegenteil von enabled).
def _account_state(jid):
    st = _registry.get_state(jid)
    if not st or not st["enabled"]:
        return {"enabled": False, "label": "Offline", "cls": "off", "next": 1}
    auth = st["auth_state"]
    if auth == "ok":
        return {"enabled": True, "label": "Online", "cls": "on", "next": 0}
    if auth == "failed":
        return {"enabled": True, "label": "Anmeldung fehlgeschlagen", "cls": "error", "next": 0}
    return {"enabled": True, "label": "Verbindet …", "cls": "connecting", "next": 0}


# --- Anhaenge (OMEMO-Media, XEP-0454) ---------------------------------------
# Bilder/Dateien werden als "aesgcm://host/pfad#<iv+key-hex>" verschickt: die Datei
# liegt AES-256-GCM-verschluesselt auf dem HTTP-Upload-Server, Schluessel+IV stehen
# im URL-Fragment. Der OMEMO-Layer hat den Body bereits zu dieser URL entschluesselt.
_MEDIA_IMG_EXT = ("jpg", "jpeg", "png", "gif", "webp", "bmp")
_MEDIA_CT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "svg": "image/svg+xml",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
    "mp3": "audio/mpeg", "ogg": "audio/ogg", "oga": "audio/ogg", "wav": "audio/wav",
    "pdf": "application/pdf", "txt": "text/plain",
}
_MEDIA_MAX = 30 * 1024 * 1024  # 30 MB Obergrenze pro Anhang


def _media_info(body, msg_id):
    # Erkennt eine reine OMEMO-Media-URL als Anhang. Nur ein einzelnes URL-Token gilt
    # als Anhang (URL + Freitext lassen wir als normalen Text stehen).
    if not body:
        return None
    b = body.strip()
    if not b.lower().startswith("aesgcm://") or any(ch in b for ch in (" ", "\n", "\t")):
        return None
    name = b.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "datei"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"url": "/media/%d" % msg_id, "name": name,
            "kind": "image" if ext in _MEDIA_IMG_EXT else "file"}


def _media_label(body):
    info = _media_info(body, 0)
    if not info:
        return None
    return "[Bild]" if info["kind"] == "image" else "[Anhang]"


def _preview(last_body, last_dir, last_dec):
    if not last_dec:
        text = "Verschluesselte Nachricht"
    else:
        text = _media_label(last_body) or ((last_body or "").replace("\n", " ").strip() or "(leer)")
    if len(text) > 60:
        text = text[:60] + "…"
    return ("Du: " + text) if last_dir == "out" else text


# Letzte N Nachrichten einer Konversation (chronologisch) fuer die Rasterkachel.
def _recent(conn, partner, n=8):
    rows = conn.execute(
        "SELECT direction, body, decrypted, sender FROM messages "
        "WHERE partner_jid = ? AND " + _nonempty() + " ORDER BY id DESC LIMIT ?",
        (partner, n),
    ).fetchall()
    out = []
    for r in reversed(rows):
        if r["decrypted"]:
            text = _media_label(r["body"]) or ((r["body"] or "").replace("\n", " ").strip() or "(leer)")
        else:
            text = "[verschluesselt]"
        if len(text) > 240:
            text = text[:240] + "…"
        if r["direction"] == "out":
            text = "Du: " + text
        elif r["sender"]:
            text = r["sender"] + ": " + text
        out.append({"direction": r["direction"], "text": text})
    return out


def _conv_items(db_path):
    conn = _open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT m.partner_jid AS partner, COUNT(*) AS cnt, MAX(m.ts_received) AS last_ts, "
            "  SUM(CASE WHEN m.decrypted = 0 THEN 1 ELSE 0 END) AS undecrypted, "
            "  SUM(CASE WHEN m.direction = 'in' AND m.ts_received > "
            "      COALESCE((SELECT last_read_ts FROM read_state r WHERE r.partner_jid = m.partner_jid), 0) "
            "    THEN 1 ELSE 0 END) AS unread, "
            "  (SELECT body FROM messages x WHERE x.partner_jid = m.partner_jid AND " + _nonempty("x.") + " ORDER BY x.id DESC LIMIT 1) AS last_body, "
            "  (SELECT direction FROM messages x WHERE x.partner_jid = m.partner_jid AND " + _nonempty("x.") + " ORDER BY x.id DESC LIMIT 1) AS last_dir, "
            "  (SELECT decrypted FROM messages x WHERE x.partner_jid = m.partner_jid AND " + _nonempty("x.") + " ORDER BY x.id DESC LIMIT 1) AS last_dec, "
            "  (SELECT name FROM contacts c WHERE c.jid = m.partner_jid) AS contact_name, "
            "  (SELECT name FROM muc_available a WHERE a.room_jid = m.partner_jid) AS room_name, "
            "  EXISTS(SELECT 1 FROM mucs g WHERE g.room_jid = m.partner_jid) AS is_room "
            "FROM messages m WHERE " + _nonempty("m.") + " GROUP BY m.partner_jid ORDER BY last_ts DESC"
        ).fetchall()
        items = []
        for r in rows:
            is_room = bool(r["is_room"])
            name = r["contact_name"] or r["room_name"] or r["partner"]
            items.append({
                "partner": r["partner"], "name": name, "count": r["cnt"], "last": _fmt_ts(r["last_ts"]),
                "last_ts": r["last_ts"],
                "undecrypted": r["undecrypted"], "unread": r["unread"], "is_room": is_room,
                "preview": _preview(r["last_body"], r["last_dir"], r["last_dec"]),
                "initials": _initials(name if name != r["partner"] else "", r["partner"]),
                "hue": _hue(r["partner"]),
                "recent": _recent(conn, r["partner"]),
            })
    finally:
        conn.close()
    return items


def _is_room(conn, jid):
    row = conn.execute(
        "SELECT 1 FROM mucs WHERE room_jid = ? UNION SELECT 1 FROM muc_available WHERE room_jid = ?",
        (jid, jid),
    ).fetchone()
    return row is not None


# Trennt fuehrende Zitatzeilen (">") vom eigentlichen Text (Antwort-Funktion).
def _split_quote(body):
    if not body:
        return None, body
    lines = body.split("\n")
    i, qlines = 0, []
    while i < len(lines) and lines[i].startswith(">"):
        qlines.append(lines[i][1:].lstrip())
        i += 1
    if not qlines:
        return None, body
    return "\n".join(qlines), "\n".join(lines[i:]).lstrip("\n")


def _msg_dict(r):
    quote, text = _split_quote(r["body"])
    media = _media_info(r["body"], r["id"]) if r["decrypted"] else None
    if media:
        # Anhang ersetzt den (sonst als Rohtext sichtbaren) aesgcm-Link.
        quote, text = None, ""
    return {"id": r["id"], "direction": r["direction"], "body": r["body"],
            "quote": quote, "text": text, "media": media,
            "decrypted": bool(r["decrypted"]), "ts": _fmt_ts(r["ts_received"]),
            "ts_raw": r["ts_received"], "sender": r["sender"], "status": r["status"]}


# Inkrementell: neue Nachrichten nach einer id (Live-Aktualisierung).
def _messages(db_path, partner, after_id=0):
    conn = _open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT id, direction, body, decrypted, ts_received, sender, status FROM messages "
            "WHERE partner_jid = ? AND id > ? AND " + _nonempty() + " ORDER BY id ASC",
            (partner, after_id),
        ).fetchall()
    finally:
        conn.close()
    return [_msg_dict(r) for r in rows]


# Seitenweises Laden (Keyset nach (ts, id)): die letzte Seite oder aeltere davor.
# Rueckgabe: (Nachrichten chronologisch, has_more = es gibt noch aeltere lokal).
def _messages_page(db_path, partner, before_ts=None, before_id=None, limit=50):
    conn = _open_ro(db_path)
    try:
        if before_ts is None:
            rows = conn.execute(
                "SELECT id, direction, body, decrypted, ts_received, sender, status FROM messages "
                "WHERE partner_jid = ? AND " + _nonempty() + " ORDER BY ts_received DESC, id DESC LIMIT ?",
                (partner, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, direction, body, decrypted, ts_received, sender, status FROM messages "
                "WHERE partner_jid = ? AND (ts_received < ? OR (ts_received = ? AND id < ?)) "
                "AND " + _nonempty() + " ORDER BY ts_received DESC, id DESC LIMIT ?",
                (partner, before_ts, before_ts, before_id, limit),
            ).fetchall()
    finally:
        conn.close()
    has_more = len(rows) == limit
    return [_msg_dict(r) for r in reversed(rows)], has_more


def _pending(db_path, partner):
    conn = _open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT id, body, status, error FROM outbox WHERE recipient_jid = ? AND status IN ('pending','error') ORDER BY id",
            (partner,),
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "body": r["body"], "status": r["status"], "error": r["error"]} for r in rows]


def _mark_read(db_path, partner):
    conn = _open_rw(db_path)
    try:
        conn.execute(
            "INSERT INTO read_state (partner_jid, last_read_ts) VALUES (?, ?) "
            "ON CONFLICT(partner_jid) DO UPDATE SET last_read_ts = excluded.last_read_ts",
            (partner, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


# --- Login / Logout ---------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = "", deleted: str = ""):
    if request.session.get("jid"):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    pending = request.session.get("pending")
    return _env.get_template("login.html").render(
        default_server=_xmpp.get("default_host", ""), error=error, deleted=bool(deleted),
        waiting=bool(pending), pending_jid=pending or "",
    )


@app.post("/login")
def login(request: Request, jid: str = Form(...), password: str = Form(...), server: str = Form("")):
    jid = (jid or "").strip()
    server = (server or "").strip() or _xmpp.get("default_host", "")
    host, port = server, _xmpp.get("default_port", 5222)
    if ":" in server:
        host, _, p = server.partition(":")
        port = int(p) if p.isdigit() else port
    if not jid or not password:
        return RedirectResponse(url="/login?error=1", status_code=status.HTTP_303_SEE_OTHER)

    # Schnellpfad: bereits validierter, aktiver Account mit unveraendertem Passwort.
    if _registry.verified_match(jid, password):
        request.session.pop("pending", None)
        request.session["jid"] = jid
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Schutz: Ist der Account aktiv und validiert, aber das Passwort stimmt nicht,
    # wird abgelehnt OHNE die laufende Verbindung/das gespeicherte Passwort zu aendern
    # (verhindert, dass ein falscher Login einen aktiven Account stoert).
    if _registry.is_ok(jid):
        return RedirectResponse(url="/login?error=1", status_code=status.HTTP_303_SEE_OTHER)

    # Sonst (neuer Account, oder zuvor fehlgeschlagen/deaktiviert): anlegen/aktualisieren;
    # der Daemon-Manager validiert ueber die echte XMPP-Verbindung (kein Connect aus dem Web).
    local = jid.split("@")[0]
    # MUC-Nick = reiner Username. Der Archivierer ist nur eine weitere Ressource
    # desselben Accounts; der Server erlaubt Multi-Session mit gleichem Nick, daher
    # kein Konflikt mit den anderen Geraeten des Nutzers (kein "-web"-Suffix noetig).
    _registry.upsert(jid, password, host=host, port=port,
                     resource=_xmpp.get("resource", "archiver"), muc_nick=local)
    _ensure_db(_registry.archive_path(jid))
    request.session.pop("jid", None)
    request.session["pending"] = jid
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


# Pollt den Validierungsstatus des laufenden Logins (vom Manager gesetzt).
@app.get("/api/login_status")
def login_status(request: Request):
    jid = request.session.get("pending")
    if not jid:
        return {"status": "ok"} if request.session.get("jid") else {"status": "none"}
    state = _registry.get_auth_state(jid)
    if state == "ok":
        request.session.pop("pending", None)
        request.session["jid"] = jid
        return {"status": "ok"}
    if state == "failed":
        request.session.pop("pending", None)
        return {"status": "failed"}
    return {"status": "pending"}


@app.post("/logout")
def logout(request: Request):
    # Nur die Session beenden; die Hintergrund-Archivierung laeuft weiter.
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


# Bestaetigungsseite fuer die Account-Loeschung ("Willst du das wirklich?").
@app.get("/settings/delete", response_class=HTMLResponse)
def delete_account_confirm(acc: dict = Depends(require_account)):
    return _env.get_template("delete_account.html").render(
        nav_active="", account_jid=acc["jid"], account_state=_account_state(acc["jid"]),
    )


# Loescht den eigenen Account und alle gespeicherten Daten auf diesem Server.
# Die Web-UI merkt die Loeschung nur vor; der Daemon-Manager trennt die Verbindung
# und entfernt das Account-Verzeichnis (kein offener DB-Zugriff). Danach Abmeldung.
@app.post("/settings/delete")
def delete_account(request: Request, acc: dict = Depends(require_account)):
    _registry.request_deletion(acc["jid"])
    request.session.clear()
    return RedirectResponse(url="/login?deleted=1", status_code=status.HTTP_303_SEE_OTHER)


# --- Web Push ---------------------------------------------------------------

# Service Worker im Wurzel-Scope ausliefern (steuert die ganze App).
@app.get("/sw.js")
def service_worker():
    with open(os.path.join(_static_dir, "sw.js"), "rb") as f:
        data = f.read()
    return Response(content=data, media_type="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/api/push/config")
def push_config(acc: dict = Depends(require_account)):
    return {"enabled": _PUSH_ENABLED, "publicKey": _PUSH_PUBLIC}


# Geraete-Abo des Browsers speichern (Endpoint + Schluessel).
@app.post("/api/push/subscribe")
async def push_subscribe(request: Request, acc: dict = Depends(require_account)):
    sub = await request.json()
    endpoint = (sub or {}).get("endpoint")
    keys = (sub or {}).get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not (endpoint and p256dh and auth):
        raise HTTPException(status_code=400)
    conn = _open_rw(acc["archive_path"])
    try:
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_ts) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
            (endpoint, p256dh, auth, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.get("/api/push/pref/{partner:path}")
def push_pref_get(partner: str, acc: dict = Depends(require_account)):
    conn = _open_ro(acc["archive_path"])
    try:
        row = conn.execute("SELECT enabled FROM push_prefs WHERE partner_jid = ?", (partner,)).fetchone()
        subs = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
    finally:
        conn.close()
    return {"enabled": bool(row and row["enabled"]), "subscribed": bool(subs), "push": _PUSH_ENABLED}


@app.post("/api/push/pref/{partner:path}")
def push_pref_set(partner: str, value: str = Form(...), acc: dict = Depends(require_account)):
    conn = _open_rw(acc["archive_path"])
    try:
        conn.execute(
            "INSERT INTO push_prefs (partner_jid, enabled) VALUES (?, ?) "
            "ON CONFLICT(partner_jid) DO UPDATE SET enabled = excluded.enabled",
            (partner, 1 if value == "1" else 0),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# Schaltet "immer online" fuer den eigenen Account um (enabled-Flag).
# enabled=0 -> der Manager trennt die Verbindung (keine Archivierung mehr),
# enabled=1 -> der Manager verbindet wieder.
@app.post("/account/online")
def account_online(request: Request, value: str = Form(...), acc: dict = Depends(require_account)):
    _registry.set_enabled(acc["jid"], value == "1")
    back = request.headers.get("referer") or "/"
    return RedirectResponse(url=back, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/api/account_status")
def account_status(acc: dict = Depends(require_account)):
    return _account_state(acc["jid"])


# --- Chats ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def conversations(acc: dict = Depends(require_account)):
    return _env.get_template("conversations.html").render(
        items=_conv_items(acc["archive_path"]), nav_active="archiv", account_jid=acc["jid"],
        account_state=_account_state(acc["jid"]),
    )


@app.get("/api/conversations")
def api_conversations(acc: dict = Depends(require_account)):
    return _conv_items(acc["archive_path"])


@app.get("/search", response_class=HTMLResponse)
def search(q: str = "", acc: dict = Depends(require_account)):
    q = (q or "").strip()
    results = _search(acc["archive_path"], q) if len(q) >= 2 else []
    return _env.get_template("search.html").render(
        q=q, results=results, nav_active="", account_jid=acc["jid"],
        account_state=_account_state(acc["jid"]),
    )


@app.get("/c/{partner:path}", response_class=HTMLResponse)
def conversation(partner: str, acc: dict = Depends(require_account)):
    db_path = acc["archive_path"]
    conn = _open_ro(db_path)
    try:
        is_room = _is_room(conn, partner)
        row = conn.execute("SELECT name FROM contacts WHERE jid = ?", (partner,)).fetchone()
        contact_name = row["name"] if row else None
        rrow = conn.execute("SELECT name FROM muc_available WHERE room_jid = ?", (partner,)).fetchone()
        room_name = rrow["name"] if rrow else None
    finally:
        conn.close()
    name = (room_name if is_room else contact_name) or partner
    # Nur die letzte Seite laden (Robustheit bei sehr langen Verlaeufen wie 'noc').
    messages, has_more = _messages_page(db_path, partner)
    max_id = max((m["id"] for m in messages), default=0)
    oldest = messages[0] if messages else None
    _mark_read(db_path, partner)
    return _env.get_template("conversation.html").render(
        partner=partner, name=name, messages=messages, max_id=max_id, pending=_pending(db_path, partner),
        oldest_ts=(oldest["ts_raw"] if oldest else 0), oldest_id=(oldest["id"] if oldest else 0),
        has_more=has_more, is_room=is_room, initials=_initials(name if name != partner else "", partner),
        hue=_hue(partner), nav_active="archiv", account_jid=acc["jid"],
        account_state=_account_state(acc["jid"]), push_enabled=_PUSH_ENABLED,
    )


# Aeltere Nachrichten aus dem lokalen Archiv (Paginierung, Keyset vor dem Cursor).
@app.get("/api/older/{partner:path}")
def api_older(partner: str, before_ts: float = 0, before_id: int = 0, acc: dict = Depends(require_account)):
    msgs, has_more = _messages_page(acc["archive_path"], partner,
                                    before_ts=before_ts if before_ts else None, before_id=before_id)
    return {"messages": msgs, "has_more": has_more}


@app.get("/api/messages/{partner:path}")
def api_messages(partner: str, after_id: int = 0, acc: dict = Depends(require_account)):
    db_path = acc["archive_path"]
    msgs = _messages(db_path, partner, after_id)
    if msgs:
        _mark_read(db_path, partner)
    return {"messages": msgs, "pending": _pending(db_path, partner)}


def _account_domain(jid):
    return jid.split("@", 1)[1].lower() if "@" in jid else ""


# Laedt die verschluesselte Datei vom HTTP-Upload-Server und entschluesselt sie
# (AES-256-GCM). Schluessel+IV stammen aus dem URL-Fragment, der GCM-Tag haengt
# (von cryptography erwartet) am Ciphertext.
def _media_fetch_decrypt(body, allowed_domain):
    u = urlparse(body.strip())
    if u.scheme != "aesgcm" or not u.fragment or not u.netloc:
        raise HTTPException(status_code=404)
    host = (u.hostname or "").lower()
    # SSRF-Schutz: ausschliesslich von der eigenen XMPP-Domain laden.
    if not allowed_domain or not (host == allowed_domain or host.endswith("." + allowed_domain)):
        raise HTTPException(status_code=403)
    try:
        raw = bytes.fromhex(u.fragment)
    except ValueError:
        raise HTTPException(status_code=404)
    if len(raw) < 33:  # mind. 1 Byte IV + 32 Byte Key
        raise HTTPException(status_code=404)
    key, iv = raw[-32:], raw[:-32]
    https = "https://%s%s" % (u.netloc, u.path)
    try:
        req = urllib.request.Request(https, headers={"User-Agent": "x-gate-chat"})
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as resp:
            data = resp.read(_MEDIA_MAX + 1)
    except Exception:
        raise HTTPException(status_code=502)
    if len(data) > _MEDIA_MAX:
        raise HTTPException(status_code=413)
    try:
        plain = AESGCM(key).decrypt(iv, data, None)
    except Exception:
        raise HTTPException(status_code=502)
    ext = u.path.rsplit(".", 1)[-1].lower() if "." in u.path else ""
    return plain, _MEDIA_CT.get(ext, "application/octet-stream")


# Entschluesselter Media-Proxy: liest den Body der eigenen Nachricht (Auth ueber Session),
# holt die verschluesselte Datei und liefert den Klartext aus. Schluessel bleiben serverseitig.
@app.get("/media/{msg_id:int}")
def media(msg_id: int, acc: dict = Depends(require_account)):
    conn = _open_ro(acc["archive_path"])
    try:
        row = conn.execute("SELECT body, decrypted FROM messages WHERE id = ?", (msg_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row["decrypted"] or not row["body"]:
        raise HTTPException(status_code=404)
    data, ctype = _media_fetch_decrypt(row["body"], _account_domain(acc["jid"]))
    return Response(content=data, media_type=ctype, headers={
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    })


# Spool-Verzeichnis je Account fuer zu sendende Anhaenge (Daemon liest + loescht).
def _account_spool_dir(archive_path):
    d = os.path.join(os.path.dirname(archive_path), "spool")
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


@app.post("/c/{partner:path}/send")
def send_message(partner: str, body: str = Form(""), quote: str = Form(""),
                 file: UploadFile = File(None), acc: dict = Depends(require_account)):
    db = acc["archive_path"]
    text = (body or "").strip()
    quote = (quote or "").strip()

    # Anhang: nur fuer 1:1 (OMEMO-Media). In Raeumen (unverschluesselt) nicht unterstuetzt.
    if file is not None and (file.filename or ""):
        conn = _open_ro(db)
        try:
            is_room = _is_room(conn, partner)
        finally:
            conn.close()
        data = file.file.read(_MEDIA_MAX + 1)
        if not is_room and data and len(data) <= _MEDIA_MAX:
            spool = _account_spool_dir(db)
            name = os.path.basename(file.filename) or "datei"
            path = os.path.join(spool, uuid.uuid4().hex + os.path.splitext(name)[1])
            with open(path, "wb") as out:
                out.write(data)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            conn = _open_rw(db)
            try:
                conn.execute(
                    "INSERT INTO outbox (recipient_jid, body, status, created_ts, kind, "
                    "media_path, media_name, media_mime) VALUES (?, ?, 'pending', ?, 'media', ?, ?, ?)",
                    (partner, name, time.time(), path, name, file.content_type or "application/octet-stream"),
                )
                conn.commit()
            finally:
                conn.close()

    if text and quote:
        # Zitat als "> "-Zeilen voranstellen (von jedem Client verstanden).
        text = "\n".join("> " + ln for ln in quote.split("\n")) + "\n" + text
    if text:
        conn = _open_rw(db)
        try:
            kind = "groupchat" if _is_room(conn, partner) else "chat"
            conn.execute(
                "INSERT INTO outbox (recipient_jid, body, status, created_ts, kind) VALUES (?, ?, 'pending', ?, ?)",
                (partner, text, time.time(), kind),
            )
            conn.commit()
        finally:
            conn.close()
    return RedirectResponse(url=f"/c/{partner}", status_code=status.HTTP_303_SEE_OTHER)


# Verwirft einen fehlgeschlagenen Sendeauftrag (entfernt nur 'error'-Zeilen).
@app.post("/c/{partner:path}/dismiss/{outbox_id:int}")
def dismiss_failed(partner: str, outbox_id: int, acc: dict = Depends(require_account)):
    conn = _open_rw(acc["archive_path"])
    try:
        conn.execute(
            "DELETE FROM outbox WHERE id = ? AND recipient_jid = ? AND status = 'error'",
            (outbox_id, partner),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/c/{partner}", status_code=status.HTTP_303_SEE_OTHER)


# --- OMEMO-Geraete / Verifizierung ------------------------------------------

def _devices(db_path, partner):
    conn = _open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT jid, device_id, fingerprint, identity_hex, trust, is_own, label FROM omemo_devices "
            "WHERE jid = ? OR is_own = 1 ORDER BY is_own DESC, device_id",
            (partner,),
        ).fetchall()
    finally:
        conn.close()
    return [{"jid": r["jid"], "device_id": r["device_id"], "fingerprint": r["fingerprint"],
             "identity_hex": r["identity_hex"], "trust": r["trust"], "is_own": bool(r["is_own"]),
             "label": r["label"]} for r in rows]


def _omemo_request_row(db_path, action, jid, identity_hex=None, trust_value=None):
    conn = _open_rw(db_path)
    try:
        conn.execute(
            "INSERT INTO omemo_requests (action, jid, identity_hex, trust_value, status, created_ts) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (action, jid, identity_hex, trust_value, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


@app.get("/devices/{partner:path}", response_class=HTMLResponse)
def devices(partner: str, acc: dict = Depends(require_account)):
    _omemo_request_row(acc["archive_path"], "refresh", partner)  # frische Daten anstossen
    return _env.get_template("devices.html").render(
        partner=partner, nav_active="", account_jid=acc["jid"], account_state=_account_state(acc["jid"]),
    )


@app.get("/api/devices/{partner:path}")
def api_devices(partner: str, acc: dict = Depends(require_account)):
    return _devices(acc["archive_path"], partner)


@app.post("/devices/{partner:path}/trust")
def devices_trust(partner: str, identity_hex: str = Form(...), value: str = Form(...),
                  acc: dict = Depends(require_account)):
    if value in ("verify", "distrust") and identity_hex:
        _omemo_request_row(acc["archive_path"], "trust", partner, identity_hex=identity_hex, trust_value=value)
    return JSONResponse({"ok": True})


# Fordert das Nachladen aelterer Nachrichten (MAM) fuer diese Konversation/diesen Raum an.
@app.post("/c/{partner:path}/loadmore")
def load_more(partner: str, acc: dict = Depends(require_account)):
    conn = _open_rw(acc["archive_path"])
    try:
        kind = "muc" if _is_room(conn, partner) else "chat"
        conn.execute(
            "INSERT INTO mam_requests (target_jid, kind, status, created_ts) VALUES (?, ?, 'pending', ?)",
            (partner, kind, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/c/{partner}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/new")
def new_conversation(partner: str = Form(...), acc: dict = Depends(require_account)):
    target = (partner or "").strip()
    if not target:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=f"/c/{target}", status_code=status.HTTP_303_SEE_OTHER)


# --- Kontakte ---------------------------------------------------------------

@app.get("/contacts", response_class=HTMLResponse)
def contacts(acc: dict = Depends(require_account)):
    conn = _open_ro(acc["archive_path"])
    try:
        rows = conn.execute(
            "SELECT jid, name FROM contacts ORDER BY (name = '' OR name IS NULL), LOWER(name), jid"
        ).fetchall()
    finally:
        conn.close()
    items = [{"jid": r["jid"], "name": r["name"] or r["jid"],
              "initials": _initials(r["name"], r["jid"]), "hue": _hue(r["jid"])} for r in rows]
    return _env.get_template("contacts.html").render(
        items=items, nav_active="kontakte", account_jid=acc["jid"], account_state=_account_state(acc["jid"])
    )


# --- Raeume -----------------------------------------------------------------

@app.get("/rooms", response_class=HTMLResponse)
def rooms(acc: dict = Depends(require_account)):
    conn = _open_ro(acc["archive_path"])
    try:
        joined = conn.execute(
            "SELECT room_jid, name FROM mucs WHERE joined = 1 ORDER BY LOWER(COALESCE(name, room_jid))"
        ).fetchall()
        joined_set = {r["room_jid"] for r in joined}
        available = conn.execute(
            "SELECT room_jid, name FROM muc_available ORDER BY LOWER(COALESCE(name, room_jid))"
        ).fetchall()
    finally:
        conn.close()
    joined_items = [{"jid": r["room_jid"], "name": r["name"] or r["room_jid"],
                     "initials": _initials(r["name"], r["room_jid"]), "hue": _hue(r["room_jid"])} for r in joined]
    avail_items = [
        {"jid": r["room_jid"], "name": r["name"] or r["room_jid"], "joined": r["room_jid"] in joined_set,
         "initials": _initials(r["name"], r["room_jid"]), "hue": _hue(r["room_jid"])}
        for r in available
    ]
    return _env.get_template("rooms.html").render(
        joined=joined_items, available=avail_items, nav_active="raeume", account_jid=acc["jid"],
        account_state=_account_state(acc["jid"]),
    )


@app.post("/rooms/join")
def join_room(room_jid: str = Form(...), acc: dict = Depends(require_account)):
    target = (room_jid or "").strip()
    if target:
        conn = _open_rw(acc["archive_path"])
        try:
            name = None
            row = conn.execute("SELECT name FROM muc_available WHERE room_jid = ?", (target,)).fetchone()
            if row:
                name = row[0]
            conn.execute(
                "INSERT INTO mucs (room_jid, name, nick, joined) VALUES (?, ?, NULL, 1) "
                "ON CONFLICT(room_jid) DO UPDATE SET joined = 1",
                (target, name),
            )
            conn.commit()
        finally:
            conn.close()
    return RedirectResponse(url=f"/c/{target}", status_code=status.HTTP_303_SEE_OTHER)
