"""Real-conversation runtime. Uses the same node-processing logic as the
simulator in flow_engine.py, but persists sessions in MongoDB and sends
real messages via Evolution API.
"""
import uuid
from datetime import datetime, timezone
from db import get_db
from flow_engine import _find_node, _find_next, _find_start, _interp, _process_node
import evolution_client as evo


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _log_msg(db, session_id, tenant_id, direction, content, mtype="text", meta=None):
    doc = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "tenant_id": tenant_id,
        "direction": direction,
        "content": content,
        "type": mtype,
        "meta": meta or {},
        "timestamp": _now(),
    }
    await db.messages_log.insert_one(doc)


async def _send_outputs(db, tenant_id, instance_name, number, session_id, outputs):
    for o in outputs:
        try:
            if o["type"] == "text":
                await evo.send_text(instance_name, number, o["content"])
                await _log_msg(db, session_id, tenant_id, "enviada", o["content"])
            elif o["type"] == "menu":
                lines = [o["content"], ""]
                for i, opt in enumerate(o["options"]):
                    lines.append(f"{i+1}. {opt}")
                text = "\n".join(lines)
                await evo.send_text(instance_name, number, text)
                await _log_msg(db, session_id, tenant_id, "enviada", text, mtype="menu")
            elif o["type"] == "media":
                await evo.send_media(instance_name, number, o.get("media_type", "image"),
                                     o.get("url", ""), o.get("caption", ""))
                await _log_msg(db, session_id, tenant_id, "enviada", o.get("url", ""),
                               mtype=o.get("media_type", "image"))
            elif o["type"] == "system":
                await _log_msg(db, session_id, tenant_id, "sistema", o["content"], mtype="system")
        except Exception as e:
            await _log_msg(db, session_id, tenant_id, "erro", f"Falha envio: {e}", mtype="error")


async def _run_from(node_id, flow, session, outputs, guard=0):
    while node_id and guard < 50:
        node = _find_node(flow["nodes"], node_id)
        if node is None:
            break
        next_id = await _process_node(node, flow, session, outputs)
        session["node_atual_id"] = node["id"]
        if next_id is None:
            break
        node_id = next_id
        guard += 1


async def handle_incoming_message(tenant_id: str, from_number: str, text: str, message_id: str):
    """Called from webhook. Advances the conversation for this contact."""
    db = get_db()

    # Idempotency
    if await db.processed_messages.find_one({"message_id": message_id}):
        return
    await db.processed_messages.insert_one({"message_id": message_id, "at": _now()})

    conn = await db.whatsapp_connections.find_one({"tenant_id": tenant_id})
    if not conn:
        return
    instance_name = conn.get("evolution_instance_name")

    # Find active bot (first ativo)
    bot = await db.bots.find_one({"tenant_id": tenant_id, "status": "ativo"})
    if not bot:
        return

    # Contact
    contact = await db.contacts.find_one({"tenant_id": tenant_id, "numero_whatsapp": from_number})
    if not contact:
        contact = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "bot_id": bot["id"],
            "numero_whatsapp": from_number,
            "nome": from_number,
            "created_at": _now(),
        }
        await db.contacts.insert_one(contact)

    # Session
    session = await db.conversation_sessions.find_one({
        "tenant_id": tenant_id, "contact_id": contact["id"], "status": {"$in": ["ativa", "aguardando_humano"]}
    })

    flow = await db.flows.find_one({"id": bot["main_flow_id"]}, {"_id": 0})
    if not flow or not flow.get("published_at"):
        return

    # Log incoming
    session_id = session["id"] if session else str(uuid.uuid4())
    await _log_msg(db, session_id, tenant_id, "recebida", text)

    outputs: list[dict] = []

    if session and session.get("status") == "aguardando_humano":
        # In human-handoff, don't auto-reply — just log
        await db.conversation_sessions.update_one({"id": session_id}, {"$set": {"updated_at": _now()}})
        return

    if not session:
        start = _find_start(flow["nodes"])
        if not start:
            return
        session = {
            "id": session_id,
            "tenant_id": tenant_id,
            "contact_id": contact["id"],
            "bot_id": bot["id"],
            "flow_id": flow["id"],
            "node_atual_id": start["id"],
            "variables": {"nome_contato": contact["nome"], "numero": from_number},
            "status": "ativa",
            "awaiting": None,
            "last_user_message": text,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.conversation_sessions.insert_one(session)
        await _run_from(start["id"], flow, session, outputs)
    else:
        session["last_user_message"] = text
        awaiting = session.get("awaiting")
        if awaiting and awaiting.get("node_id"):
            menu_node = _find_node(flow["nodes"], awaiting["node_id"])
            if menu_node and menu_node["type"] == "menu":
                opts = menu_node.get("data", {}).get("options", [])
                handle = None
                m = (text or "").strip()
                if m.isdigit():
                    i = int(m) - 1
                    if 0 <= i < len(opts):
                        handle = opts[i].get("id") or f"opt_{i}"
                if handle is None:
                    for i, o in enumerate(opts):
                        if o.get("label", "").strip().lower() == m.lower():
                            handle = o.get("id") or f"opt_{i}"
                            break
                if handle is None:
                    next_id = _find_next(flow["edges"], menu_node["id"], "invalid")
                    if next_id is None:
                        outputs.append({"type": "text",
                                        "content": menu_node["data"].get("invalid_message", "Resposta inválida.")})
                    else:
                        session["awaiting"] = None
                        await _run_from(next_id, flow, session, outputs)
                else:
                    next_id = _find_next(flow["edges"], menu_node["id"], handle)
                    session["awaiting"] = None
                    if next_id:
                        await _run_from(next_id, flow, session, outputs)

    # persist session
    await db.conversation_sessions.update_one(
        {"id": session_id},
        {"$set": {
            "node_atual_id": session["node_atual_id"],
            "variables": session["variables"],
            "status": session["status"],
            "awaiting": session.get("awaiting"),
            "updated_at": _now(),
        }},
    )

    # send outputs via Evolution
    if instance_name and outputs:
        await _send_outputs(db, tenant_id, instance_name, from_number, session_id, outputs)


async def send_human_message(tenant_id: str, session_id: str, content: str):
    """Sends a text from human agent (inbox) via Evolution API."""
    db = get_db()
    session = await db.conversation_sessions.find_one({"id": session_id, "tenant_id": tenant_id})
    if not session:
        return None
    contact = await db.contacts.find_one({"id": session["contact_id"]})
    conn = await db.whatsapp_connections.find_one({"tenant_id": tenant_id})
    instance = conn and conn.get("evolution_instance_name")
    if instance and contact:
        try:
            await evo.send_text(instance, contact["numero_whatsapp"], content)
        except Exception as e:
            await _log_msg(db, session_id, tenant_id, "erro", f"Falha envio humano: {e}", mtype="error")
            raise
    await _log_msg(db, session_id, tenant_id, "enviada", content)
    await db.conversation_sessions.update_one({"id": session_id}, {"$set": {"updated_at": _now()}})
    return True
