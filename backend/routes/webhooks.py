"""WuzAPI (whatsmeow) webhook receiver, reached via the zappzen-gateway.

The gateway is the only thing that should call this — it already validated
the WuzAPI HMAC signature once and forwards the same x-hmac-signature header
unchanged (payload bytes are identical), so we re-check it here too rather
than trust the network blindly. It also durably queues + retries delivery
with backoff, so we don't need our own retry here — just process fast and
return 200.

Routing is normally per-connection by URL (/wuzapi/{tenant_id}/{connection_id}),
set when the connection is created (see whatsapp.py's _webhook_url()). In
practice WuzAPI has also been observed delivering real incoming-message
events to the gateway's plain /webhook route even when the per-connection
URL is configured, so /wuzapi (no path params) exists as a fallback that
resolves tenant/connection from the payload's `userID` field instead.
"""
import hmac
import hashlib
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from db import get_db
from flow_runtime import handle_incoming_message

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _validate_hmac(body: bytes, request: Request):
    key = os.environ.get("WUZAPI_GLOBAL_HMAC_KEY")
    if not key:
        return
    provided = request.headers.get("x-hmac-signature", "")
    expected = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")


@router.post("/wuzapi")
async def wuzapi_webhook_unrouted(request: Request, bg: BackgroundTasks):
    """Some WuzAPI events (observed for real incoming 'Message' events, even
    when a per-connection webhook URL is configured) get delivered to the
    gateway's plain /webhook route instead of /webhook/{tenant_id}/{connection_id}
    — so they arrive here with no IDs in the URL. WuzAPI does stamp every
    payload with `userID`, which is exactly the `wuzapi_user_id` we store per
    connection at creation time, so we resolve tenant/connection from that
    instead of trusting the URL."""
    body = await request.body()
    _validate_hmac(body, request)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    db = get_db()
    conn = await db.whatsapp_connections.find_one({"wuzapi_user_id": payload.get("userID")})
    if not conn:
        # Unknown/stale instance (e.g. a connection created outside this
        # backend, or already deleted) — ack anyway so WuzAPI/gateway don't
        # keep retrying something that will never resolve.
        return {"ok": True, "ignored": "unknown userID"}

    return await _process_webhook_event(conn["tenant_id"], conn["id"], payload, db, bg)


@router.post("/wuzapi/{tenant_id}/{connection_id}")
async def wuzapi_webhook(tenant_id: str, connection_id: str, request: Request, bg: BackgroundTasks):
    body = await request.body()
    _validate_hmac(body, request)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    db = get_db()
    conn = await db.whatsapp_connections.find_one({"id": connection_id, "tenant_id": tenant_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")

    return await _process_webhook_event(tenant_id, connection_id, payload, db, bg)


async def _process_webhook_event(tenant_id: str, connection_id: str, payload: dict, db, bg: BackgroundTasks):
    await db.whatsapp_connections.update_one(
        {"id": connection_id}, {"$set": {"last_webhook_event_at": _now()}}
    )

    etype = payload.get("type", "")
    event = payload.get("event") or {}

    if etype == "QR":
        b64 = payload.get("qrCodeBase64")
        if b64:
            await db.whatsapp_connections.update_one(
                {"id": connection_id},
                {"$set": {"qrcode_atual": b64, "status": "pareando", "updated_at": _now()}},
            )
        return {"ok": True}

    if etype == "PairSuccess":
        raw_id = event.get("ID", "")
        numero = raw_id.split(":")[0].split("@")[0] if raw_id else None
        await db.whatsapp_connections.update_one(
            {"id": connection_id},
            {"$set": {"status": "conectado", "qrcode_atual": None, "numero": numero, "updated_at": _now()}},
        )
        return {"ok": True}

    if etype == "Connected":
        await db.whatsapp_connections.update_one(
            {"id": connection_id}, {"$set": {"status": "conectado", "updated_at": _now()}}
        )
        return {"ok": True}

    if etype in ("Disconnected", "LoggedOut"):
        await db.whatsapp_connections.update_one(
            {"id": connection_id}, {"$set": {"status": "desconectado", "updated_at": _now()}}
        )
        return {"ok": True}

    if etype == "Message":
        info = event.get("Info", {})
        if info.get("IsFromMe") or info.get("IsGroup"):
            return {"ok": True}
        # `Chat` is often a "@lid" (linked ID) — an opaque per-conversation
        # identifier, not a dialable phone number, seen when the sender has
        # WhatsApp's privacy/linked-device addressing enabled. `SenderAlt`
        # carries the real phone-number JID ("55...@s.whatsapp.net") in that
        # case, which is what we actually need to reply — a LID cannot be
        # used as the Phone field on send.
        chat = info.get("Chat", "")
        sender_alt = info.get("SenderAlt", "")
        if chat.endswith("@lid") and sender_alt.endswith("@s.whatsapp.net"):
            number = sender_alt.split("@")[0]
        else:
            number = chat.split("@")[0]
        # JIDs can carry a ":<device_id>" suffix before the "@" (e.g.
        # "559884800522:23") — strip it, WuzAPI's /chat/send rejects it as
        # an unregistered phone number.
        number = number.split(":")[0]
        message_id = info.get("ID") or f"noid_{_now()}"
        msg = event.get("Message", {})
        text = (
            msg.get("conversation")
            or (msg.get("extendedTextMessage") or {}).get("text")
            or (msg.get("imageMessage") or {}).get("caption")
            or ""
        )
        if not text:
            return {"ok": True}
        push_name = info.get("PushName") or None
        bg.add_task(handle_incoming_message, tenant_id, number, text, message_id, connection_id, push_name)
        return {"ok": True, "queued": True}

    return {"ok": True, "ignored": etype}
