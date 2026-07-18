"""Real WhatsApp routes backed by Evolution API.
Replaces the previous mock. Old /api/whatsapp/connection endpoint kept
for backward compat with UI that hasn't migrated yet, delegating to the
new logic.
"""
import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from db import get_db
from auth import require_tenant_admin
import evolution_client as evo

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _instance_name(tenant_id: str) -> str:
    return f"zappzen_{tenant_id.replace('-', '')[:16]}"


def _webhook_url(tenant_id: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/api/webhooks/evolution/{tenant_id}"


async def _get_or_create_row(tenant_id: str):
    db = get_db()
    row = await db.whatsapp_connections.find_one({"tenant_id": tenant_id})
    if not row:
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "numero": None,
            "status": "desconectado",
            "qrcode_atual": None,
            "evolution_instance_name": None,
            "evolution_instance_token": None,
            "last_webhook_event_at": None,
            "updated_at": _now(),
        }
        await db.whatsapp_connections.insert_one(row)
        row.pop("_id", None)
    else:
        row.pop("_id", None)
    return row


@router.get("/status")
async def status(user=Depends(require_tenant_admin)):
    row = await _get_or_create_row(user["tenant_id"])
    return row


# Backward-compat alias
@router.get("/connection")
async def get_connection(user=Depends(require_tenant_admin)):
    return await status(user)


@router.post("/connect")
async def connect(user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    row = await _get_or_create_row(tenant_id)

    if row.get("status") == "conectado":
        raise HTTPException(status_code=400, detail="Já existe uma instância conectada. Desconecte primeiro.")

    inst = row.get("evolution_instance_name") or _instance_name(tenant_id)
    hook = _webhook_url(tenant_id)

    # Try create instance (idempotent-ish; if already exists Evolution returns error)
    qr_b64 = None
    try:
        created = await evo.create_instance(inst, hook)
        # v2 returns { instance, hash, qrcode: { code, base64 } }
        qr_data = created.get("qrcode") or {}
        qr_b64 = qr_data.get("base64") or qr_data.get("code")
        token = created.get("hash") or (created.get("instance") or {}).get("token")
    except evo.EvolutionError:
        # Instance may already exist — just fetch QR
        try:
            got = await evo.fetch_qr(inst)
            qr_b64 = (got.get("qrcode") or {}).get("base64") or got.get("base64") or got.get("code")
            token = None
        except evo.EvolutionError as e2:
            raise HTTPException(status_code=502, detail=f"Erro Evolution API: {e2}")

    await db.whatsapp_connections.update_one(
        {"tenant_id": tenant_id},
        {"$set": {
            "evolution_instance_name": inst,
            "evolution_instance_token": token if 'token' in locals() else None,
            "status": "pareando",
            "qrcode_atual": qr_b64,
            "updated_at": _now(),
        }},
    )
    row = await db.whatsapp_connections.find_one({"tenant_id": tenant_id}, {"_id": 0})
    return row


@router.post("/disconnect")
async def disconnect(user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    row = await _get_or_create_row(tenant_id)
    inst = row.get("evolution_instance_name")
    if inst:
        try:
            await evo.logout_instance(inst)
        except evo.EvolutionError:
            pass
    await db.whatsapp_connections.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"status": "desconectado", "qrcode_atual": None, "numero": None, "updated_at": _now()}},
    )
    return await db.whatsapp_connections.find_one({"tenant_id": tenant_id}, {"_id": 0})


# Backward compat POST /connection
from pydantic import BaseModel


class LegacyAction(BaseModel):
    action: str


class ConnectionUpdate(BaseModel):
    departamento_padrao_id: str | None = None


@router.patch("/connection")
async def update_connection_settings(body: ConnectionUpdate, user=Depends(require_tenant_admin)):
    db = get_db()
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if upd:
        upd["updated_at"] = _now()
        await db.whatsapp_connections.update_one({"tenant_id": user["tenant_id"]}, {"$set": upd})
    return await db.whatsapp_connections.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})


@router.post("/connection")
async def legacy_connection(body: LegacyAction, user=Depends(require_tenant_admin)):
    if body.action == "start_pairing":
        return await connect(user)
    if body.action == "disconnect":
        return await disconnect(user)
    if body.action == "confirm_paired":
        # No-op in real integration — connection is confirmed via webhook.
        return await status(user)
    raise HTTPException(status_code=400, detail="Ação desconhecida")
