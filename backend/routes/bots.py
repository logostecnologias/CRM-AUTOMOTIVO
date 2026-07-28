import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_db
from auth import require_tenant_admin
from plan_limits import enforce_plan_limit

router = APIRouter(prefix="/api/bots", tags=["bots"])


class BotIn(BaseModel):
    name: str


class BotUpdate(BaseModel):
    name: str | None = None
    status: str | None = None


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_bots(user=Depends(require_tenant_admin)):
    db = get_db()
    bots = await db.bots.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return bots


@router.post("")
async def create_bot(body: BotIn, user=Depends(require_tenant_admin)):
    db = get_db()
    await enforce_plan_limit(db, user["tenant_id"], "bots", "max_bots", "robôs")
    bot_id = str(uuid.uuid4())
    flow_id = str(uuid.uuid4())
    now = _now()
    bot = {
        "id": bot_id,
        "tenant_id": user["tenant_id"],
        "name": body.name,
        "status": "rascunho",
        "created_at": now,
        "main_flow_id": flow_id,
    }
    # Create an empty starter flow with a single Start node
    start_node_id = str(uuid.uuid4())
    flow = {
        "id": flow_id,
        "bot_id": bot_id,
        "tenant_id": user["tenant_id"],
        "name": "Fluxo Principal",
        "version": 1,
        "is_main": True,
        "published_at": None,
        "nodes": [{
            "id": start_node_id,
            "type": "start",
            "position": {"x": 100, "y": 200},
            "data": {"label": "Início", "trigger": "first_message"},
        }],
        "edges": [],
        "created_at": now,
        "updated_at": now,
    }
    await db.bots.insert_one(bot)
    await db.flows.insert_one(flow)
    bot.pop("_id", None)
    return bot


@router.get("/{bot_id}")
async def get_bot(bot_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    bot = await db.bots.find_one({"id": bot_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not bot:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    return bot


@router.patch("/{bot_id}")
async def update_bot(bot_id: str, body: BotUpdate, user=Depends(require_tenant_admin)):
    db = get_db()
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if upd:
        await db.bots.update_one(
            {"id": bot_id, "tenant_id": user["tenant_id"]},
            {"$set": upd},
        )
    bot = await db.bots.find_one({"id": bot_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not bot:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    return bot


@router.post("/{bot_id}/duplicate")
async def duplicate_bot(bot_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    await enforce_plan_limit(db, user["tenant_id"], "bots", "max_bots", "robôs")
    bot = await db.bots.find_one({"id": bot_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not bot:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    flow = await db.flows.find_one({"id": bot["main_flow_id"]}, {"_id": 0})
    new_bot_id = str(uuid.uuid4())
    new_flow_id = str(uuid.uuid4())
    now = _now()
    new_bot = {**bot, "id": new_bot_id, "name": f"{bot['name']} (Cópia)", "status": "rascunho",
               "created_at": now, "main_flow_id": new_flow_id}
    new_flow = {**flow, "id": new_flow_id, "bot_id": new_bot_id, "tenant_id": user["tenant_id"],
                "version": 1, "published_at": None, "created_at": now, "updated_at": now}
    await db.bots.insert_one(new_bot)
    await db.flows.insert_one(new_flow)
    new_bot.pop("_id", None)
    return new_bot


@router.patch("/{bot_id}/default")
async def set_default(bot_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    bot = await db.bots.find_one({"id": bot_id, "tenant_id": user["tenant_id"]})
    if not bot:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    # Unset any existing default in this tenant, then set this one.
    await db.bots.update_many({"tenant_id": user["tenant_id"]}, {"$set": {"is_default": False}})
    await db.bots.update_one({"id": bot_id}, {"$set": {"is_default": True}})
    return {"ok": True}


@router.delete("/{bot_id}")
async def delete_bot(bot_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    await db.bots.delete_one({"id": bot_id, "tenant_id": user["tenant_id"]})
    await db.flows.delete_many({"bot_id": bot_id})
    return {"ok": True}
