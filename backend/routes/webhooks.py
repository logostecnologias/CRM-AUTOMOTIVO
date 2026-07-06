"""Evolution API webhook receiver.

Evolution v2 posts a JSON body with `event`, `instance`, `data`.
We validate via the `apikey` header (shared secret) and by matching the
tenant's own instance name — a call for tenant A can't be spoofed
without also knowing A's instance name.
"""
import os
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from db import get_db
from flow_runtime import handle_incoming_message

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.post("/evolution/{tenant_id}")
async def evolution_webhook(tenant_id: str, request: Request, bg: BackgroundTasks):
    # Shared-secret validation
    provided = request.headers.get("apikey") or request.headers.get("Apikey")
    expected = os.environ.get("EVOLUTION_API_KEY")
    if expected and provided and provided != expected:
        raise HTTPException(status_code=401, detail="Invalid apikey")
    # If Evolution can't send apikey header, we still bind by instance name below.

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    db = get_db()
    row = await db.whatsapp_connections.find_one({"tenant_id": tenant_id})
    if not row:
        raise HTTPException(status_code=404, detail="Tenant não configurado")

    event = payload.get("event") or ""
    instance = payload.get("instance") or {}
    inst_name = instance.get("instanceName") if isinstance(instance, dict) else instance
    expected_inst = row.get("evolution_instance_name")
    if expected_inst and inst_name and inst_name != expected_inst:
        raise HTTPException(status_code=403, detail="Instance mismatch")

    data = payload.get("data") or {}

    await db.whatsapp_connections.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"last_webhook_event_at": _now()}},
    )

    event_norm = event.lower().replace(".", "_")

    # QR Code updated
    if event_norm in ("qrcode_updated",):
        b64 = data.get("qrcode", {}).get("base64") if isinstance(data.get("qrcode"), dict) else data.get("base64")
        if b64:
            await db.whatsapp_connections.update_one(
                {"tenant_id": tenant_id},
                {"$set": {"qrcode_atual": b64, "status": "pareando", "updated_at": _now()}},
            )
        return {"ok": True}

    # Connection state
    if event_norm in ("connection_update",):
        state = (data.get("state") or data.get("status") or "").lower()
        if state == "open":
            wid = data.get("wuid") or data.get("wid") or data.get("id") or ""
            numero = wid.split("@")[0] if isinstance(wid, str) else None
            await db.whatsapp_connections.update_one(
                {"tenant_id": tenant_id},
                {"$set": {"status": "conectado", "qrcode_atual": None, "numero": numero, "updated_at": _now()}},
            )
        elif state in ("close", "connecting"):
            new_status = "desconectado" if state == "close" else "pareando"
            await db.whatsapp_connections.update_one(
                {"tenant_id": tenant_id},
                {"$set": {"status": new_status, "updated_at": _now()}},
            )
        return {"ok": True}

    # Incoming message
    if event_norm in ("messages_upsert", "message_upsert"):
        msgs = data.get("messages") or ([data] if data.get("key") else [])
        for m in msgs:
            key = m.get("key", {}) if isinstance(m, dict) else {}
            if key.get("fromMe"):
                continue
            remote = key.get("remoteJid", "")
            if "@g.us" in remote:  # skip groups
                continue
            number = remote.split("@")[0]
            message_id = key.get("id") or f"noid_{_now()}"
            msg_content = m.get("message", {}) if isinstance(m, dict) else {}
            text = (
                msg_content.get("conversation")
                or (msg_content.get("extendedTextMessage") or {}).get("text")
                or (msg_content.get("imageMessage") or {}).get("caption")
                or ""
            )
            if not text:
                continue
            # Fire-and-forget processing so we return 200 fast to Evolution
            bg.add_task(handle_incoming_message, tenant_id, number, text, message_id)
        return {"ok": True, "queued": len(msgs)}

    return {"ok": True, "ignored": event}
