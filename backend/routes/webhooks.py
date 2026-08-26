"""WuzAPI (whatsmeow) webhook receiver, reached via the zappzen-gateway.

The gateway is the only thing that should call this — it already validated
the WuzAPI HMAC signature once and forwards the same x-hmac-signature header
unchanged (payload bytes are identical), so we re-check it here too rather
than trust the network blindly. It also durably queues + retries delivery
with backoff, so we don't need our own retry here — just process fast and
return 200.

Routing is normally per-connection by URL (/wuzapi/{tenant_id}/{connection_id}),
set when the connection is created (see whatsapp.py's _webhook_url()). In
practice WuzAPI has also been observed delivering real incoming-message
events to the gateway's plain /webhook route even when the per-connection
URL is configured, so /wuzapi (no path params) exists as a fallback that
resolves tenant/connection from the payload's `userID` field instead.
"""
import hmac
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from db import get_db
from flow_runtime import handle_incoming_message

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

logger = logging.getLogger("zappzen.webhooks")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _validate_hmac(body: bytes, request: Request):
    key = os.environ.get("WUZAPI_GLOBAL_HMAC_KEY")
    if not key:
        # Fail-closed (ZZ-11): sem a chave, o webhook alimenta
        # `handle_incoming_message` sem nenhuma autenticação — dá para forjar
        # mensagem em qualquer conversa e mexer no estado das conexões. Antes,
        # a ausência da chave desligava a verificação **em silêncio**; agora a
        # recusa é explícita. O boot também avisa (ver server.on_startup).
        logger.error("WUZAPI_GLOBAL_HMAC_KEY ausente — webhooks recusados até configurá-la")
        raise HTTPException(status_code=503, detail="Webhook signing not configured")
    provided = request.headers.get("x-hmac-signature", "")
    expected = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")


# Cada tipo de mídia vira um nó próprio dentro de Message. Figurinha entra
# como imagem: é webp, o chat exibe igual e o download usa o mesmo endpoint.
_MEDIA_NODES = [
    ("imageMessage", "image"),
    ("videoMessage", "video"),
    ("audioMessage", "audio"),
    ("documentMessage", "document"),
    ("stickerMessage", "image"),
]


def _pick(d: dict, *names):
    """Primeiro nome presente no dict.

    A serialização do whatsmeow não é estável entre versões quanto à caixa das
    chaves (`URL` x `url`, `fileSha256` x `fileSHA256`), e errar a chave aqui
    faria o download falhar silenciosamente — então cada campo é procurado por
    todas as grafias plausíveis.
    """
    for n in names:
        v = d.get(n)
        if v not in (None, ""):
            return v
    return None


def _extract_media(payload: dict, msg: dict) -> dict | None:
    for key, kind in _MEDIA_NODES:
        node = msg.get(key)
        # `{}` conta como presente: quando a WuzAPI já baixou a mídia sozinha,
        # ela pode esvaziar o nó e mandar o binário na raiz do evento — tratar
        # como "sem mídia" jogaria o anexo fora.
        if not isinstance(node, dict):
            continue
        mime = _pick(node, "mimetype", "mimeType", "Mimetype") or payload.get("mimeType")
        length = _pick(node, "fileLength", "FileLength") or 0
        return {
            "kind": kind,
            "mime": mime,
            "filename": _pick(node, "fileName", "filename", "FileName") or payload.get("fileName"),
            "caption": node.get("caption") or "",
            # Sem -skipmedia a WuzAPI já baixa e manda o binário junto do
            # evento; aí não é preciso pedir de novo.
            "base64": payload.get("base64") or None,
            "download": {
                "Url": _pick(node, "URL", "url", "Url"),
                "DirectPath": _pick(node, "directPath", "DirectPath"),
                "MediaKey": _pick(node, "mediaKey", "MediaKey"),
                "Mimetype": mime,
                "FileSHA256": _pick(node, "fileSha256", "fileSHA256", "FileSHA256"),
                "FileEncSHA256": _pick(node, "fileEncSha256", "fileEncSHA256", "FileEncSHA256"),
                "FileLength": int(length) if str(length).isdigit() else 0,
            },
        }
    return None


# A resposta a botão ou lista não vem como texto: cada tipo de mensagem
# interativa devolve a escolha num nó próprio do payload. São quatro porque o
# whatsmeow monta o menu de formas diferentes conforme a versão (botão clássico,
# template, native flow), e o cliente do contato responde no formato que
# recebeu — cobrir só um faria a resposta cair como mensagem sem texto e ser
# descartada logo abaixo, deixando a conversa parada.
_NOS_DE_ESCOLHA = (
    # (nó, chaves do id, chaves do rótulo, caminho do id aninhado)
    ("buttonsResponseMessage", ("selectedButtonId", "selectedButtonID"),
     ("selectedDisplayText",), None),
    ("listResponseMessage", ("selectedRowId", "selectedRowID"),
     ("title", "description"), "singleSelectReply"),
    ("templateButtonReplyMessage", ("selectedId", "selectedID"),
     ("selectedDisplayText",), None),
)


def _escolha_native_flow(no: dict) -> dict | None:
    """O botão de resposta rápida que a WuzAPI monta é um NativeFlowButton, e a
    resposta dele chega com o id dentro de um JSON **em string** —
    `paramsJson: '{"id": "opt_3"}'`. Sem desempacotar isso, a escolha não tem
    id e o contato que tocou no botão cai no caminho de resposta inválida."""
    fluxo = no.get("nativeFlowResponseMessage") or {}
    bruto = _pick(fluxo, "paramsJson", "paramsJSON", "params_json") or ""
    escolhido, rotulo = None, ""
    try:
        params = json.loads(bruto)
        if isinstance(params, dict):
            escolhido = _pick(params, "id", "ID")
            rotulo = _pick(params, "display_text", "displayText", "title") or ""
    except (ValueError, TypeError):
        pass
    rotulo = rotulo or ((no.get("body") or {}).get("text") or "")
    if not escolhido and not rotulo:
        return None
    return {"id": escolhido, "titulo": rotulo}


def _extract_escolha(msg: dict) -> dict | None:
    escolha, origem = None, None
    for chave, ids, rotulos, aninhado in _NOS_DE_ESCOLHA:
        no = msg.get(chave)
        if not isinstance(no, dict) or not no:
            continue
        fonte = (no.get(aninhado) or {}) if aninhado else no
        escolha = {"id": _pick(fonte, *ids), "titulo": _pick(no, *rotulos) or ""}
        origem = chave
        break
    if escolha is None:
        interativo = msg.get("interactiveResponseMessage")
        if isinstance(interativo, dict) and interativo:
            escolha = _escolha_native_flow(interativo)
            origem = "interactiveResponseMessage"
    if escolha is None:
        return None

    if escolha.get("id") and not escolha.get("titulo"):
        # Observado em toque real: a resposta traz o id e nenhum rótulo. O
        # histórico é salvo por `awaiting.rotulos` (ver flow_runtime), mas o
        # payload fica registrado aqui porque a forma exata dele é a única
        # coisa deste módulo que veio de leitura do handler da WuzAPI e não de
        # observação — e é o que diz se falta procurar o rótulo em outro campo.
        logger.info("Escolha interativa sem rótulo (%s) id=%s payload=%s",
                    origem, escolha["id"],
                    json.dumps(msg.get(origem), ensure_ascii=False)[:1000])
    return escolha


@router.post("/wuzapi")
async def wuzapi_webhook_unrouted(request: Request, bg: BackgroundTasks):
    """Some WuzAPI events (observed for real incoming 'Message' events, even
    when a per-connection webhook URL is configured) get delivered to the
    gateway's plain /webhook route instead of /webhook/{tenant_id}/{connection_id}
    — so they arrive here with no IDs in the URL. WuzAPI does stamp every
    payload with `userID`, which is exactly the `wuzapi_user_id` we store per
    connection at creation time, so we resolve tenant/connection from that
    instead of trusting the URL."""
    body = await request.body()
    _validate_hmac(body, request)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    db = get_db()
    conn = await db.whatsapp_connections.find_one({"wuzapi_user_id": payload.get("userID")})
    if not conn:
        # Unknown/stale instance (e.g. a connection created outside this
        # backend, or already deleted) — ack anyway so WuzAPI/gateway don't
        # keep retrying something that will never resolve.
        return {"ok": True, "ignored": "unknown userID"}

    return await _process_webhook_event(conn["tenant_id"], conn["id"], payload, db, bg)


@router.post("/wuzapi/{tenant_id}/{connection_id}")
async def wuzapi_webhook(tenant_id: str, connection_id: str, request: Request, bg: BackgroundTasks):
    body = await request.body()
    _validate_hmac(body, request)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    db = get_db()
    conn = await db.whatsapp_connections.find_one({"id": connection_id, "tenant_id": tenant_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")

    return await _process_webhook_event(tenant_id, connection_id, payload, db, bg)


async def _process_webhook_event(tenant_id: str, connection_id: str, payload: dict, db, bg: BackgroundTasks):
    await db.whatsapp_connections.update_one(
        {"id": connection_id}, {"$set": {"last_webhook_event_at": _now()}}
    )

    etype = payload.get("type", "")
    event = payload.get("event") or {}

    if etype == "QR":
        b64 = payload.get("qrCodeBase64")
        if b64:
            await db.whatsapp_connections.update_one(
                {"id": connection_id},
                {"$set": {"qrcode_atual": b64, "status": "pareando", "updated_at": _now()}},
            )
        return {"ok": True}

    if etype == "PairSuccess":
        raw_id = event.get("ID", "")
        numero = raw_id.split(":")[0].split("@")[0] if raw_id else None
        await db.whatsapp_connections.update_one(
            {"id": connection_id},
            {"$set": {"status": "conectado", "qrcode_atual": None, "numero": numero, "updated_at": _now()}},
        )
        return {"ok": True}

    if etype == "Connected":
        await db.whatsapp_connections.update_one(
            {"id": connection_id}, {"$set": {"status": "conectado", "updated_at": _now()}}
        )
        return {"ok": True}

    if etype in ("Disconnected", "LoggedOut"):
        await db.whatsapp_connections.update_one(
            {"id": connection_id}, {"$set": {"status": "desconectado", "updated_at": _now()}}
        )
        return {"ok": True}

    if etype == "Message":
        info = event.get("Info", {})
        if info.get("IsFromMe") or info.get("IsGroup"):
            return {"ok": True}
        # `Chat` is often a "@lid" (linked ID) — an opaque per-conversation
        # identifier, not a dialable phone number, seen when the sender has
        # WhatsApp's privacy/linked-device addressing enabled. `SenderAlt`
        # carries the real phone-number JID ("55...@s.whatsapp.net") in that
        # case, which is what we actually need to reply — a LID cannot be
        # used as the Phone field on send.
        chat = info.get("Chat", "")
        sender_alt = info.get("SenderAlt", "")
        if chat.endswith("@lid") and sender_alt.endswith("@s.whatsapp.net"):
            number = sender_alt.split("@")[0]
        else:
            number = chat.split("@")[0]
        # JIDs can carry a ":<device_id>" suffix before the "@" (e.g.
        # "559884800522:23") — strip it, WuzAPI's /chat/send rejects it as
        # an unregistered phone number.
        number = number.split(":")[0]
        message_id = info.get("ID") or f"noid_{_now()}"
        msg = event.get("Message", {})
        media = _extract_media(payload, msg)
        escolha = _extract_escolha(msg)
        text = (
            msg.get("conversation")
            or (msg.get("extendedTextMessage") or {}).get("text")
            or (media or {}).get("caption")
            # O rótulo do botão/item é o que o contato viu na tela dele, então é
            # o que faz sentido no histórico. Sem rótulo, o id — feio, mas uma
            # bolha vazia esconderia que o contato respondeu.
            or (escolha or {}).get("titulo")
            or (escolha or {}).get("id")
            or ""
        )
        if not text and not media and not escolha:
            return {"ok": True}
        push_name = info.get("PushName") or None
        bg.add_task(handle_incoming_message, tenant_id, number, text, message_id,
                    connection_id, push_name, media, escolha)
        return {"ok": True, "queued": True}

    return {"ok": True, "ignored": etype}
