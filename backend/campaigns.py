"""Campanhas de disparo — o primeiro envio ativo do ZappZen.

Até aqui toda mensagem que saía era reativa: nascia de um webhook de entrada,
dentro de uma conversa que já existia. Campanha inverte isso — a plataforma
escreve primeiro. Duas consequências moldam este módulo:

  - **A sessão ainda não existe.** `conversation_sessions` sempre nasceu em
    `flow_runtime.handle_incoming_message`. Um disparo que apenas chamasse
    `wuzapi.send_text` entregaria a mensagem e deixaria a resposta do contato
    cair numa conversa nova, sem vínculo nenhum com a campanha — o atendente
    veria um "quanto custa?" solto, sem saber o que foi oferecido. Por isso
    `ensure_session` cria (ou reaproveita) a conversa **antes** do envio, e é
    ela que carrega `campanha_id`.

  - **Ninguém pediu esta mensagem.** Daí `opt_out` do contato ser respeitado
    aqui, e o destinatário recusado virar `ignorado` em vez de `falha`: não é
    erro de entrega, é vontade registrada de não receber.

O estado de cada destinatário vive em `campaign_recipients`, um documento por
contato. É o que permite retomar exatamente de onde parou depois de um
restart — e é de onde saem as métricas da campanha, sem varrer `messages_log`.

O envio em si passa por `wuzapi_client`, que vai pelo gateway: é ele que já
aplica rate limiting e normaliza o número. A cadência daqui (ver
`campaign_runner`) é outra coisa — é sobre não parecer robô para o WhatsApp,
não sobre proteger a WuzAPI.
"""
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone

import media_store
import outbound
import wuzapi_client as wuzapi
from flow_engine import _interp
from flow_runtime import log_message

logger = logging.getLogger("zappzen.campaigns")

# Estados da campanha. `pausada` é diferente de `cancelada`: pausada volta a
# enviar de onde parou, cancelada descarta o que faltava.
STATUS = ("rascunho", "agendada", "enviando", "pausada", "concluida", "cancelada")

# Estados do destinatário. `enviando` é um estado de posse — quem o gravou
# está mandando a mensagem agora — e é o que impede dois workers de disparar
# para o mesmo contato.
DESTINO_STATUS = ("pendente", "enviando", "enviado", "falha", "ignorado")

# Teto de público por campanha. Não é limite de negócio, é de memória: a lista
# é materializada de uma vez para `campaign_recipients`. Acima disso a resposta
# diz o número exato em vez de truncar em silêncio — público cortado sem aviso
# viraria "a campanha não chegou pra metade da base" sem explicação.
MAX_PUBLICO = 20000

# Como o contato sai da lista. Comparação com a mensagem **inteira**, não
# "contém": "quero cancelar meu pedido" é atendimento, não descadastro, e
# tirar esse cliente da base por engano é pior do que exigir a palavra exata.
# É também a convenção que o próprio texto da campanha pode instruir
# ("responda SAIR para não receber mais").
OPT_OUT_PALAVRAS = {
    "sair", "parar", "pare", "cancelar", "descadastrar", "descadastro",
    "remover", "stop", "sairdalista", "naoquero", "naoqueromais",
    "naoqueroreceber", "naoquerorecebermais", "semmensagens", "naomeenviemais",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _normaliza(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação/espaço, para o cotejo de
    opt-out. "SAIR!", "sair" e "Sair " são a mesma intenção."""
    limpo = unicodedata.normalize("NFKD", texto or "")
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", limpo.lower())


def pediu_opt_out(texto: str) -> bool:
    return _normaliza(texto) in OPT_OUT_PALAVRAS


# ---------- Público ----------


def audience_query(tenant_id: str, publico: dict) -> dict:
    """Filtro de contatos de um público, já sem quem pediu para sair.

    `opt_out` é excluído aqui, no filtro, e não na hora do envio: assim a
    prévia que a tela mostra ("2.480 contatos") é o mesmo número que vai
    receber, em vez de encolher no meio do disparo sem explicação.
    """
    q: dict = {"tenant_id": tenant_id, "opt_out": {"$ne": True}}
    tipo = (publico or {}).get("tipo", "todos")
    if tipo == "tags":
        tags = [t for t in (publico.get("tags") or []) if t]
        # Sem tag nenhuma o filtro casaria a base inteira — o oposto do que
        # quem escolheu "por etiqueta" pediu.
        q["tags"] = {"$in": tags} if tags else {"$in": []}
    elif tipo == "selecionados":
        q["id"] = {"$in": list((publico.get("contact_ids") or []))}
    return q


async def audience_count(db, tenant_id: str, publico: dict) -> int:
    return await db.contacts.count_documents(audience_query(tenant_id, publico))


class CampaignError(Exception):
    pass


async def materialize_recipients(db, campaign: dict) -> int:
    """Congela o público da campanha em `campaign_recipients`.

    Congelar no início do disparo, e não resolver o filtro a cada envio, é
    deliberado: uma campanha "todos os contatos" que rodasse por uma hora
    incluiria quem chegou no meio do caminho, e o total mostrado na tela nunca
    fecharia com o que foi enviado. Depois de materializado, o público é aquele
    e o progresso é uma conta simples.

    Idempotente: reexecutar não duplica destinatário, só acrescenta quem
    faltava (é o que torna "retomar" seguro).
    """
    tenant_id = campaign["tenant_id"]
    total = await audience_count(db, tenant_id, campaign.get("publico") or {})
    if total == 0:
        raise CampaignError("Nenhum contato no público selecionado")
    if total > MAX_PUBLICO:
        raise CampaignError(
            f"Público de {total} contatos acima do limite de {MAX_PUBLICO} por campanha. "
            "Divida por etiqueta em campanhas menores."
        )

    ja_tem = set(
        await db.campaign_recipients.distinct("contact_id", {"campaign_id": campaign["id"]})
    )
    cursor = db.contacts.find(
        audience_query(tenant_id, campaign.get("publico") or {}),
        {"_id": 0, "id": 1, "nome": 1, "numero_whatsapp": 1},
    )
    lote, criados = [], 0
    async for c in cursor:
        if c["id"] in ja_tem:
            continue
        lote.append({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "campaign_id": campaign["id"],
            "contact_id": c["id"],
            "numero_whatsapp": c.get("numero_whatsapp"),
            "nome": c.get("nome"),
            "status": "pendente",
            "erro": None,
            "session_id": None,
            "sent_at": None,
            "respondeu": False,
            "respondido_em": None,
            "created_at": _now(),
        })
        if len(lote) >= 500:
            await db.campaign_recipients.insert_many(lote)
            criados += len(lote)
            lote = []
    if lote:
        await db.campaign_recipients.insert_many(lote)
        criados += len(lote)

    await db.campaigns.update_one(
        {"id": campaign["id"]},
        {"$set": {"totais.total": await db.campaign_recipients.count_documents(
            {"campaign_id": campaign["id"]}), "updated_at": _now()}},
    )
    return criados


# ---------- Sessão de saída ----------


async def ensure_session(db, campaign: dict, contact: dict) -> dict:
    """A conversa do disparo. O bootstrap em si vive em `outbound.py`, que é
    compartilhado com a mensagem direta da ficha do contato — os dois casos
    precisam da mesma sessão criada antes do envio, e duplicar isso deixaria
    um dos dois sem `campanha_id` ou sem a marca de primeira resposta."""
    session, _criada = await outbound.ensure_session(
        db,
        campaign["tenant_id"],
        campaign["whatsapp_connection_id"],
        contact,
        # Em modo "bot" o bot da campanha já entra vinculado, para a primeira
        # resposta do contato cair no fluxo dele. Em modo "aguardando" fica sem
        # bot de propósito: a resposta vai direto para a fila humana.
        bot_id=campaign.get("bot_id") if campaign.get("resposta_modo") == "bot" else None,
        departamento_id=campaign.get("departamento_id"),
        origem="campanha",
        campanha_id=campaign["id"],
        resposta_modo=campaign.get("resposta_modo") or "aguardando",
    )
    return session


async def mark_reply(db, session: dict):
    """Marca no destinatário que o contato respondeu ao disparo.

    Taxa de resposta é a métrica que uma campanha existe para produzir, e
    contá-la depois exigiria cruzar `messages_log` com horário de envio. Um
    update de um campo no momento da resposta troca isso por nada.
    """
    if not session.get("campanha_id"):
        return
    await db.campaign_recipients.update_one(
        {
            "campaign_id": session["campanha_id"],
            "contact_id": session.get("contact_id"),
            "respondeu": {"$ne": True},
        },
        {"$set": {"respondeu": True, "respondido_em": _now()}},
    )


# ---------- Envio ----------


def render(texto: str, contact: dict) -> str:
    """Interpola as variáveis do contato no texto da campanha.

    Mesmo `_interp` do motor de fluxos, de propósito: quem escreve
    `{nome_contato}` num nó de Mensagem espera que funcione igual aqui.
    """
    nome = (contact.get("nome") or "").strip()
    return _interp(texto or "", {
        "nome_contato": nome or contact.get("numero_whatsapp", ""),
        "primeiro_nome": nome.split(" ")[0] if nome else "",
        "numero": contact.get("numero_whatsapp", ""),
    })


async def send_one(db, campaign: dict, recipient: dict, token: str) -> tuple[str, str | None]:
    """Dispara para um destinatário. Devolve (status, erro).

    Nunca levanta: o runner precisa seguir para o próximo destinatário mesmo
    quando um número específico falha. Uma falha isolada é dado da campanha
    ("28 falhas"), não motivo para parar o disparo.
    """
    tenant_id = campaign["tenant_id"]
    contact = await db.contacts.find_one(
        {"id": recipient["contact_id"], "tenant_id": tenant_id}, {"_id": 0}
    )
    if not contact:
        return "falha", "Contato não existe mais"
    if contact.get("opt_out"):
        # Pediu para sair depois de a lista ter sido congelada.
        return "ignorado", "Contato optou por não receber campanhas"

    numero = contact.get("numero_whatsapp")
    if not numero:
        return "falha", "Contato sem número"

    conteudo = campaign.get("conteudo") or {}
    texto = render(conteudo.get("texto") or "", contact)

    session = await ensure_session(db, campaign, contact)
    session_id = session["id"]

    try:
        if conteudo.get("tipo") == "media":
            media_doc = await db.media_files.find_one(
                {"id": conteudo.get("media_id"), "tenant_id": tenant_id}, {"_id": 0}
            )
            if not media_doc:
                return "falha", "Mídia da campanha não encontrada"
            if media_doc.get("purged_at"):
                return "falha", "Mídia da campanha expirou pela retenção"
            # Lido do disco em blocos durante o envio — o arquivo nunca cabe
            # inteiro na memória, e numa campanha ele é reenviado a cada
            # destinatário.
            data_uri = media_store.DataUriStream(media_doc)
            await wuzapi.send_media(token, numero, media_doc["kind"], data_uri,
                                    texto, filename=media_doc["filename"])
            await log_message(db, session_id, tenant_id, "enviada", texto,
                              mtype=media_doc["kind"],
                              meta={"media": media_store.public_payload(media_doc),
                                    "campanha_id": campaign["id"],
                                    "campanha_nome": campaign.get("nome")})
        else:
            if not texto.strip():
                return "falha", "Campanha sem texto"
            await wuzapi.send_text(token, numero, texto)
            await log_message(db, session_id, tenant_id, "enviada", texto,
                              meta={"campanha_id": campaign["id"],
                                    "campanha_nome": campaign.get("nome")})
    except Exception as e:
        logger.warning("Falha no disparo da campanha %s para %s: %s",
                       campaign["id"], numero, e)
        return "falha", str(e)[:300]

    await db.campaign_recipients.update_one(
        {"id": recipient["id"]}, {"$set": {"session_id": session_id}}
    )
    await db.conversation_sessions.update_one(
        {"id": session_id}, {"$set": {"updated_at": _now()}}
    )
    return "enviado", None
