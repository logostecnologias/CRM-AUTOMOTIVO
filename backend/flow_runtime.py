"""Real-conversation runtime. Uses the same node-processing logic as the
simulator in flow_engine.py, but persists sessions in MongoDB and sends
real messages via WuzAPI.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from db import get_db
from flow_engine import _find_node, _find_next, _find_start, _interp, _process_node
import wuzapi_client as wuzapi

logger = logging.getLogger("zappzen.flow_runtime")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _fetch_avatar_bg(contact_id: str, token: str, number: str):
    """Fire-and-forget: fetch the contact's profile picture without
    delaying message/reply handling (WuzAPI can take a few seconds, or
    fail outright if the contact hides their picture)."""
    try:
        db = get_db()
        url = await wuzapi.get_avatar(token, number)
        if url:
            await db.contacts.update_one({"id": contact_id}, {"$set": {"foto_url": url}})
    except Exception as e:
        logger.warning("Failed to fetch avatar for contact %s: %s", contact_id, e)


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


async def _send_outputs(db, tenant_id, token, number, session_id, outputs):
    for o in outputs:
        try:
            if o["type"] == "text":
                await wuzapi.send_text(token, number, o["content"])
                await _log_msg(db, session_id, tenant_id, "enviada", o["content"])
            elif o["type"] == "menu":
                lines = [o["content"], ""]
                for i, opt in enumerate(o["options"]):
                    lines.append(f"{i+1}. {opt}")
                text = "\n".join(lines)
                await wuzapi.send_text(token, number, text)
                await _log_msg(db, session_id, tenant_id, "enviada", text, mtype="menu")
            elif o["type"] == "media":
                await wuzapi.send_media(token, number, o.get("media_type", "image"),
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


async def _load_bot_flow(db, tenant_id: str, bot_id: str | None, require_active: bool = True):
    """Carrega bot + fluxo publicado + nó de início. Devolve None se qualquer
    peça faltar (bot inexistente/pausado, fluxo não publicado, fluxo sem
    início) — quem chama decide o que fazer com a ausência."""
    if not bot_id:
        return None
    q = {"id": bot_id, "tenant_id": tenant_id}
    if require_active:
        q["status"] = "ativo"
    bot = await db.bots.find_one(q)
    if not bot:
        return None
    flow = await db.flows.find_one({"id": bot["main_flow_id"]}, {"_id": 0})
    if not flow or not flow.get("published_at"):
        return None
    start = _find_start(flow["nodes"])
    if not start:
        return None
    return bot, flow, start


def _keyword_matches(start: dict, text: str) -> bool:
    keyword = (start.get("data", {}).get("trigger_keyword") or "").strip().lower()
    if not keyword:
        return False
    return keyword in (text or "").strip().lower()


async def _pick_bot_for_new_session(db, tenant_id: str, conn: dict, text: str):
    """Escolhe quem atende uma conversa nova.

    Isolamento por conexão é total: só os bots encaixados nos slots DESTA
    conexão podem responder. Não existe fallback pro bot padrão do tenant nem
    varredura por bots soltos — se o slot está vazio, ninguém responde e a
    conversa nasce direto em "aguardando", pra um humano assumir.

    Cada conexão tem no máximo um bot de cada tipo. O de palavra-chave tem
    preferência: se a mensagem contiver a palavra configurada, ele responde.
    Não contendo, entra o de primeira mensagem.

    Antes desta função o bot era escolhido ANTES do gatilho ser avaliado, então
    o gatilho só conseguia vetar o bot já escolhido, nunca convocar outro: um
    bot de palavra-chave só rodava se fosse justamente o padrão da conexão, e
    nesse caso o de primeira mensagem nunca rodava.
    """
    async def slot(trigger: str):
        # O gatilho fica espelhado no documento do bot justamente pra esta
        # busca: sem isso, seria preciso abrir o fluxo de cada bot da conexão
        # a cada mensagem só pra descobrir o tipo de cada um.
        b = await db.bots.find_one({
            "tenant_id": tenant_id,
            "connection_id": conn["id"],
            "trigger": trigger,
            "status": "ativo",
        })
        return await _load_bot_flow(db, tenant_id, b["id"]) if b else None

    keyword_bot = await slot("keyword")
    if keyword_bot and _keyword_matches(keyword_bot[2], text):
        return keyword_bot

    return await slot("first_message")


async def handle_incoming_message(tenant_id: str, from_number: str, text: str, message_id: str, connection_id: str | None = None, push_name: str | None = None):
    """Called from webhook. Advances the conversation for this contact.

    `connection_id` identifies exactly which whatsapp_connection (and thus
    which WuzAPI instance) the message came in on — required so the
    right bot/instance is used when a tenant has more than one connection.
    `push_name` is the sender's WhatsApp display name (Info.PushName on the
    webhook payload) — free, no extra API call needed.
    """
    db = get_db()

    # Idempotency
    if await db.processed_messages.find_one({"message_id": message_id}):
        return
    await db.processed_messages.insert_one({"message_id": message_id, "at": _now()})

    if connection_id:
        conn = await db.whatsapp_connections.find_one({"id": connection_id, "tenant_id": tenant_id})
    else:
        conn = await db.whatsapp_connections.find_one({"tenant_id": tenant_id})
    if not conn:
        return
    token = conn.get("wuzapi_token")

    # Contact (needs to exist before session lookup)
    contact = await db.contacts.find_one({"tenant_id": tenant_id, "numero_whatsapp": from_number})
    if not contact:
        contact = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "numero_whatsapp": from_number,
            "nome": push_name or from_number,
            "created_at": _now(),
        }
        await db.contacts.insert_one(contact)
        if token:
            asyncio.create_task(_fetch_avatar_bg(contact["id"], token, from_number))
    else:
        updates = {}
        if push_name and contact.get("nome") == contact.get("numero_whatsapp"):
            updates["nome"] = push_name
        if updates:
            await db.contacts.update_one({"id": contact["id"]}, {"$set": updates})
            contact.update(updates)
        if token and not contact.get("foto_url"):
            asyncio.create_task(_fetch_avatar_bg(contact["id"], token, from_number))

    # Conversa já em andamento continua no bot dela (mesmo que ele tenha sido
    # pausado depois — trocar de bot no meio confundiria o contato).
    session = await db.conversation_sessions.find_one({
        "tenant_id": tenant_id, "contact_id": contact["id"],
        "whatsapp_connection_id": conn["id"], "status": {"$in": ["ativa", "aguardando_humano"]}
    })

    # Loga a mensagem antes de qualquer decisão: mesmo sem bot capaz de
    # atender, ela precisa aparecer no histórico da conversa.
    session_id = session["id"] if session else str(uuid.uuid4())
    await _log_msg(db, session_id, tenant_id, "recebida", text)

    outputs: list[dict] = []

    if session and session.get("status") == "aguardando_humano":
        # In human-handoff, don't auto-reply — just log
        await db.conversation_sessions.update_one(
            {"id": session_id}, {"$set": {"updated_at": _now()}, "$inc": {"unread_count": 1}}
        )
        return

    if session:
        loaded = await _load_bot_flow(db, tenant_id, session.get("bot_id"), require_active=False)
        if not loaded:
            # Bot da conversa sumiu ou teve o fluxo despublicado: manda pra
            # fila humana em vez de engolir a mensagem.
            await db.conversation_sessions.update_one(
                {"id": session_id},
                {"$set": {"status": "aguardando_humano", "status_atendimento": "aguardando",
                          "aguardando_desde": session.get("aguardando_desde") or _now(),
                          "updated_at": _now()},
                 "$inc": {"unread_count": 1}},
            )
            await _log_msg(db, session_id, tenant_id, "sistema",
                           "Bot da conversa indisponível — encaminhada para atendimento humano")
            return
        bot, flow, _start = loaded

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
    else:
        picked = await _pick_bot_for_new_session(db, tenant_id, conn, text)
        run_bot_flow = picked is not None
        if picked:
            bot, flow, start = picked
        else:
            # Nenhum bot atende: a conversa ainda nasce, direto em "aguardando",
            # pra um humano ver na inbox em vez de a mensagem sumir.
            bot, flow, start = None, None, None

        conn_id = conn.get("id") if conn else None
        dept_id = conn.get("departamento_padrao_id") if conn else None
        session = {
            "id": session_id,
            "tenant_id": tenant_id,
            "contact_id": contact["id"],
            "bot_id": bot["id"] if bot else None,
            "flow_id": flow["id"] if flow else None,
            "whatsapp_connection_id": conn_id,
            "departamento_id": dept_id,
            "atendente_id": None,
            "status_atendimento": "bot",
            "aguardando_desde": None,
            "assumido_em": None,
            "finalizado_em": None,
            "node_atual_id": start["id"] if start else None,
            "variables": {"nome_contato": contact["nome"], "numero": from_number},
            "status": "ativa",
            "awaiting": None,
            "last_user_message": text,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.conversation_sessions.insert_one(session)
        if run_bot_flow:
            await _run_from(start["id"], flow, session, outputs)
        else:
            session["status"] = "aguardando_humano"
            await _log_msg(db, session_id, tenant_id, "sistema",
                           "Nenhum bot configurado para atender esta mensagem — "
                           "encaminhada para atendimento humano")

    # persist session
    # Mirror flow_engine's session.status → status_atendimento so kanban stays in sync.
    if session.get("status") == "aguardando_humano" and session.get("status_atendimento") == "bot":
        session["status_atendimento"] = "aguardando"
        # Marca o início da espera para a UI mostrar "aguardando há X min".
        session["aguardando_desde"] = _now()
    elif session.get("status") == "finalizada" and session.get("status_atendimento") in (None, "bot"):
        session["status_atendimento"] = "finalizado"
        session["finalizado_em"] = _now()

    await db.conversation_sessions.update_one(
        {"id": session_id},
        {"$set": {
            "node_atual_id": session["node_atual_id"],
            "variables": session["variables"],
            "status": session["status"],
            "status_atendimento": session.get("status_atendimento", "bot"),
            "aguardando_desde": session.get("aguardando_desde"),
            "awaiting": session.get("awaiting"),
            "bot_id": session.get("bot_id"),
            "flow_id": session.get("flow_id"),
            "departamento_id": session.get("departamento_id"),
            "finalizado_em": session.get("finalizado_em"),
            "updated_at": _now(),
        }, "$inc": {"unread_count": 1}},
    )

    # Handle bot-to-bot transfer: swap this session onto the target bot's flow
    # and continue processing so the new bot's greeting fires immediately.
    guard = 0
    while session.get("status") == "transferindo" and guard < 5:
        guard += 1
        target_bot_id = session.get("transfer_target")
        target_bot = await db.bots.find_one({"id": target_bot_id, "tenant_id": tenant_id, "status": "ativo"})
        if not target_bot:
            await _log_msg(db, session_id, tenant_id, "sistema",
                           f"Bot de destino {target_bot_id} não existe ou está inativo", mtype="error")
            await db.conversation_sessions.update_one({"id": session_id}, {"$set": {"status": "finalizada"}})
            break
        target_flow = await db.flows.find_one({"id": target_bot["main_flow_id"]}, {"_id": 0})
        if not target_flow or not target_flow.get("published_at"):
            await _log_msg(db, session_id, tenant_id, "sistema",
                           f"Fluxo do bot destino não publicado", mtype="error")
            await db.conversation_sessions.update_one({"id": session_id}, {"$set": {"status": "finalizada"}})
            break
        start = _find_start(target_flow["nodes"])
        if not start:
            break
        session["bot_id"] = target_bot["id"]
        session["flow_id"] = target_flow["id"]
        session["status"] = "ativa"
        session["awaiting"] = None
        session["transfer_target"] = None
        session["node_atual_id"] = start["id"]
        await _run_from(start["id"], target_flow, session, outputs)
        await db.conversation_sessions.update_one(
            {"id": session_id},
            {"$set": {
                "bot_id": session["bot_id"],
                "flow_id": session["flow_id"],
                "node_atual_id": session["node_atual_id"],
                "variables": session["variables"],
                "status": session["status"],
                "awaiting": session.get("awaiting"),
                "updated_at": _now(),
            }},
        )
        flow = target_flow  # for subsequent iterations if chained transfer

    # send outputs via WuzAPI
    if token and outputs:
        await _send_outputs(db, tenant_id, token, from_number, session_id, outputs)


async def send_human_message(tenant_id: str, session_id: str, content: str):
    """Sends a text from human agent (inbox) via WuzAPI.

    The agent's name is prepended (WhatsApp bold syntax) to the text that
    actually goes out over WhatsApp, so the customer sees who's answering —
    not just an internal-only label. The clean `content` (without the
    prefix) is what's stored/shown in our own chat panel, with the agent
    name kept separately in `meta` for the bold label above the bubble.
    """
    db = get_db()
    session = await db.conversation_sessions.find_one({"id": session_id, "tenant_id": tenant_id})
    if not session:
        return None
    contact = await db.contacts.find_one({"id": session["contact_id"]})
    conn_id = session.get("whatsapp_connection_id")
    if conn_id:
        conn = await db.whatsapp_connections.find_one({"id": conn_id, "tenant_id": tenant_id})
    else:
        conn = await db.whatsapp_connections.find_one({"tenant_id": tenant_id})
    token = conn and conn.get("wuzapi_token")

    agent = None
    if session.get("atendente_id"):
        # No tenant_id filter here: a super admin acting via impersonation
        # has atendente_id set to their own user id, whose record carries
        # tenant_id=None (they belong to no tenant) — filtering by tenant_id
        # would silently fail to find them and drop the name.
        agent = await db.users.find_one({"id": session["atendente_id"]})
    agent_name = agent.get("name") if agent else None
    outgoing_text = f"*{agent_name}:*\n{content}" if agent_name else content

    if token and contact:
        try:
            await wuzapi.send_text(token, contact["numero_whatsapp"], outgoing_text)
        except Exception as e:
            await _log_msg(db, session_id, tenant_id, "erro", f"Falha envio humano: {e}", mtype="error")
            raise
    await _log_msg(db, session_id, tenant_id, "enviada", content,
                    meta={"agent_name": agent_name} if agent_name else None)
    await db.conversation_sessions.update_one({"id": session_id}, {"$set": {"updated_at": _now()}})
    return True
