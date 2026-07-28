"""Múltiplas conexões WhatsApp por tenant, cada uma com sua instância na WuzAPI."""
import os
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_db
from auth import require_tenant_admin, get_current_user
from plan_limits import enforce_plan_limit
import wuzapi_client as wuzapi

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _instance_name(tenant_id: str, conn_id: str) -> str:
    return f"zappzen_{tenant_id.replace('-', '')[:8]}_{conn_id.replace('-', '')[:8]}"


def _webhook_url(tenant_id: str, conn_id: str) -> str:
    # Aponta pro GATEWAY, não pro PUBLIC_BASE_URL do zappzen — é a WuzAPI
    # que chama essa URL diretamente, e o gateway é quem protege contra o
    # zappzen estar fora do ar (fila + retry). O gateway repassa pro
    # PUBLIC_BASE_URL de verdade por conta própria (configuração dele, não daqui).
    #
    # Importante: essa URL é chamada pelo container da WuzAPI, não por nós —
    # por isso usa WUZAPI_GATEWAY_INTERNAL_URL (endereço da WuzAPI enxerga o
    # gateway dentro da rede docker do servidor, ex: http://gateway:8090),
    # nunca WUZAPI_GATEWAY_URL (que é o endereço que NÓS usamos pra alcançar
    # o gateway, normalmente via túnel SSH em 127.0.0.1 — um "127.0.0.1"
    # aqui apontaria a WuzAPI pra ela mesma, não pro gateway).
    base = os.environ.get("WUZAPI_GATEWAY_INTERNAL_URL", os.environ.get("WUZAPI_GATEWAY_URL", "")).rstrip("/")
    return f"{base}/webhook/{tenant_id}/{conn_id}"


# ---------- CRUD ----------

# O vínculo com bots mora no bot (`bots.connection_id`), não aqui: é lá que se
# escolhe a conexão, e a regra de um bot de cada tipo por conexão é validada em
# bot_binding.
class ConnectionIn(BaseModel):
    nome: str
    departamento_padrao_id: str | None = None


class ConnectionPatch(BaseModel):
    nome: str | None = None
    departamento_padrao_id: str | None = None


@router.get("/connections")
async def list_connections(user: dict = Depends(get_current_user)):
    if not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Sem tenant")
    db = get_db()
    q: dict = {"tenant_id": user["tenant_id"]}
    if user["role"] not in ("tenant_admin", "super_admin"):
        access = await db.user_connection_access.find(
            {"tenant_id": user["tenant_id"], "user_id": user["id"]}, {"_id": 0}
        ).to_list(500)
        q["id"] = {"$in": [a["whatsapp_connection_id"] for a in access]}
    rows = await db.whatsapp_connections.find(q, {"_id": 0}).sort("created_at", 1).to_list(200)
    return rows


@router.post("/connections")
async def create_connection(body: ConnectionIn, user=Depends(require_tenant_admin)):
    db = get_db()
    await enforce_plan_limit(db, user["tenant_id"], "whatsapp_connections", "max_conexoes", "conexões WhatsApp")
    conn = {
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "nome": body.nome,
        "departamento_padrao_id": body.departamento_padrao_id,
        "wuzapi_user_id": None,
        "wuzapi_token": None,
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
    if conn.get("wuzapi_token"):
        try:
            await wuzapi.logout_instance(conn["wuzapi_token"])
        except wuzapi.WuzapiError:
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

    token = conn.get("wuzapi_token") or wuzapi.generate_token()
    name = _instance_name(user["tenant_id"], conn_id)
    hook = _webhook_url(user["tenant_id"], conn_id)

    try:
        wuzapi_id = conn.get("wuzapi_user_id")
        if not conn.get("wuzapi_token"):
            created = await wuzapi.create_instance(name, token, hook)
            wuzapi_id = created.get("id")

        await wuzapi.connect(token)

        qr_b64 = None
        for _ in range(3):  # QR pode levar um instante pra ficar disponível após connect
            qr_b64 = await wuzapi.fetch_qr(token)
            if qr_b64:
                break
            await asyncio.sleep(0.5)
    except wuzapi.WuzapiError as e:
        raise HTTPException(status_code=502, detail=f"Erro WuzAPI: {e}")

    await db.whatsapp_connections.update_one(
        {"id": conn_id},
        {"$set": {
            "wuzapi_user_id": wuzapi_id,
            "wuzapi_token": token,
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
    if conn.get("wuzapi_token"):
        try:
            await wuzapi.disconnect_instance(conn["wuzapi_token"])  # mantém sessão, sem novo QR depois
        except wuzapi.WuzapiError:
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
                "wuzapi_user_id": None, "departamento_padrao_id": None}
    return conn


@router.get("/connection")
async def legacy_connection(user=Depends(require_tenant_admin)):
    return await legacy_status(user)
