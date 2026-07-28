import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_db
from auth import require_tenant_admin
from flow_runtime import send_human_message as _send_human

router = APIRouter(prefix="/api", tags=["contacts"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class ContactIn(BaseModel):
    bot_id: str
    numero_whatsapp: str
    nome: str


@router.get("/contacts")
async def list_contacts(user=Depends(require_tenant_admin)):
    db = get_db()
    contacts = await db.contacts.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return contacts


@router.post("/contacts")
async def create_contact(body: ContactIn, user=Depends(require_tenant_admin)):
    db = get_db()
    contact = {
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "bot_id": body.bot_id,
        "numero_whatsapp": body.numero_whatsapp,
        "nome": body.nome,
        "created_at": _now(),
    }
    await db.contacts.insert_one(contact)
    contact.pop("_id", None)
    return contact


@router.get("/sessions")
async def list_sessions(user=Depends(require_tenant_admin), status: str | None = None):
    db = get_db()
    q = {"tenant_id": user["tenant_id"]}
    if status:
        q["status"] = status
    sessions = await db.conversation_sessions.find(q, {"_id": 0}).sort("updated_at", -1).to_list(500)
    return sessions


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    session = await db.conversation_sessions.find_one(
        {"id": session_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    # Mesmo desempate por `_id` da Central: mensagens da mesma rajada
    # compartilham o timestamp, e sem ele a ordem do histórico é indefinida.
    messages = await db.messages_log.find(
        {"session_id": session_id}, {"_id": 0}
    ).sort([("timestamp", 1), ("_id", 1)]).to_list(1000)
    return {"session": session, "messages": messages}


class SendMessageIn(BaseModel):
    content: str


@router.post("/sessions/{session_id}/messages")
async def send_human_message(session_id: str, body: SendMessageIn, user=Depends(require_tenant_admin)):
    """Human agent sends a message inside handoff inbox (mocked send)."""
    db = get_db()
    session = await db.conversation_sessions.find_one(
        {"id": session_id, "tenant_id": user["tenant_id"]}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    try:
        await _send_human(user["tenant_id"], session_id, body.content)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha ao enviar via WhatsApp: {e}")
    msg = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "direction": "enviada",
        "content": body.content,
        "type": "text",
        "sent_by": user["email"],
        "timestamp": _now(),
    }
    return msg


class SessionStatusIn(BaseModel):
    status: str


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, body: SessionStatusIn, user=Depends(require_tenant_admin)):
    db = get_db()
    res = await db.conversation_sessions.update_one(
        {"id": session_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": body.status, "updated_at": _now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return {"ok": True}
