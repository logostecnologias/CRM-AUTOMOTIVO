"""Mocked WhatsApp connection endpoints.
Real implementation (Cloud API or WhatsApp Web lib) will replace the logic later.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db import get_db
from auth import require_tenant_admin

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fake_qr():
    # Deterministic random-looking token used as QR payload for display
    return f"zappzen-mock-qr-{uuid.uuid4().hex[:24]}"


@router.get("/connection")
async def get_connection(user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})
    if not conn:
        conn = {
            "id": str(uuid.uuid4()),
            "tenant_id": user["tenant_id"],
            "numero": None,
            "status": "desconectado",
            "qrcode_atual": None,
            "updated_at": _now(),
        }
        await db.whatsapp_connections.insert_one(conn)
        conn.pop("_id", None)
    return conn


class PairIn(BaseModel):
    action: str  # start_pairing | confirm_paired | disconnect


@router.post("/connection")
async def update_connection(body: PairIn, user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one({"tenant_id": user["tenant_id"]})
    if not conn:
        conn = {
            "id": str(uuid.uuid4()),
            "tenant_id": user["tenant_id"],
            "numero": None,
            "status": "desconectado",
            "qrcode_atual": None,
            "updated_at": _now(),
        }
        await db.whatsapp_connections.insert_one(conn)

    update = {"updated_at": _now()}
    if body.action == "start_pairing":
        update["status"] = "pareando"
        update["qrcode_atual"] = _fake_qr()
    elif body.action == "confirm_paired":
        update["status"] = "conectado"
        update["qrcode_atual"] = None
        update["numero"] = "+55 11 99999-0000"
    elif body.action == "disconnect":
        update["status"] = "desconectado"
        update["qrcode_atual"] = None
        update["numero"] = None
    await db.whatsapp_connections.update_one({"tenant_id": user["tenant_id"]}, {"$set": update})
    return await db.whatsapp_connections.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})
