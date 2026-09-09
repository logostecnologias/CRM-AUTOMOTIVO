"""Receptor de webhook do canal não oficial (WuzAPI/whatsmeow).

Módulo separado do receptor da Cloud API de propósito. Os dois terminam no
mesmo lugar — `flow_runtime.handle_incoming_message`, que é o único ponto de
entrada de mensagem recebida do sistema — mas o que vem antes disso não tem
nada em comum: a Meta manda um envelope documentado e estável, com assinatura
sobre os bytes crus e roteamento por `phone_number_id`; a WuzAPI manda a
serialização do whatsmeow, que muda de caixa de chave entre versões e roteia
por URL. Misturar as duas leituras num arquivo só faria cada correção de uma
delas passar por cima do raciocínio da outra.

Três diferenças que moldam este arquivo:

  - **A URL carrega o roteamento.** Ao contrário da Cloud API, aqui cada
    conexão tem a própria URL de webhook (`/wuzapi/{tenant_id}/{connection_id}`),
    gravada na instância quando a conexão é criada. Existe também a rota sem
    parâmetros, como reserva: a WuzAPI já foi observada entregando evento de
    mensagem real na rota simples mesmo com a URL por conexão configurada, e
    ali o que identifica a instância é o `userID` do próprio payload.

  - **A assinatura é nossa e é por conexão.** Antes quem assinava era o
    `zappzen-gateway`, com uma chave global; ele não existe mais. A chave
    passou a viver no documento da conexão (`wuzapi_hmac`), gerada por nós e
    configurada na instância. Fail-closed como a HMAC anterior e como a
    assinatura da Meta: **sem chave, o webhook recusa**. A alternativa é grave
    e não teórica — este endpoint alimenta `handle_incoming_message` e está
    exposto na internet, então sem autenticação dá para forjar mensagem em
    qualquer conversa de qualquer empresa.

  - **O estado da conexão chega por evento.** QR, pareamento, conexão e
    desconexão são eventos do webhook, não consulta. É o oposto da Cloud API,
    onde não há sessão para acompanhar.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from db import get_db
from flow_runtime import handle_incoming_message
from whatsapp_client import CANAL_WUZAPI

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

logger = logging.getLogger("zappzen.webhooks.wuzapi")


def _now():
    return datetime.now(timezone.utc).isoformat()


# A grafia do cabeçalho de assinatura muda entre versões e forks da WuzAPI, e é
# a mesma classe de problema que obrigou o `_pick` das chaves de mídia: errar o
# nome faria toda mensagem ser recusada com 401, o que na tela parece "o
# webhook não chega". Conferimos todos os que aparecem na prática.
CABECALHOS_ASSINATURA = (
    "x-hmac-signature",
    "x-webhook-signature",
    "x-signature",
    "x-hub-signature-256",
)


def _validar_assinatura(corpo: bytes, request: Request, conn: dict) -> None:
    """HMAC-SHA256 do corpo cru com a chave da conexão.

    Sobre os **bytes crus**, nunca sobre o JSON reserializado: a ordem das
    chaves e o espaçamento mudariam o hash. É a mesma regra da assinatura da
    Meta, e o motivo pelo qual o corpo é lido com `await request.body()` antes
    de qualquer `request.json()`.

    Aceita o dígito hexadecimal com ou sem o prefixo `sha256=`, porque as duas
    formas circulam.
    """
    chave = (conn or {}).get("wuzapi_hmac")
    if not chave:
        # Fail-closed. Sem chave não há como distinguir um evento da WuzAPI de
        # um POST de qualquer um na internet, e o que está do outro lado deste
        # endpoint é o motor de conversas de todas as empresas.
        logger.error("Conexão %s sem wuzapi_hmac — webhook recusado",
                     (conn or {}).get("id"))
        raise HTTPException(status_code=503, detail="Webhook sem assinatura configurada")

    esperado = hmac.new(chave.encode(), corpo, hashlib.sha256).hexdigest()
    for nome in CABECALHOS_ASSINATURA:
        recebido = (request.headers.get(nome) or "").strip()
        if not recebido:
            continue
        recebido = recebido.split("=", 1)[1] if recebido.startswith("sha256=") else recebido
        if hmac.compare_digest(recebido.lower(), esperado):
            return
    raise HTTPException(status_code=401, detail="Assinatura inválida")


# Cada tipo de mídia vira um nó próprio dentro de Message. Figurinha entra como
# imagem: é webp, o chat exibe igual e o download usa o mesmo endpoint.
_NOS_DE_MIDIA = [
    ("imageMessage", "image"),
    ("videoMessage", "video"),
    ("audioMessage", "audio"),
    ("documentMessage", "document"),
    ("stickerMessage", "image"),
]


def _pick(d: dict, *nomes):
    """Primeiro nome presente no dicionário.

    A serialização do whatsmeow não é estável entre versões quanto à caixa das
    chaves (`URL` x `url`, `fileSha256` x `fileSHA256`), e errar a chave aqui
    faria o download falhar **em silêncio** — então cada campo é procurado por
    todas as grafias plausíveis.
    """
    for n in nomes:
        v = d.get(n)
        if v not in (None, ""):
            return v
    return None


def _extrair_midia(payload: dict, msg: dict) -> dict | None:
    for chave, kind in _NOS_DE_MIDIA:
        no = msg.get(chave)
        # `{}` conta como presente: quando a WuzAPI já baixou a mídia sozinha
        # ela pode esvaziar o nó e mandar o binário na raiz do evento, e tratar
        # isso como "sem mídia" jogaria o anexo fora.
        if not isinstance(no, dict):
            continue
        mime = _pick(no, "mimetype", "mimeType", "Mimetype") or payload.get("mimeType")
        tamanho = _pick(no, "fileLength", "FileLength") or 0
        return {
            "kind": kind,
            "mime": mime,
            "filename": _pick(no, "fileName", "filename", "FileName") or payload.get("fileName"),
            "caption": no.get("caption") or "",
            # Sem -skipmedia a WuzAPI já baixa e manda o binário junto do
            # evento; aí não é preciso pedir de novo.
            "base64": payload.get("base64") or None,
            "download": {
                "Url": _pick(no, "URL", "url", "Url"),
                "DirectPath": _pick(no, "directPath", "DirectPath"),
                "MediaKey": _pick(no, "mediaKey", "MediaKey"),
                "Mimetype": mime,
                "FileSHA256": _pick(no, "fileSha256", "fileSHA256", "FileSHA256"),
                "FileEncSHA256": _pick(no, "fileEncSha256", "fileEncSHA256", "FileEncSHA256"),
                "FileLength": int(tamanho) if str(tamanho).isdigit() else 0,
            },
        }
    return None


# A resposta a botão ou lista não vem como texto: cada tipo de mensagem
# interativa devolve a escolha num nó próprio do payload. São quatro porque o
# whatsmeow monta o menu de formas diferentes conforme a versão (botão
# clássico, template, native flow), e o cliente do contato responde no formato
# que recebeu — cobrir só um faria a resposta cair como mensagem sem texto e
# ser descartada, deixando a conversa parada esperando uma escolha que já
# chegou.
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
    `paramsJson: '{"id": "opt_3"}'`. Sem desempacotar isso a escolha não tem
    id, e o contato que tocou no botão cai no caminho de resposta inválida."""
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


def _extrair_escolha(msg: dict) -> dict | None:
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


def _numero_do_evento(info: dict) -> str:
    """O telefone com que se responde, a partir do JID do remetente.

    `Chat` costuma ser um `@lid` (linked ID) — identificador opaco por
    conversa, não um número discável, que aparece quando o remetente tem o
    endereçamento por dispositivo vinculado do WhatsApp. Nesse caso o número
    real está em `SenderAlt` (`55...@s.whatsapp.net`), e é ele que serve para
    responder: um LID não pode ir no campo `Phone` do envio.

    O sufixo `:<device_id>` (`559884800522:23`) é removido — o `/chat/send` da
    WuzAPI recusa isso como número não registrado.

    O número sai daqui **como o WhatsApp o entregou**, nunca reconstruído: é a
    mesma regra do `wa_id` da Cloud API, e no Brasil ela é literal, porque
    acrescentar o nono dígito manda a mensagem para outra pessoa.
    """
    chat = info.get("Chat", "") or ""
    sender_alt = info.get("SenderAlt", "") or ""
    if chat.endswith("@lid") and sender_alt.endswith("@s.whatsapp.net"):
        numero = sender_alt.split("@")[0]
    else:
        numero = chat.split("@")[0]
    return numero.split(":")[0]


@router.post("/wuzapi/{tenant_id}/{connection_id}")
async def webhook_wuzapi(tenant_id: str, connection_id: str, request: Request,
                         bg: BackgroundTasks):
    corpo = await request.body()
    db = get_db()
    # A conexão é buscada **antes** da conferência de assinatura porque a chave
    # é dela. Buscar não é agir: nada é processado antes de a assinatura passar.
    conn = await db.whatsapp_connections.find_one(
        {"id": connection_id, "tenant_id": tenant_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    _validar_assinatura(corpo, request, conn)

    try:
        payload = json.loads(corpo)
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    return await _processar_evento(tenant_id, connection_id, payload, db, bg)


@router.post("/wuzapi")
async def webhook_wuzapi_sem_rota(request: Request, bg: BackgroundTasks):
    """Reserva para o evento que chega sem os ids na URL.

    A WuzAPI já foi observada entregando evento de mensagem real na rota
    simples mesmo com a URL por conexão configurada. Ela estampa `userID` em
    todo payload, que é o id da instância que guardamos na conexão, então a
    identificação sai dali em vez da URL.
    """
    corpo = await request.body()
    try:
        payload = json.loads(corpo)
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    # `userID` vazio **não** vira consulta. No Mongo, `{"wuzapi_id": None}`
    # casa com documento em que o campo é nulo **e** com documento em que ele
    # não existe — então um corpo sem `userID` encontraria a primeira conexão
    # da Cloud API da base. Ela não tem chave de assinatura, o fail-closed
    # recusaria com 503, e o sintoma seria "o webhook não funciona" apontando
    # para o lugar errado. Observado logo depois de publicar, com um POST de
    # corpo vazio.
    user_id = payload.get("userID")
    if not user_id:
        return {"ok": True, "ignorado": "payload sem userID"}

    db = get_db()
    # O canal entra no filtro pelo mesmo motivo: garante que só conexão não
    # oficial é resolvida por esta rota.
    conn = await db.whatsapp_connections.find_one(
        {"wuzapi_id": user_id, "canal": CANAL_WUZAPI})
    if not conn:
        # Instância desconhecida ou já apagada: responde 200 para a WuzAPI
        # parar de reentregar algo que nunca vai resolver. Mesma decisão do
        # `phone_number_id` desconhecido no receptor da Cloud API.
        return {"ok": True, "ignorado": "userID desconhecido"}
    _validar_assinatura(corpo, request, conn)
    return await _processar_evento(conn["tenant_id"], conn["id"], payload, db, bg)


async def _processar_evento(tenant_id: str, connection_id: str, payload: dict,
                            db, bg: BackgroundTasks):
    await db.whatsapp_connections.update_one(
        {"id": connection_id}, {"$set": {"last_webhook_event_at": _now()}}
    )

    tipo = payload.get("type", "")
    evento = payload.get("event") or {}

    if tipo == "QR":
        b64 = payload.get("qrCodeBase64")
        if b64:
            await db.whatsapp_connections.update_one(
                {"id": connection_id},
                {"$set": {"qrcode_atual": b64, "status": "pareando",
                          "updated_at": _now()}},
            )
        return {"ok": True}

    if tipo == "PairSuccess":
        bruto = evento.get("ID", "") or ""
        numero = bruto.split(":")[0].split("@")[0] if bruto else None
        await db.whatsapp_connections.update_one(
            {"id": connection_id},
            {"$set": {"status": "conectado", "qrcode_atual": None,
                      "numero": numero, "numero_exibicao": f"+{numero}" if numero else None,
                      "updated_at": _now()}},
        )
        return {"ok": True}

    if tipo == "Connected":
        await db.whatsapp_connections.update_one(
            {"id": connection_id},
            {"$set": {"status": "conectado", "updated_at": _now()}},
        )
        return {"ok": True}

    if tipo in ("Disconnected", "LoggedOut"):
        await db.whatsapp_connections.update_one(
            {"id": connection_id},
            {"$set": {"status": "desconectado", "updated_at": _now()}},
        )
        return {"ok": True}

    if tipo == "Message":
        info = evento.get("Info", {}) or {}
        # Mensagem nossa e grupo ficam de fora: a primeira voltaria como se o
        # contato tivesse escrito (e o bot responderia à própria resposta), e a
        # segunda não tem atendimento individual no produto.
        if info.get("IsFromMe") or info.get("IsGroup"):
            return {"ok": True}

        numero = _numero_do_evento(info)
        message_id = info.get("ID") or f"noid_{_now()}"
        msg = evento.get("Message", {}) or {}
        midia = _extrair_midia(payload, msg)
        escolha = _extrair_escolha(msg)
        texto = (
            msg.get("conversation")
            or (msg.get("extendedTextMessage") or {}).get("text")
            or (midia or {}).get("caption")
            # O rótulo do botão é o que o contato viu na tela dele, então é o
            # que faz sentido no histórico. Sem rótulo, o id — feio, mas uma
            # bolha vazia esconderia que o contato respondeu.
            or (escolha or {}).get("titulo")
            or (escolha or {}).get("id")
            or ""
        )
        if not texto and not midia and not escolha:
            return {"ok": True}

        # Em tarefa de fundo, como no receptor da Cloud API: a WuzAPI reentrega
        # o que não recebe 200 rápido, e processar o fluxo inteiro dentro da
        # requisição faria uma conversa lenta virar evento duplicado.
        bg.add_task(handle_incoming_message, tenant_id, numero, texto, message_id,
                    connection_id, info.get("PushName") or None, midia, escolha)
        return {"ok": True, "enfileirado": True}

    return {"ok": True, "ignorado": tipo}
