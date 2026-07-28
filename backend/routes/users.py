"""Tenant admin manages agents (role='agent') + their connection access."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from db import get_db
from auth import require_tenant_admin, hash_password
from plan_limits import enforce_plan_limit

router = APIRouter(prefix="/api/users", tags=["users"])


class UserIn(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "agent"  # agent | tenant_admin (rarely used)
    connection_ids: list[str] = []


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = None
    status: str | None = None
    connection_ids: list[str] | None = None


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _get_access(db, tenant_id, user_id):
    rows = await db.user_connection_access.find(
        {"tenant_id": tenant_id, "user_id": user_id}, {"_id": 0}
    ).to_list(200)
    return [r["whatsapp_connection_id"] for r in rows]


@router.get("")
async def list_users(admin=Depends(require_tenant_admin)):
    db = get_db()
    users = await db.users.find(
        {"tenant_id": admin["tenant_id"]},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1).to_list(500)
    for u in users:
        u["connection_ids"] = await _get_access(db, admin["tenant_id"], u["id"])
    return users


@router.post("")
async def create_user(body: UserIn, admin=Depends(require_tenant_admin)):
    db = get_db()
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    if body.role not in ("agent", "tenant_admin"):
        raise HTTPException(status_code=400, detail="Papel inválido")
    await enforce_plan_limit(db, admin["tenant_id"], "users", "max_usuarios", "usuários")
    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "tenant_id": admin["tenant_id"],
        "name": body.name,
        "email": email,
        "role": body.role,
        "status": "active",
        "password_hash": hash_password(body.password),
        "created_at": _now(),
    }
    await db.users.insert_one(doc)
    for cid in body.connection_ids:
        await db.user_connection_access.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": admin["tenant_id"],
            "user_id": user_id,
            "whatsapp_connection_id": cid,
        })
    doc.pop("_id", None); doc.pop("password_hash", None)
    doc["connection_ids"] = body.connection_ids
    return doc


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, admin=Depends(require_tenant_admin)):
    db = get_db()
    u = await db.users.find_one({"id": user_id, "tenant_id": admin["tenant_id"]})
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    upd = {}
    if body.name is not None: upd["name"] = body.name
    if body.status is not None: upd["status"] = body.status
    if body.password: upd["password_hash"] = hash_password(body.password)
    if upd:
        await db.users.update_one({"id": user_id}, {"$set": upd})
    if body.connection_ids is not None:
        await db.user_connection_access.delete_many({"tenant_id": admin["tenant_id"], "user_id": user_id})
        for cid in body.connection_ids:
            await db.user_connection_access.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": admin["tenant_id"],
                "user_id": user_id,
                "whatsapp_connection_id": cid,
            })
    out = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    out["connection_ids"] = await _get_access(db, admin["tenant_id"], user_id)
    return out


@router.delete("/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_tenant_admin)):
    db = get_db()
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Não pode excluir a si mesmo")
    await db.users.delete_one({"id": user_id, "tenant_id": admin["tenant_id"]})
    await db.user_connection_access.delete_many({"tenant_id": admin["tenant_id"], "user_id": user_id})
    return {"ok": True}
