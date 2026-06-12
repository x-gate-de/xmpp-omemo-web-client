# -----------------------------------------------------------------------------
# Skript: src/web/app.py
# Autor: Torben Belz
# Version: 1.2.0
# Lizenz: AGPL-3.0-or-later (siehe LICENSE)
# Zweck:
# - Web-UI: Archiv lesen, 1:1 (OMEMO) und Gruppen (MUC) senden, Kontakte und
#   oeffentliche Raeume anzeigen/beitreten, Live-Aktualisierung, Sende-Status.
# Ablauf:
# - Liest read-only; Sendeauftraege und Raum-Beitritte landen in DB-Tabellen,
#   die der Daemon abarbeitet. Pflicht-Login (HTTP Basic).
# Betriebs- und Wartungshinweise:
# - Zeigt entschluesselte private Nachrichten (Schutzbedarf HOCH).
# -----------------------------------------------------------------------------

import os
import secrets
import sqlite3
import time
from datetime import datetime

import jinja2
from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from src.config import load_config
from src.schema import ensure_schema

CONFIG_PATH = os.environ.get("OMEMO_WEB_CONFIG", "/opt/omemo-web/config.yaml")
config = load_config(CONFIG_PATH)

_web = config["web"]
_db_path = config["archive"]["db_path"]

if not _web.get("auth_user") or not _web.get("auth_password"):
    raise RuntimeError("web.auth_user und web.auth_password muessen in config.yaml gesetzt sein")

_init_conn = sqlite3.connect(_db_path)
ensure_schema(_init_conn)
_init_conn.close()

app = FastAPI(title="Chat", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
security = HTTPBasic()

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=True,
)


def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username, str(_web["auth_user"]))
    pass_ok = secrets.compare_digest(credentials.password, str(_web["auth_password"]))
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nicht autorisiert",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _open_ro():
    conn = sqlite3.connect(f"file:{_db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _open_rw():
    conn = sqlite3.connect(_db_path, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# Initialen fuer den Avatar aus Anzeigename bzw. JID-Localpart.
def _initials(name, jid):
    base = (name or "").strip() or (jid or "").split("@")[0]
    parts = [p for p in base.replace(".", " ").replace("_", " ").replace("-", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (base[:2] or "?").upper()


# Stabile Farbnuance (0-359) je Gespraechspartner fuer den Avatar.
def _hue(s):
    return sum(ord(c) for c in (s or "")) % 360


# Konversationen/Raeume mit Zaehlern fuer Liste und Polling.
def _conversation_rows():
    conn = _open_ro()
    try:
        return conn.execute(
            "SELECT m.partner_jid AS partner, COUNT(*) AS cnt, MAX(m.ts_received) AS last_ts, "
            "  SUM(CASE WHEN m.decrypted = 0 THEN 1 ELSE 0 END) AS undecrypted, "
            "  SUM(CASE WHEN m.direction = 'in' AND m.ts_received > "
            "      COALESCE((SELECT last_read_ts FROM read_state r WHERE r.partner_jid = m.partner_jid), 0) "
            "    THEN 1 ELSE 0 END) AS unread, "
            "  (SELECT body FROM messages x WHERE x.partner_jid = m.partner_jid ORDER BY x.id DESC LIMIT 1) AS last_body, "
            "  (SELECT direction FROM messages x WHERE x.partner_jid = m.partner_jid ORDER BY x.id DESC LIMIT 1) AS last_dir, "
            "  (SELECT decrypted FROM messages x WHERE x.partner_jid = m.partner_jid ORDER BY x.id DESC LIMIT 1) AS last_dec, "
            "  (SELECT name FROM contacts c WHERE c.jid = m.partner_jid) AS contact_name, "
            "  (SELECT name FROM muc_available a WHERE a.room_jid = m.partner_jid) AS room_name, "
            "  EXISTS(SELECT 1 FROM mucs g WHERE g.room_jid = m.partner_jid) AS is_room "
            "FROM messages m GROUP BY m.partner_jid ORDER BY last_ts DESC"
        ).fetchall()
    finally:
        conn.close()


# Kurze Vorschau der letzten Nachricht fuer die Liste.
def _preview(last_body, last_dir, last_dec):
    if not last_dec:
        text = "Verschluesselte Nachricht"
    else:
        text = (last_body or "").replace("\n", " ").strip() or "(leer)"
    if len(text) > 60:
        text = text[:60] + "…"
    return ("Du: " + text) if last_dir == "out" else text


def _conv_items():
    items = []
    for r in _conversation_rows():
        is_room = bool(r["is_room"])
        name = (r["contact_name"] or r["room_name"] or r["partner"]) if not is_room else (r["room_name"] or r["partner"])
        if not is_room and r["contact_name"]:
            name = r["contact_name"]
        items.append({
            "partner": r["partner"], "name": name, "count": r["cnt"], "last": _fmt_ts(r["last_ts"]),
            "undecrypted": r["undecrypted"], "unread": r["unread"], "is_room": is_room,
            "preview": _preview(r["last_body"], r["last_dir"], r["last_dec"]),
            "initials": _initials(name if name != r["partner"] else "", r["partner"]),
            "hue": _hue(r["partner"]),
        })
    return items


@app.get("/", response_class=HTMLResponse)
def conversations(_user: str = Depends(require_auth)):
    return _env.get_template("conversations.html").render(items=_conv_items(), nav_active="archiv")


@app.get("/api/conversations")
def api_conversations(_user: str = Depends(require_auth)):
    return _conv_items()


# Markiert ob eine JID ein Raum ist (fuer Anzeige und Sendeart).
def _is_room(conn, jid):
    row = conn.execute(
        "SELECT 1 FROM mucs WHERE room_jid = ? UNION SELECT 1 FROM muc_available WHERE room_jid = ?",
        (jid, jid),
    ).fetchone()
    return row is not None


def _messages(partner, after_id=0):
    conn = _open_ro()
    try:
        rows = conn.execute(
            "SELECT id, direction, body, decrypted, ts_received, sender, status FROM messages "
            "WHERE partner_jid = ? AND id > ? ORDER BY id ASC",
            (partner, after_id),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": r["id"], "direction": r["direction"], "body": r["body"],
         "decrypted": bool(r["decrypted"]), "ts": _fmt_ts(r["ts_received"]),
         "sender": r["sender"], "status": r["status"]}
        for r in rows
    ]


# Offene/fehlgeschlagene Sendeauftraege fuer die Anzeige als "wird gesendet"/"Fehler".
def _pending(partner):
    conn = _open_ro()
    try:
        rows = conn.execute(
            "SELECT body, status FROM outbox WHERE recipient_jid = ? AND status IN ('pending','error') ORDER BY id",
            (partner,),
        ).fetchall()
    finally:
        conn.close()
    return [{"body": r["body"], "status": r["status"]} for r in rows]


def _mark_read(partner):
    conn = _open_rw()
    try:
        conn.execute(
            "INSERT INTO read_state (partner_jid, last_read_ts) VALUES (?, ?) "
            "ON CONFLICT(partner_jid) DO UPDATE SET last_read_ts = excluded.last_read_ts",
            (partner, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


@app.get("/c/{partner:path}", response_class=HTMLResponse)
def conversation(partner: str, _user: str = Depends(require_auth)):
    conn = _open_ro()
    try:
        is_room = _is_room(conn, partner)
        row = conn.execute("SELECT name FROM contacts WHERE jid = ?", (partner,)).fetchone()
        contact_name = row["name"] if row else None
        rrow = conn.execute("SELECT name FROM muc_available WHERE room_jid = ?", (partner,)).fetchone()
        room_name = rrow["name"] if rrow else None
    finally:
        conn.close()
    name = (room_name if is_room else contact_name) or partner
    messages = _messages(partner)
    _mark_read(partner)
    return _env.get_template("conversation.html").render(
        partner=partner, name=name, messages=messages, pending=_pending(partner),
        is_room=is_room, initials=_initials(name if name != partner else "", partner),
        hue=_hue(partner), nav_active="archiv",
    )


@app.get("/api/messages/{partner:path}")
def api_messages(partner: str, after_id: int = 0, _user: str = Depends(require_auth)):
    msgs = _messages(partner, after_id)
    if msgs:
        _mark_read(partner)
    return {"messages": msgs, "pending": _pending(partner)}


# Legt einen Sendeauftrag ab; Art (1:1 OMEMO oder Gruppe) wird automatisch erkannt.
@app.post("/c/{partner:path}/send")
def send_message(partner: str, body: str = Form(...), _user: str = Depends(require_auth)):
    text = (body or "").strip()
    if text:
        conn = _open_rw()
        try:
            kind = "groupchat" if _is_room(conn, partner) else "chat"
            conn.execute(
                "INSERT INTO outbox (recipient_jid, body, status, created_ts, kind) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (partner, text, time.time(), kind),
            )
            conn.commit()
        finally:
            conn.close()
    return RedirectResponse(url=f"/c/{partner}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/new")
def new_conversation(partner: str = Form(...), _user: str = Depends(require_auth)):
    target = (partner or "").strip()
    if not target:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=f"/c/{target}", status_code=status.HTTP_303_SEE_OTHER)


# --- Kontakte (Roster) -----------------------------------------------------

@app.get("/contacts", response_class=HTMLResponse)
def contacts(_user: str = Depends(require_auth)):
    conn = _open_ro()
    try:
        rows = conn.execute(
            "SELECT jid, name FROM contacts ORDER BY (name = '' OR name IS NULL), LOWER(name), jid"
        ).fetchall()
    finally:
        conn.close()
    items = [{"jid": r["jid"], "name": r["name"] or r["jid"],
              "initials": _initials(r["name"], r["jid"]), "hue": _hue(r["jid"])} for r in rows]
    return _env.get_template("contacts.html").render(items=items, nav_active="kontakte")


# --- Oeffentliche Raeume (MUC) ---------------------------------------------

@app.get("/rooms", response_class=HTMLResponse)
def rooms(_user: str = Depends(require_auth)):
    conn = _open_ro()
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
    return _env.get_template("rooms.html").render(joined=joined_items, available=avail_items, nav_active="raeume")


@app.post("/rooms/join")
def join_room(room_jid: str = Form(...), _user: str = Depends(require_auth)):
    target = (room_jid or "").strip()
    if target:
        conn = _open_rw()
        try:
            name = None
            row = conn.execute("SELECT name FROM muc_available WHERE room_jid = ?", (target,)).fetchone()
            if row:
                name = row[0]
            # joined=1 -> der Daemon betritt den Raum beim naechsten Outbox-Durchlauf.
            conn.execute(
                "INSERT INTO mucs (room_jid, name, nick, joined) VALUES (?, ?, NULL, 1) "
                "ON CONFLICT(room_jid) DO UPDATE SET joined = 1",
                (target, name),
            )
            conn.commit()
        finally:
            conn.close()
    return RedirectResponse(url=f"/c/{target}", status_code=status.HTTP_303_SEE_OTHER)
