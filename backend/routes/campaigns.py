"""API de campanhas.

As rotas aqui só mudam estado e devolvem números — o disparo em si é do
`campaign_runner`, que roda fora do ciclo de request. Uma campanha de 2.000
contatos leva minutos ou horas de cadência proposital: prendê-la numa request
faria o navegador desistir muito antes de a campanha acabar.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

import campaigns as campanhas
import datas
import media_store
from auth import require_tenant_admin
from db import get_db

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class PublicoIn(BaseModel):
    tipo: str = Field(default="todos", pattern="^(todos|tags|selecionados)$")
    tags: list[str] = []
    contact_ids: list[str] = []


class TemplateIn(BaseModel):
    """O modelo aprovado que a campanha dispara.

    `corpo` é guardado junto de propósito, mesmo sendo uma cópia do que está na
    Meta: é dele que sai o texto do histórico de cada conversa, e a lista de
    campanhas mostra a prévia sem precisar consultar a Meta a cada abertura de
    tela. `variaveis` é um valor por `{{n}}` do corpo, e cada um passa pelo
    mesmo `render` do texto livre.
    """
    nome: str = ""
    idioma: str = "pt_BR"
    corpo: str = ""
    variaveis: list[str] = Field(default_factory=list)
    media_id: str | None = None


class ConteudoIn(BaseModel):
    # `template` é o padrão: fora da janela de 24h o WhatsApp só entrega modelo
    # aprovado, e num público de campanha quase todo mundo está fora dela.
    tipo: str = Field(default="template", pattern="^(template|text|media)$")
    texto: str = ""
    media_id: str | None = None
    template: TemplateIn = TemplateIn()


class CadenciaIn(BaseModel):
    # 12/min é o default por ser cadência de gente, não de robô. O teto de 60
    # não é técnico: é o que mantém a conexão livre para quem está conversando
    # enquanto o disparo corre, e o que evita gastar a vazão do número inteira
    # numa campanha só.
    por_minuto: int = Field(default=12, ge=1, le=60)


class CampaignIn(BaseModel):
    nome: str
    whatsapp_connection_id: str
    conteudo: ConteudoIn = ConteudoIn()
    publico: PublicoIn = PublicoIn()
    cadencia: CadenciaIn = CadenciaIn()
    agendada_para: str | None = None
    # O que acontece quando o contato responde ao disparo. "aguardando" manda
    # direto para a fila humana; "bot" roda o fluxo do bot escolhido, para
    # qualificar antes de ocupar um atendente.
    resposta_modo: str = Field(default="aguardando", pattern="^(aguardando|bot)$")
    bot_id: str | None = None
    departamento_id: str | None = None


EDITAVEL = ("rascunho", "agendada", "pausada")


async def _get(db, campaign_id: str, tenant_id: str) -> dict:
    doc = await db.campaigns.find_one({"id": campaign_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    return doc


async def _validar_vinculos(db, tenant_id: str, body: CampaignIn):
    """Conexão, bot e departamento têm de ser da própria empresa.

    Sem isto, um id de outra empresa colado no corpo faria a campanha sair
    pela conexão de outro cliente — o pior vazamento possível neste sistema.
    """
    conn = await db.whatsapp_connections.find_one(
        {"id": body.whatsapp_connection_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}
    )
    if not conn:
        raise HTTPException(status_code=400, detail="Conexão de WhatsApp inválida")
    if body.resposta_modo == "bot":
        if not body.bot_id:
            raise HTTPException(status_code=400, detail="Escolha o bot que vai atender as respostas")
        bot = await db.bots.find_one({"id": body.bot_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1})
        if not bot:
            raise HTTPException(status_code=400, detail="Bot inválido")
    if body.departamento_id:
        dept = await db.departments.find_one(
            {"id": body.departamento_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}
        )
        if not dept:
            raise HTTPException(status_code=400, detail="Departamento inválido")
    if body.conteudo.tipo == "template" and not body.conteudo.template.nome:
        # Sem modelo escolhido a campanha falharia num destinatário por vez, e
        # o erro só apareceria depois de a lista inteira estar materializada.
        raise HTTPException(status_code=400, detail="Escolha o modelo aprovado da campanha")
    if body.conteudo.tipo == "media":
        if not body.conteudo.media_id:
            raise HTTPException(status_code=400, detail="Anexe o arquivo da campanha")
        media = await db.media_files.find_one(
            {"id": body.conteudo.media_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}
        )
        if not media:
            raise HTTPException(status_code=400, detail="Arquivo da campanha não encontrado")


@router.get("")
async def list_campaigns(user=Depends(require_tenant_admin)):
    db = get_db()
    return await db.campaigns.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)


@router.post("")
async def create_campaign(body: CampaignIn, user=Depends(require_tenant_admin)):
    db = get_db()
    await _validar_vinculos(db, user["tenant_id"], body)
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "nome": body.nome,
        # Gravado em cada campanha: é o campo que decide por onde ela sai. Hoje
        # só existe um canal, mas ele continua aqui porque a alternativa (a
        # Marketing Messages API, ou um segundo provedor) chegaria sem forma de
        # distinguir as campanhas antigas das novas.
        "canal": "cloud_api",
        "whatsapp_connection_id": body.whatsapp_connection_id,
        "conteudo": body.conteudo.model_dump(),
        "publico": body.publico.model_dump(),
        "cadencia": body.cadencia.model_dump(),
        "agendada_para": datas.para_utc(body.agendada_para, "Data de agendamento"),
        "resposta_modo": body.resposta_modo,
        "bot_id": body.bot_id if body.resposta_modo == "bot" else None,
        "departamento_id": body.departamento_id,
        "status": "rascunho",
        "motivo_pausa": None,
        "totais": {"total": 0, "enviados": 0, "falhas": 0, "ignorados": 0},
        "criado_por": user["email"],
        "iniciada_em": None,
        "concluida_em": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.campaigns.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    doc["metricas"] = await _metricas(db, campaign_id)
    return doc


async def _metricas(db, campaign_id: str) -> dict:
    """Contagens por estado numa consulta agrupada, não uma por coluna.

    Mesma razão do `summary` da Central: o que domina não é o volume, é a ida
    e volta até o banco — que aqui passa por túnel SSH.
    """
    cursor = db.campaign_recipients.aggregate([
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {"_id": "$status", "n": {"$sum": 1},
                    "respostas": {"$sum": {"$cond": ["$respondeu", 1, 0]}}}},
    ])
    por_status, respostas = {s: 0 for s in campanhas.DESTINO_STATUS}, 0
    async for row in cursor:
        if row["_id"] in por_status:
            por_status[row["_id"]] = row["n"]
        respostas += row.get("respostas", 0)
    return {**por_status, "respostas": respostas}


@router.patch("/{campaign_id}")
async def update_campaign(campaign_id: str, body: CampaignIn, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    if doc["status"] not in EDITAVEL:
        raise HTTPException(
            status_code=409,
            detail=f"Campanha {doc['status']} não pode ser editada",
        )
    await _validar_vinculos(db, user["tenant_id"], body)
    campos = body.model_dump()
    campos["bot_id"] = body.bot_id if body.resposta_modo == "bot" else None
    campos["agendada_para"] = datas.para_utc(body.agendada_para, "Data de agendamento")
    campos["updated_at"] = _now()
    await db.campaigns.update_one({"id": campaign_id, "tenant_id": user["tenant_id"]},
                                  {"$set": campos})
    return await _get(db, campaign_id, user["tenant_id"])


@router.post("/media")
async def upload_campaign_media(file: UploadFile = File(...), user=Depends(require_tenant_admin)):
    """Guarda o arquivo da campanha e devolve o `media_id` para o formulário.

    Gravado direto em disco conforme chega, como todo upload do sistema — o
    arquivo nunca passa inteiro pela memória. `session_id` fica nulo: este
    arquivo não pertence a nenhuma conversa, e é reenviado a cada
    destinatário.
    """
    db = get_db()
    try:
        doc = await media_store.store_stream(
            db, user["tenant_id"], None, user["id"],
            file.filename, file.content_type, file.read,
        )
    except media_store.MediaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return media_store.public_payload(doc)


class PublicoPreviewIn(BaseModel):
    publico: PublicoIn


@router.post("/audience/preview")
async def audience_preview(body: PublicoPreviewIn, user=Depends(require_tenant_admin)):
    """Quantos contatos o público alcança — já descontando quem pediu para sair."""
    db = get_db()
    total = await campanhas.audience_count(db, user["tenant_id"], body.publico.model_dump())
    return {"total": total, "limite": campanhas.MAX_PUBLICO}


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    if doc["status"] in ("enviando", "concluida"):
        raise HTTPException(status_code=409, detail=f"Campanha já está {doc['status']}")

    try:
        await campanhas.materialize_recipients(db, doc)
    except campanhas.CampaignError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pendentes = await db.campaign_recipients.count_documents(
        {"campaign_id": campaign_id, "status": "pendente"}
    )
    if not pendentes:
        raise HTTPException(status_code=400, detail="Nenhum destinatário pendente nesta campanha")

    agendada = doc.get("agendada_para")
    # Agendamento no passado (ou já vencido enquanto a campanha era rascunho)
    # dispara agora, em vez de ficar preso esperando uma hora que não volta.
    futuro = bool(agendada and agendada > _now())
    await db.campaigns.update_one(
        {"id": campaign_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "agendada" if futuro else "enviando",
                  "iniciada_em": None if futuro else _now(),
                  "motivo_pausa": None, "updated_at": _now()}},
    )
    return {"ok": True, "status": "agendada" if futuro else "enviando", "pendentes": pendentes}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    if doc["status"] not in ("enviando", "agendada"):
        raise HTTPException(status_code=409, detail=f"Campanha {doc['status']} não está em disparo")
    await db.campaigns.update_one(
        {"id": campaign_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "pausada", "motivo_pausa": "Pausada manualmente", "updated_at": _now()}},
    )
    return {"ok": True}


@router.post("/{campaign_id}/resume")
async def resume_campaign(campaign_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    if doc["status"] != "pausada":
        raise HTTPException(status_code=409, detail="Só campanha pausada pode ser retomada")
    pendentes = await db.campaign_recipients.count_documents(
        {"campaign_id": campaign_id, "status": "pendente"}
    )
    if not pendentes:
        await db.campaigns.update_one(
            {"id": campaign_id}, {"$set": {"status": "concluida", "concluida_em": _now()}}
        )
        return {"ok": True, "status": "concluida"}
    await db.campaigns.update_one(
        {"id": campaign_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "enviando", "motivo_pausa": None, "updated_at": _now()}},
    )
    return {"ok": True, "status": "enviando", "pendentes": pendentes}


@router.post("/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    if doc["status"] in ("concluida", "cancelada"):
        raise HTTPException(status_code=409, detail=f"Campanha já está {doc['status']}")
    await db.campaigns.update_one(
        {"id": campaign_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "cancelada", "motivo_pausa": None,
                  "concluida_em": _now(), "updated_at": _now()}},
    )
    # Quem não recebeu vira "ignorado", e não fica pendente para sempre: sem
    # isto os totais da campanha nunca fechariam com o público.
    res = await db.campaign_recipients.update_many(
        {"campaign_id": campaign_id, "status": {"$in": ["pendente", "enviando"]}},
        {"$set": {"status": "ignorado", "erro": "Campanha cancelada", "claimed_at": None}},
    )
    await db.campaigns.update_one(
        {"id": campaign_id}, {"$inc": {"totais.ignorados": res.modified_count}}
    )
    return {"ok": True, "descartados": res.modified_count}


@router.get("/{campaign_id}/recipients")
async def list_recipients(campaign_id: str, status: str | None = None, skip: int = 0,
                          limit: int = 100, user=Depends(require_tenant_admin)):
    db = get_db()
    await _get(db, campaign_id, user["tenant_id"])
    q: dict = {"campaign_id": campaign_id, "tenant_id": user["tenant_id"]}
    if status:
        q["status"] = status
    limit = max(1, min(limit, 500))
    rows = await db.campaign_recipients.find(q, {"_id": 0}).sort("created_at", 1) \
        .skip(max(0, skip)).limit(limit).to_list(limit)
    return {"total": await db.campaign_recipients.count_documents(q), "items": rows}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    doc = await _get(db, campaign_id, user["tenant_id"])
    if doc["status"] == "enviando":
        raise HTTPException(status_code=409, detail="Pause a campanha antes de excluir")
    await db.campaigns.delete_one({"id": campaign_id, "tenant_id": user["tenant_id"]})
    await db.campaign_recipients.delete_many(
        {"campaign_id": campaign_id, "tenant_id": user["tenant_id"]}
    )
    # As conversas geradas ficam: são histórico real de atendimento, e apagar
    # a campanha não desfaz as mensagens que o contato recebeu.
    return {"ok": True}
