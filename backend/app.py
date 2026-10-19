"""XiaoBaWang V0.2 local control plane. No message-send capability."""
import base64
import hmac
import io
import os
import re
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from integrations.chatwoot.adapter import available, get_collection, validate_webhook

ROOT = Path(__file__).resolve().parent

@contextmanager
def db_connection():
    file_path = Path(os.getenv("XBW_DB_PATH", "./data/xiaobawang.sqlite3"))
    file_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(file_path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        with con:
            yield con
    finally:
        con.close()

def init_db():
    with db_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS chatwoot_events (
            delivery_key TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            conversation_id TEXT, message_id TEXT,
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_account TEXT NOT NULL, tg_chat_id TEXT NOT NULL,
            wa_session TEXT NOT NULL, wa_group_jid TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tg_account, tg_chat_id, wa_session, wa_group_jid)
        );
        CREATE TABLE IF NOT EXISTS source_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_account TEXT NOT NULL, tg_chat_id TEXT NOT NULL,
            tg_message_id TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tg_account, tg_chat_id, tg_message_id)
        );
        CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_event_id INTEGER NOT NULL REFERENCES source_events(id),
            rule_id INTEGER NOT NULL REFERENCES rules(id),
            wa_session TEXT NOT NULL, wa_group_jid TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_review',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_event_id, rule_id)
        );
        """)

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield

app = FastAPI(title="小霸王 XiaoBaWang", version="0.2.0", lifespan=lifespan)

def _check(value, setting):
    expected = os.getenv(setting, "")
    if not expected or not value or not hmac.compare_digest(expected, value):
        raise HTTPException(401, "Invalid service credentials")

def admin(x_api_key: str | None = Header(default=None)):
    _check(x_api_key, "XBW_API_KEY")

def telegram_worker(x_tg_key: str | None = Header(default=None)):
    _check(x_tg_key, "XBW_TG_KEY")

ACCOUNT = r"^[A-Za-z0-9_-]{1,64}$"
CHAT = r"^-?[0-9]{1,30}$"
WA_GROUP = r"^[0-9-]+@g\.us$"

class NewRule(BaseModel):
    tg_account: str = Field(pattern=ACCOUNT)
    tg_chat_id: str = Field(pattern=CHAT)
    wa_session: str = Field(pattern=ACCOUNT)
    wa_group_jid: str = Field(pattern=WA_GROUP)

class ChangeRule(BaseModel):
    enabled: bool

class IncomingEvent(BaseModel):
    tg_account: str = Field(pattern=ACCOUNT)
    tg_chat_id: str = Field(pattern=CHAT)
    tg_message_id: str = Field(pattern=r"^[0-9]{1,40}$")
    text: str = Field(min_length=1, max_length=8000)

def _alias(value):
    if not re.fullmatch(ACCOUNT, value):
        raise HTTPException(422, "Invalid account alias")
    return value

@app.get("/", response_class=HTMLResponse)
def homepage():
    return (ROOT / "chat.html").read_text(encoding="utf-8")

@app.get("/settings", response_class=HTMLResponse)
def advanced_settings():
    return (ROOT / "index.html").read_text(encoding="utf-8")

@app.get("/health")
def health():
    return {"product": "XiaoBaWang", "version": "0.2.0",
            "mode": "simulation_only", "real_sending": False}

@app.get("/api/config", dependencies=[Depends(admin)])
def config():
    return {"mode": "simulation_only", "real_sending": False,
            "chatwoot_url": os.getenv("CHATWOOT_URL", ""),
            "max_active_wa": 7}

@app.get("/api/routes", dependencies=[Depends(admin)])
def list_routes():
    with db_connection() as db:
        return [dict(x) for x in db.execute("SELECT * FROM rules ORDER BY id DESC")]

@app.post("/api/routes", dependencies=[Depends(admin)], status_code=201)
def create_route(new: NewRule):
    try:
        with db_connection() as db:
            row = db.execute(
                "INSERT INTO rules (tg_account,tg_chat_id,wa_session,wa_group_jid) VALUES (?,?,?,?)",
                (new.tg_account, new.tg_chat_id, new.wa_session, new.wa_group_jid)
            )
            return {"id": row.lastrowid, "enabled": False}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Rule already exists") from exc

@app.patch("/api/routes/{rule_id}", dependencies=[Depends(admin)])
def update_route(rule_id: int, patch: ChangeRule):
    with db_connection() as db:
        updated = db.execute("UPDATE rules SET enabled=? WHERE id=?",
                             (int(patch.enabled), rule_id))
        if updated.rowcount == 0:
            raise HTTPException(404, "Route not found")
    return {"id": rule_id, "enabled": patch.enabled}

@app.get("/api/telegram/allowed/{alias}", dependencies=[Depends(telegram_worker)])
def telegram_allowed(alias: str):
    _alias(alias)
    with db_connection() as db:
        chats = db.execute(
            "SELECT DISTINCT tg_chat_id FROM rules WHERE enabled=1 AND tg_account=?",
            (alias,)
        ).fetchall()
    return {"account": alias, "chat_ids": [x["tg_chat_id"] for x in chats]}

@app.post("/api/telegram/events", dependencies=[Depends(telegram_worker)])
def ingest_event(event: IncomingEvent):
    with db_connection() as db:
        matching = db.execute(
            "SELECT id,wa_session,wa_group_jid FROM rules WHERE enabled=1 AND tg_account=? AND tg_chat_id=?",
            (event.tg_account, event.tg_chat_id)
        ).fetchall()
        if not matching:
            return {"ignored": True, "created": 0, "duplicate": False}
        try:
            record = db.execute(
                "INSERT INTO source_events(tg_account,tg_chat_id,tg_message_id,text) VALUES (?,?,?,?)",
                (event.tg_account, event.tg_chat_id, event.tg_message_id, event.text)
            )
        except sqlite3.IntegrityError:
            return {"ignored": False, "created": 0, "duplicate": True}
        ids = []
        for rule in matching:
            saved = db.execute(
                "INSERT INTO deliveries(source_event_id,rule_id,wa_session,wa_group_jid) VALUES (?,?,?,?)",
                (record.lastrowid, rule["id"], rule["wa_session"], rule["wa_group_jid"])
            )
            ids.append(saved.lastrowid)
        return {"ignored": False, "created": len(ids), "duplicate": False, "delivery_ids": ids}

@app.get("/api/deliveries", dependencies=[Depends(admin)])
def deliveries():
    with db_connection() as db:
        query = """
            SELECT d.*, e.tg_account,e.tg_chat_id,e.tg_message_id,e.text,
                   r.enabled AS rule_enabled
            FROM deliveries d JOIN source_events e ON e.id=d.source_event_id
            JOIN rules r ON r.id=d.rule_id ORDER BY d.id DESC LIMIT 200
        """
        return [dict(x) for x in db.execute(query)]

def resolve_review(delivery_id: int, status: str):
    with db_connection() as db:
        existing = db.execute(
            "SELECT d.status, r.enabled FROM deliveries d JOIN rules r ON r.id=d.rule_id WHERE d.id=?",
            (delivery_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "Delivery not found")
        if existing["status"] != "pending_review":
            raise HTTPException(409, "Already reviewed")
        if status == "simulated" and not existing["enabled"]:
            raise HTTPException(409, "Route is paused")
        db.execute(
            "UPDATE deliveries SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending_review'",
            (status, delivery_id)
        )
    return {"id": delivery_id, "status": status, "network_sent": False}

@app.post("/api/deliveries/{delivery_id}/simulate", dependencies=[Depends(admin)])
def simulate(delivery_id: int):
    return resolve_review(delivery_id, "simulated")

@app.post("/api/deliveries/{delivery_id}/reject", dependencies=[Depends(admin)])
def reject(delivery_id: int):
    return resolve_review(delivery_id, "rejected")

def bridge(method: str, path: str):
    key = os.getenv("XBW_BRIDGE_KEY")
    if not key:
        raise HTTPException(503, "WhatsApp bridge not configured")
    base = os.getenv("XBW_BRIDGE_URL", "http://127.0.0.1:3101").rstrip("/")
    try:
        with httpx.Client(timeout=12) as client:
            response = client.request(method, base + path, headers={"X-Bridge-Key": key})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "WhatsApp bridge unavailable") from exc

@app.get("/api/whatsapp/sessions", dependencies=[Depends(admin)])
def wa_sessions():
    return bridge("GET", "/v1/sessions")

@app.post("/api/whatsapp/sessions/{alias}/connect", dependencies=[Depends(admin)])
def wa_connect(alias: str):
    return bridge("POST", "/v1/sessions/" + _alias(alias) + "/connect")

@app.get("/api/whatsapp/sessions/{alias}", dependencies=[Depends(admin)])
def wa_detail(alias: str):
    data = bridge("GET", "/v1/sessions/" + _alias(alias))
    raw_qr = data.pop("qr", None)
    if raw_qr:
        import qrcode
        output = io.BytesIO()
        qrcode.make(raw_qr).save(output, format="PNG")
        data["qr_data_uri"] = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return data

@app.get("/api/whatsapp/sessions/{alias}/groups", dependencies=[Depends(admin)])
def wa_groups(alias: str):
    return bridge("GET", "/v1/sessions/" + _alias(alias) + "/groups")

@app.get("/api/chatwoot/status", dependencies=[Depends(admin)])
def chatwoot_status():
    return {"configured": available(), "mode": "read_only_webhook_audit", "outbound_enabled": False}

@app.get("/api/chatwoot/{resource}", dependencies=[Depends(admin)])
def chatwoot_resource(resource: str):
    return get_collection(resource)

@app.post("/api/chatwoot/webhook")
async def chatwoot_webhook(request: Request,
                          x_chatwoot_signature: str | None = Header(default=None),
                          x_chatwoot_timestamp: str | None = Header(default=None),
                          x_chatwoot_delivery: str | None = Header(default=None)):
    raw = await request.body()
    digest = validate_webhook(raw, x_chatwoot_signature, x_chatwoot_timestamp)
    try:
        payload = __import__("json").loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid event")
    kind = str(payload.get("event", ""))[:80]
    if kind not in ("message_created", "conversation_created", "conversation_updated"):
        return {"ignored": True}
    conversation = payload.get("conversation", {}) or {}
    if not isinstance(conversation, dict):
        conversation = {}
    message = payload.get("message", {}) or {}
    if not isinstance(message, dict):
        message = {}
    delivery = (x_chatwoot_delivery or digest)[:200]
    with db_connection() as db:
        result = db.execute(
            "INSERT OR IGNORE INTO chatwoot_events(delivery_key,event_type,conversation_id,message_id) VALUES (?,?,?,?)",
            (delivery, kind, str(conversation.get("id", ""))[:80], str(message.get("id", ""))[:80])
        )
        return {"recorded": result.rowcount == 1, "duplicate": result.rowcount == 0, "network_sent": False}

@app.get("/api/chatwoot-events", dependencies=[Depends(admin)])
def chatwoot_events():
    with db_connection() as db:
        return [dict(row) for row in db.execute(
            "SELECT delivery_key,event_type,conversation_id,message_id,received_at FROM chatwoot_events ORDER BY received_at DESC LIMIT 100"
        )]

# Inbox-facing read-only APIs. Chat messages are not stored in the backend.
@app.get("/api/chat/whatsapp/{alias}/chats", dependencies=[Depends(admin)])
def whatsapp_chat_list(alias: str):
    return bridge("GET", "/v1/sessions/" + _alias(alias) + "/chats")

@app.get("/api/chat/whatsapp/{alias}/chats/{jid}/messages", dependencies=[Depends(admin)])
def whatsapp_chat_messages(alias: str, jid: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,90}@(g\.us|s\.whatsapp\.net|lid)", jid):
        raise HTTPException(422, "Invalid WhatsApp chat ID")
    return bridge("GET", "/v1/sessions/" + _alias(alias) + "/chats/" + quote(jid, safe="") + "/messages")

@app.get("/api/chat/telegram/threads", dependencies=[Depends(admin)])
def telegram_chat_list():
    with db_connection() as db:
        return [dict(row) for row in db.execute("""
            SELECT e.tg_account, e.tg_chat_id, e.text AS preview,
                   e.created_at AS last_time,
                   (SELECT COUNT(*) FROM source_events s
                    WHERE s.tg_account=e.tg_account AND s.tg_chat_id=e.tg_chat_id) AS observed_messages
            FROM source_events e
            WHERE e.id = (SELECT MAX(s2.id) FROM source_events s2
                          WHERE s2.tg_account=e.tg_account AND s2.tg_chat_id=e.tg_chat_id)
            ORDER BY e.id DESC LIMIT 300
        """)]

@app.get("/api/chat/telegram/{alias}/{chat_id}/messages", dependencies=[Depends(admin)])
def telegram_chat_messages(alias: str, chat_id: str):
    _alias(alias)
    if not re.fullmatch(CHAT, chat_id):
        raise HTTPException(422, "Invalid Telegram chat ID")
    with db_connection() as db:
        rows = db.execute("""
            SELECT id, tg_message_id, text, created_at
            FROM source_events WHERE tg_account=? AND tg_chat_id=?
            ORDER BY id DESC LIMIT 150
        """, (alias, chat_id)).fetchall()
        return {"messages": [dict(row) for row in reversed(rows)],
                "scope": "observed_after_route_enabled",
                "sending_enabled": False}
