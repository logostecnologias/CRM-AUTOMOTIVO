import os
import uuid
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from pydantic import BaseModel, EmailStr

from db import get_db

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str, tenant_id: str | None, impersonation_id: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "impersonation_id": impersonation_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        "type": "access",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def _set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=False,
                        samesite="lax", max_age=12 * 3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=False,
                        samesite="lax", max_age=7 * 86400, path="/")


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Token inválido")
        db = get_db()
        user = await db.users.find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        user.pop("_id", None)
        user.pop("password_hash", None)
        # If impersonating, JWT claims override DB role/tenant.
        if payload.get("impersonation_id"):
            user["role"] = payload.get("role")
            user["tenant_id"] = payload.get("tenant_id")
            user["impersonation_id"] = payload.get("impersonation_id")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


async def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao Super Admin")
    return user


async def require_tenant_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "tenant_admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao Tenant Admin")
    if not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Tenant não vinculado")
    return user


# ---------- Router ----------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response):
    db = get_db()
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Conta suspensa")
    # tenant status check for tenant_admin
    if user["role"] == "tenant_admin" and user.get("tenant_id"):
        tenant = await db.tenants.find_one({"id": user["tenant_id"]})
        if tenant and tenant.get("status") == "suspended":
            raise HTTPException(status_code=403, detail="Empresa suspensa. Contate o administrador.")
    access = create_access_token(user["id"], user["email"], user["role"], user.get("tenant_id"))
    refresh = create_refresh_token(user["id"])
    _set_auth_cookies(response, access, refresh)
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "tenant_id": user.get("tenant_id"),
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "tenant_id": user.get("tenant_id"),
    }


@router.post("/exit-impersonation")
async def exit_impersonation(request: Request, response: Response):
    """Encerra sessão de impersonation e restaura o Super Admin."""
    from db import get_db
    log_id = request.cookies.get("impersonation_id")
    if not log_id:
        raise HTTPException(status_code=400, detail="Não está em modo suporte")
    db = get_db()
    log = await db.impersonation_log.find_one({"id": log_id})
    if not log:
        raise HTTPException(status_code=404, detail="Log não encontrado")
    await db.impersonation_log.update_one(
        {"id": log_id},
        {"$set": {"finalizado_em": datetime.now(timezone.utc).isoformat()}},
    )
    # Re-issue SA token
    sa = await db.users.find_one({"id": log["super_admin_id"]})
    if not sa or sa["role"] != "super_admin":
        raise HTTPException(status_code=500, detail="Super admin ausente")
    access = create_access_token(sa["id"], sa["email"], "super_admin", None)
    refresh = create_refresh_token(sa["id"])
    _set_auth_cookies(response, access, refresh)
    response.delete_cookie("impersonation_id", path="/")
    response.delete_cookie("impersonated_role", path="/")
    return {"ok": True}


async def seed_super_admin():
    db = get_db()
    email = os.environ.get("ADMIN_EMAIL", "admin@zappzen.com").lower()
    password = os.environ.get("ADMIN_PASSWORD", "admin@123")
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": email,
            "name": "Super Admin",
            "role": "super_admin",
            "tenant_id": None,
            "status": "active",
            "password_hash": hash_password(password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif not verify_password(password, existing["password_hash"]):
        await db.users.update_one(
            {"email": email},
            {"$set": {"password_hash": hash_password(password)}},
        )
