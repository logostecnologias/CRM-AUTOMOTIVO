import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from db import get_db
from auth import require_super_admin, hash_password

router = APIRouter(prefix="/api/admin", tags=["super_admin"])


class TenantCreate(BaseModel):
    name: str
    plan: str = "starter"
    admin_name: str
    admin_email: EmailStr
    admin_password: str


class TenantUpdate(BaseModel):
    name: str | None = None
    plan: str | None = None
    status: str | None = None


@router.get("/tenants")
async def list_tenants(_=Depends(require_super_admin)):
    db = get_db()
    tenants = await db.tenants.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    # counts per tenant
    result = []
    for t in tenants:
        bots = await db.bots.count_documents({"tenant_id": t["id"]})
        users = await db.users.count_documents({"tenant_id": t["id"]})
        result.append({**t, "bots_count": bots, "users_count": users})
    return result


@router.post("/tenants")
async def create_tenant(body: TenantCreate, _=Depends(require_super_admin)):
    db = get_db()
    email = body.admin_email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    tenant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.tenants.insert_one({
        "id": tenant_id,
        "name": body.name,
        "plan": body.plan,
        "status": "active",
        "created_at": now,
    })
    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "name": body.admin_name,
        "email": email,
        "role": "tenant_admin",
        "status": "active",
        "password_hash": hash_password(body.admin_password),
        "created_at": now,
    })
    return {"id": tenant_id, "name": body.name, "plan": body.plan, "status": "active", "created_at": now}


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: TenantUpdate, _=Depends(require_super_admin)):
    db = get_db()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        return {"ok": True}
    res = await db.tenants.update_one({"id": tenant_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    return tenant


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, _=Depends(require_super_admin)):
    db = get_db()
    await db.tenants.delete_one({"id": tenant_id})
    await db.users.delete_many({"tenant_id": tenant_id})
    await db.bots.delete_many({"tenant_id": tenant_id})
    await db.flows.delete_many({"tenant_id": tenant_id})
    await db.contacts.delete_many({"tenant_id": tenant_id})
    await db.conversation_sessions.delete_many({"tenant_id": tenant_id})
    await db.whatsapp_connections.delete_many({"tenant_id": tenant_id})
    return {"ok": True}


@router.get("/metrics")
async def global_metrics(_=Depends(require_super_admin)):
    db = get_db()
    return {
        "tenants_total": await db.tenants.count_documents({}),
        "tenants_active": await db.tenants.count_documents({"status": "active"}),
        "users_total": await db.users.count_documents({"role": "tenant_admin"}),
        "bots_total": await db.bots.count_documents({}),
        "messages_total": await db.messages_log.count_documents({}),
        "conversations_total": await db.conversation_sessions.count_documents({}),
    }
