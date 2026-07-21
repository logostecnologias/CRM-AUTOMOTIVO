"""WuzAPI (whatsmeow) webhook receiver, reached via the zappzen-gateway.

The gateway is the only thing that should call this — it already validated
the WuzAPI HMAC signature once and forwards the same x-hmac-signature header
unchanged (payload bytes are identical), so we re-check it here too rather
than trust the network blindly. It also durably queues + retries delivery
with backoff, so we don't need our own retry here — just process fast and
return 200.

Routing is per-connection by URL (/wuzapi/{tenant_id}/{connection_id}),
set when the connection is created (see whatsapp.py's _webhook_url()) — no
legacy "resolve by instance name in payload" fallback is needed like the
old Evolution version had, since every connection created from here on
always carries its IDs in the URL.
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
        chat = info.get("Chat", "")
        number = chat.split("@")[0]
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
        bg.add_task(handle_incoming_message, tenant_id, number, text, message_id, connection_id)
        return {"ok": True, "queued": True}

    return {"ok": True, "ignored": etype}
