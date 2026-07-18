"""Múltiplas conexões WhatsApp por tenant, cada uma com sua instância no Evolution."""
import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_db
from auth import require_tenant_admin, get_current_user
import evolution_client as evo

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _instance_name(tenant_id: str, conn_id: str) -> str:
    return f"zappzen_{tenant_id.replace('-', '')[:8]}_{conn_id.replace('-', '')[:8]}"


def _webhook_url(tenant_id: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/api/webhooks/evolution/{tenant_id}"


# ---------- CRUD ----------

class ConnectionIn(BaseModel):
    nome: str
    departamento_padrao_id: str | None = None
    default_bot_id: str | None = None


class ConnectionPatch(BaseModel):
    nome: str | None = None
    departamento_padrao_id: str | None = None
    default_bot_id: str | None = None


@router.get("/connections")
async def list_connections(user: dict = Depends(get_current_user)):
    if not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Sem tenant")
    db = get_db()
    rows = await db.whatsapp_connections.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return rows


@router.post("/connections")
async def create_connection(body: ConnectionIn, user=Depends(require_tenant_admin)):
    db = get_db()
    conn = {
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "nome": body.nome,
        "departamento_padrao_id": body.departamento_padrao_id,
        "default_bot_id": body.default_bot_id,
        "evolution_instance_name": None,
        "evolution_instance_token": None,
        "numero": None,
        "status": "desconectado",
        "qrcode_atual": None,
        "last_webhook_event_at": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.whatsapp_connections.insert_one(conn)
    conn.pop("_id", None)
    return conn


@router.get("/connections/{conn_id}")
async def get_connection(conn_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    return conn


@router.patch("/connections/{conn_id}")
async def update_connection(conn_id: str, body: ConnectionPatch, user=Depends(require_tenant_admin)):
    db = get_db()
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if upd:
        upd["updated_at"] = _now()
        await db.whatsapp_connections.update_one(
            {"id": conn_id, "tenant_id": user["tenant_id"]}, {"$set": upd}
        )
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    return conn


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    if conn.get("evolution_instance_name"):
        try:
            await evo.logout_instance(conn["evolution_instance_name"])
        except evo.EvolutionError:
            pass
    await db.whatsapp_connections.delete_one({"id": conn_id, "tenant_id": user["tenant_id"]})
    await db.user_connection_access.delete_many({"whatsapp_connection_id": conn_id})
    return {"ok": True}


# ---------- Connect / Disconnect ----------

@router.post("/connections/{conn_id}/connect")
async def connect(conn_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    if conn.get("status") == "conectado":
        raise HTTPException(status_code=400, detail="Já está conectada")

    inst = conn.get("evolution_instance_name") or _instance_name(user["tenant_id"], conn_id)
    hook = _webhook_url(user["tenant_id"])

    qr_b64 = None
    token = None
    try:
        created = await evo.create_instance(inst, hook)
        qr_data = created.get("qrcode") or {}
        qr_b64 = qr_data.get("base64") or qr_data.get("code")
        token = created.get("hash") or (created.get("instance") or {}).get("token")
    except evo.EvolutionError:
        try:
            got = await evo.fetch_qr(inst)
            qr_b64 = (got.get("qrcode") or {}).get("base64") or got.get("base64") or got.get("code")
        except evo.EvolutionError as e2:
            raise HTTPException(status_code=502, detail=f"Erro Evolution API: {e2}")

    await db.whatsapp_connections.update_one(
        {"id": conn_id},
        {"$set": {
            "evolution_instance_name": inst,
            "evolution_instance_token": token,
            "status": "pareando",
            "qrcode_atual": qr_b64,
            "updated_at": _now(),
        }},
    )
    return await db.whatsapp_connections.find_one({"id": conn_id}, {"_id": 0})


@router.post("/connections/{conn_id}/disconnect")
async def disconnect(conn_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    if conn.get("evolution_instance_name"):
        try:
            await evo.logout_instance(conn["evolution_instance_name"])
        except evo.EvolutionError:
            pass
    await db.whatsapp_connections.update_one(
        {"id": conn_id},
        {"$set": {"status": "desconectado", "qrcode_atual": None, "numero": None, "updated_at": _now()}},
    )
    return await db.whatsapp_connections.find_one({"id": conn_id}, {"_id": 0})


# ---------- Legacy compat (returns first connection) ----------

async def _first_conn(db, tenant_id: str):
    return await db.whatsapp_connections.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}, sort=[("created_at", 1)]
    )


@router.get("/status")
async def legacy_status(user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await _first_conn(db, user["tenant_id"])
    if not conn:
        return {"status": "desconectado", "id": None, "numero": None, "qrcode_atual": None,
                "evolution_instance_name": None, "departamento_padrao_id": None}
    return conn


@router.get("/connection")
async def legacy_connection(user=Depends(require_tenant_admin)):
    return await legacy_status(user)
