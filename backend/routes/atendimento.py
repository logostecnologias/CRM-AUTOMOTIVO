"""Central de Atendimento — lista de conversas + ações."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_db
from auth import get_current_user
from flow_runtime import send_human_message

router = APIRouter(prefix="/api/atendimento", tags=["atendimento"])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _accessible_connection_ids(db, user: dict) -> list[str] | None:
    """Returns None (=todos) para admin/super, ou lista explícita para agent."""
    if user["role"] in ("tenant_admin", "super_admin"):
        return None
    rows = await db.user_connection_access.find(
        {"tenant_id": user["tenant_id"], "user_id": user["id"]}, {"_id": 0}
    ).to_list(500)
    return [r["whatsapp_connection_id"] for r in rows]


async def _enrich(db, sessions: list[dict]):
    if not sessions:
        return sessions
    contact_ids = list({s["contact_id"] for s in sessions if s.get("contact_id")})
    dept_ids = list({s["departamento_id"] for s in sessions if s.get("departamento_id")})
    agent_ids = list({s["atendente_id"] for s in sessions if s.get("atendente_id")})
    conn_ids = list({s["whatsapp_connection_id"] for s in sessions if s.get("whatsapp_connection_id")})
    contacts = {c["id"]: c async for c in db.contacts.find({"id": {"$in": contact_ids}}, {"_id": 0})}
    depts = {d["id"]: d async for d in db.departments.find({"id": {"$in": dept_ids}}, {"_id": 0})}
    agents = {u["id"]: u async for u in db.users.find({"id": {"$in": agent_ids}}, {"_id": 0, "password_hash": 0})}
    conns = {c["id"]: c async for c in db.whatsapp_connections.find(
        {"id": {"$in": conn_ids}}, {"_id": 0, "id": 1, "nome": 1, "numero": 1}
    )}
    session_ids = [s["id"] for s in sessions]
    last_messages = {
        row["_id"]: row["last"]
        async for row in db.messages_log.aggregate([
            {"$match": {"session_id": {"$in": session_ids}}},
            {"$sort": {"timestamp": -1}},
            {"$group": {"_id": "$session_id", "last": {"$first": "$$ROOT"}}},
        ])
    }
    for s in sessions:
        s["contact"] = contacts.get(s.get("contact_id"))
        s["department"] = depts.get(s.get("departamento_id"))
        s["agent"] = agents.get(s.get("atendente_id"))
        s["connection"] = conns.get(s.get("whatsapp_connection_id"))
        last = last_messages.get(s["id"])
        if last:
            last.pop("_id", None)
        s["last_message"] = last
    return sessions


@router.get("/sessions")
async def list_sessions(
    user: dict = Depends(get_current_user),
    status: str | None = None,
    department_id: str | None = None,
    connection_id: str | None = None,
    limit: int = 200,
):
    if not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Sem tenant")
    db = get_db()
    q: dict = {"tenant_id": user["tenant_id"]}
    if status:
        q["status_atendimento"] = status
    if department_id:
        q["departamento_id"] = department_id

    accessible = await _accessible_connection_ids(db, user)
    if accessible is not None:
        if connection_id and connection_id not in accessible:
            raise HTTPException(status_code=403, detail="Sem acesso a esta conexão")
        q["whatsapp_connection_id"] = connection_id if connection_id else {"$in": accessible}
    elif connection_id:
        q["whatsapp_connection_id"] = connection_id

    sessions = await db.conversation_sessions.find(q, {"_id": 0}).sort("updated_at", -1).limit(limit).to_list(limit)
    return await _enrich(db, sessions)


@router.get("/unread-count")
async def unread_count(user: dict = Depends(get_current_user)):
    """Soma leve de unread_count, sem o enrich caro de /sessions — usada pelo
    polling do sino/som de notificação, que roda a cada poucos segundos."""
    if not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Sem tenant")
    db = get_db()
    q: dict = {"tenant_id": user["tenant_id"], "unread_count": {"$gt": 0}}
    accessible = await _accessible_connection_ids(db, user)
    if accessible is not None:
        q["whatsapp_connection_id"] = {"$in": accessible}
    total = 0
    async for s in db.conversation_sessions.find(q, {"_id": 0, "unread_count": 1}):
        total += s.get("unread_count") or 0
    return {"total": total}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    s = await db.conversation_sessions.find_one(
        {"id": session_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    accessible = await _accessible_connection_ids(db, user)
    if accessible is not None and s.get("whatsapp_connection_id") not in accessible:
        raise HTTPException(status_code=403, detail="Sem acesso a esta conexão")
    msgs = await db.messages_log.find({"session_id": session_id}, {"_id": 0}).sort("timestamp", 1).to_list(2000)
    if s.get("unread_count"):
        await db.conversation_sessions.update_one({"id": session_id}, {"$set": {"unread_count": 0}})
        s["unread_count"] = 0
    (await _enrich(db, [s]))
    return {"session": s, "messages": msgs}


@router.post("/sessions/{session_id}/assume")
async def assume(session_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    s = await db.conversation_sessions.find_one({"id": session_id, "tenant_id": user["tenant_id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    accessible = await _accessible_connection_ids(db, user)
    if accessible is not None and s.get("whatsapp_connection_id") not in accessible:
        raise HTTPException(status_code=403, detail="Sem acesso a esta conexão")
    if s.get("status_atendimento") not in ("aguardando", "em_atendimento"):
        raise HTTPException(status_code=400, detail="Conversa não está em fila humana")
    await db.conversation_sessions.update_one(
        {"id": session_id},
        {"$set": {
            "status_atendimento": "em_atendimento",
            "status": "aguardando_humano",
            "atendente_id": user["id"],
            "assumido_em": s.get("assumido_em") or _now(),
            "updated_at": _now(),
        }},
    )
    await db.messages_log.insert_one({
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "tenant_id": user["tenant_id"],
        "direction": "sistema",
        "type": "system",
        "content": f"{user['name']} assumiu a conversa",
        "timestamp": _now(),
    })
    return {"ok": True}


@router.post("/sessions/{session_id}/finalize")
async def finalize(session_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    s = await db.conversation_sessions.find_one({"id": session_id, "tenant_id": user["tenant_id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    if user["role"] == "agent" and s.get("atendente_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Só quem assumiu pode finalizar")
    await db.conversation_sessions.update_one(
        {"id": session_id},
        {"$set": {
            "status_atendimento": "finalizado",
            "status": "finalizada",
            "finalizado_em": _now(),
            "updated_at": _now(),
        }},
    )
    await db.messages_log.insert_one({
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "tenant_id": user["tenant_id"],
        "direction": "sistema",
        "type": "system",
        "content": f"{user['name']} finalizou o atendimento",
        "timestamp": _now(),
    })
    return {"ok": True}


class ReassignIn(BaseModel):
    department_id: str | None = None


@router.patch("/sessions/{session_id}/department")
async def reassign_department(session_id: str, body: ReassignIn, user: dict = Depends(get_current_user)):
    db = get_db()
    s = await db.conversation_sessions.find_one({"id": session_id, "tenant_id": user["tenant_id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    # Any tenant user with access can reassign
    accessible = await _accessible_connection_ids(db, user)
    if accessible is not None and s.get("whatsapp_connection_id") not in accessible:
        raise HTTPException(status_code=403, detail="Sem acesso")
    await db.conversation_sessions.update_one(
        {"id": session_id},
        {"$set": {"departamento_id": body.department_id, "updated_at": _now()}},
    )
    return {"ok": True}


class SendIn(BaseModel):
    content: str


@router.post("/sessions/{session_id}/send")
async def send(session_id: str, body: SendIn, user: dict = Depends(get_current_user)):
    """Human agent sends a message via WuzAPI."""
    db = get_db()
    s = await db.conversation_sessions.find_one({"id": session_id, "tenant_id": user["tenant_id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    if user["role"] == "agent" and s.get("atendente_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Assuma a conversa antes de enviar")
    if s.get("status_atendimento") != "em_atendimento":
        # Force-assume if admin/tenant_admin sends directly
        if user["role"] in ("tenant_admin", "super_admin"):
            await db.conversation_sessions.update_one(
                {"id": session_id},
                {"$set": {
                    "status_atendimento": "em_atendimento",
                    "status": "aguardando_humano",
                    "atendente_id": user["id"],
                    "assumido_em": _now(),
                }},
            )
        else:
            raise HTTPException(status_code=400, detail="Conversa não está em atendimento")
    try:
        await send_human_message(user["tenant_id"], session_id, body.content)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha ao enviar: {e}")
    return {"ok": True}


@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)):
    """Kanban column counts respecting user access."""
    db = get_db()
    q: dict = {"tenant_id": user["tenant_id"]}
    accessible = await _accessible_connection_ids(db, user)
    if accessible is not None:
        q["whatsapp_connection_id"] = {"$in": accessible}
    counts = {}
    for st in ["bot", "aguardando", "em_atendimento", "finalizado"]:
        counts[st] = await db.conversation_sessions.count_documents({**q, "status_atendimento": st})
    return counts
