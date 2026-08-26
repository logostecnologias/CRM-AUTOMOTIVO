"""API de agendamento: configuração, serviços, profissionais e horários marcados.

Permissão segue a regra do resto do CRM (ver CLAUDE.md): **operar é de quem
atende, configurar é do admin**. Uma recepcionista marca, remarca e cancela o
dia inteiro: barrar isso no `require_tenant_admin` transformaria a agenda numa
tela que só o dono usa. Já mexer na grade de horários, no catálogo de serviços e
nos feriados muda o que o bot promete a todos os contatos, e isso é configuração.

Ler a agenda é liberado para a equipe inteira, sem recorte por profissional: quem
atende o telefone precisa ver a agenda de todo mundo para dizer "a Ana tem às
15h". O recorte por profissional existe como **filtro** na tela, não como
barreira, e o admin, como pediu o cliente, vê tudo por padrão.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import agenda as dominio
import agenda_worker
import contatos_csv
from auth import require_tenant_admin, require_tenant_member
from db import get_db

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

# Teto de agendamentos devolvidos numa janela. A tela mostra semana ou mês de
# uma equipe; acima disso é exportação, não visualização, e uma consulta sem
# teto num tenant grande traria o histórico inteiro pelo túnel.
MAX_AGENDAMENTOS = 1000


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

class BloqueioIn(BaseModel):
    data: str
    motivo: str | None = None


class ConfigIn(BaseModel):
    fuso: str | None = None
    passo_min: int | None = Field(default=None, ge=5, le=240)
    intervalo_min: int | None = Field(default=None, ge=0, le=240)
    antecedencia_min_horas: float | None = Field(default=None, ge=0, le=720)
    antecedencia_max_dias: int | None = Field(default=None, ge=1, le=365)
    cancelamento_min_horas: float | None = Field(default=None, ge=0, le=720)
    lembrete_ativo: bool | None = None
    lembrete_horas: float | None = Field(default=None, ge=1, le=168)
    bloqueios: list[BloqueioIn] | None = None
    mensagem_confirmacao: str | None = None
    mensagem_lembrete: str | None = None
    mensagem_cancelamento: str | None = None


@router.get("/config")
async def ver_config(user=Depends(require_tenant_member)):
    db = get_db()
    config = await dominio.configuracao(db, user["tenant_id"])
    # Os modelos de mensagem padrão vão junto: a tela precisa mostrar o que sai
    # hoje, e um campo vazio com placeholder faria o cliente achar que nenhuma
    # mensagem é enviada.
    config["mensagens_padrao"] = agenda_worker.MENSAGENS
    return config


@router.put("/config")
async def salvar_config(body: ConfigIn, user=Depends(require_tenant_admin)):
    db = get_db()
    campos = {k: v for k, v in body.model_dump().items() if v is not None}
    if "bloqueios" in campos:
        campos["bloqueios"] = [
            {"data": dominio._dia(b["data"]).isoformat(),
             "motivo": (b.get("motivo") or "").strip() or None}
            for b in campos["bloqueios"]
        ]
    if campos.get("fuso"):
        # Conferido na entrada: um fuso inválido gravado só apareceria como
        # "nenhum horário disponível", que manda o suporte procurar na grade.
        antes = campos["fuso"]
        if str(dominio.fuso_de({"fuso": antes})) != antes:
            raise HTTPException(status_code=400, detail=f"Fuso desconhecido: {antes}")
    campos["updated_at"] = _now()
    await db.scheduling_settings.update_one(
        {"tenant_id": user["tenant_id"]}, {"$set": campos}, upsert=True)
    return await dominio.configuracao(db, user["tenant_id"])


# ---------------------------------------------------------------------------
# Serviços
# ---------------------------------------------------------------------------

class ServicoIn(BaseModel):
    nome: str
    duracao_min: int = Field(ge=5, le=1440)
    preco: float | None = Field(default=None, ge=0)
    descricao: str | None = None
    cor: str | None = None
    ativo: bool = True
    ordem: int = 0
    # Vazio = qualquer profissional atende. É o padrão, para um profissional
    # novo não nascer silenciosamente fora de todos os serviços.
    recursos: list[str] = []


@router.get("/services")
async def listar_servicos(todos: bool = True, user=Depends(require_tenant_member)):
    db = get_db()
    filtro = {"tenant_id": user["tenant_id"]}
    if not todos:
        filtro["ativo"] = True
    return await db.services.find(filtro, {"_id": 0}) \
        .sort([("ordem", 1), ("nome", 1)]).to_list(300)


@router.post("/services")
async def criar_servico(body: ServicoIn, user=Depends(require_tenant_admin)):
    db = get_db()
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Dê um nome ao serviço")
    await _nome_livre(db, "services", user["tenant_id"], nome, "um serviço")
    await _valida_recursos(db, user["tenant_id"], body.recursos)
    doc = {"id": str(uuid.uuid4()), "tenant_id": user["tenant_id"],
           **body.model_dump(), "nome": nome,
           "created_at": _now(), "updated_at": _now()}
    await db.services.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.patch("/services/{service_id}")
async def editar_servico(service_id: str, body: ServicoIn,
                         user=Depends(require_tenant_admin)):
    db = get_db()
    await _get(db, "services", service_id, user["tenant_id"], "Serviço")
    await _nome_livre(db, "services", user["tenant_id"], body.nome.strip(),
                      "um serviço", exceto=service_id)
    await _valida_recursos(db, user["tenant_id"], body.recursos)
    campos = {**body.model_dump(), "nome": body.nome.strip(), "updated_at": _now()}
    await db.services.update_one(
        {"id": service_id, "tenant_id": user["tenant_id"]}, {"$set": campos})
    return await _get(db, "services", service_id, user["tenant_id"], "Serviço")


@router.delete("/services/{service_id}")
async def remover_servico(service_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    await _get(db, "services", service_id, user["tenant_id"], "Serviço")
    await _sem_futuro(db, user["tenant_id"], {"service_id": service_id},
                      "Esse serviço ainda tem")
    await db.services.delete_one({"id": service_id, "tenant_id": user["tenant_id"]})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Profissionais / recursos
# ---------------------------------------------------------------------------

class ExcecaoIn(BaseModel):
    data: str
    fechado: bool = True
    motivo: str | None = None
    janelas: list[dict] = []


class RecursoIn(BaseModel):
    nome: str
    tipo: str = Field(default="pessoa", pattern="^(pessoa|sala|equipamento)$")
    descricao: str | None = None
    cor: str | None = None
    ativo: bool = True
    # Liga o profissional a um usuário do sistema. Serve ao filtro "minha
    # agenda", e é opcional porque nem todo profissional tem login.
    user_id: str | None = None
    # None = herda o intervalo da empresa. Zero é um valor legítimo e diferente
    # de "herda", por isso não pode ser representado por ausência.
    intervalo_min: int | None = Field(default=None, ge=0, le=240)
    grade: list | None = None
    excecoes: list[ExcecaoIn] = []


@router.get("/resources")
async def listar_recursos(todos: bool = True, user=Depends(require_tenant_member)):
    db = get_db()
    filtro = {"tenant_id": user["tenant_id"]}
    if not todos:
        filtro["ativo"] = True
    return await db.resources.find(filtro, {"_id": 0}).sort("nome", 1).to_list(300)


@router.post("/resources")
async def criar_recurso(body: RecursoIn, user=Depends(require_tenant_admin)):
    db = get_db()
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Dê um nome ao profissional")
    await _nome_livre(db, "resources", user["tenant_id"], nome, "um profissional")
    await _valida_usuario(db, user["tenant_id"], body.user_id)
    doc = {"id": str(uuid.uuid4()), "tenant_id": user["tenant_id"],
           **_campos_recurso(body), "nome": nome,
           "created_at": _now(), "updated_at": _now()}
    await db.resources.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.patch("/resources/{resource_id}")
async def editar_recurso(resource_id: str, body: RecursoIn,
                         user=Depends(require_tenant_admin)):
    db = get_db()
    await _get(db, "resources", resource_id, user["tenant_id"], "Profissional")
    await _nome_livre(db, "resources", user["tenant_id"], body.nome.strip(),
                      "um profissional", exceto=resource_id)
    await _valida_usuario(db, user["tenant_id"], body.user_id)
    campos = {**_campos_recurso(body), "nome": body.nome.strip(), "updated_at": _now()}
    await db.resources.update_one(
        {"id": resource_id, "tenant_id": user["tenant_id"]}, {"$set": campos})
    return await _get(db, "resources", resource_id, user["tenant_id"], "Profissional")


@router.delete("/resources/{resource_id}")
async def remover_recurso(resource_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    await _get(db, "resources", resource_id, user["tenant_id"], "Profissional")
    await _sem_futuro(db, user["tenant_id"], {"resource_id": resource_id},
                      "Esse profissional ainda tem")
    await db.resources.delete_one({"id": resource_id, "tenant_id": user["tenant_id"]})
    return {"ok": True}


def _campos_recurso(body: RecursoIn) -> dict:
    campos = body.model_dump()
    # Grade ausente vira a comercial padrão, não uma agenda vazia: um
    # profissional recém-criado sem nenhum horário não apareceria em lugar
    # nenhum, e a causa seria invisível.
    campos["grade"] = dominio.validar_grade(
        body.grade if body.grade is not None else dominio.GRADE_PADRAO)
    campos["excecoes"] = [_excecao(e) for e in campos.get("excecoes") or []]
    return campos


def _excecao(e: dict) -> dict:
    """Uma exceção de data validada com o mesmo rigor da grade semanal.

    Reaproveita `validar_grade` pondo as janelas no primeiro dia de uma grade de
    sete: é a mesma checagem (HH:MM, sem inversão, sem sobreposição) e não vale
    uma segunda implementação para divergir depois. O erro é reetiquetado com a
    data: o texto de `validar_grade` diria "Segunda", e mandaria a pessoa
    procurar o problema no dia da semana errado.
    """
    data = dominio._dia(e["data"]).isoformat()
    try:
        janelas = dominio.validar_grade([e.get("janelas") or [], [], [], [], [], [], []])[0]
    except HTTPException as erro:
        detalhe = str(erro.detail).split(":", 1)[-1].strip()
        raise HTTPException(status_code=400, detail=f"Exceção de {data}: {detalhe}")
    return {"data": data, "fechado": bool(e.get("fechado", True)),
            "motivo": (e.get("motivo") or "").strip() or None, "janelas": janelas}


# ---------------------------------------------------------------------------
# Horários livres
# ---------------------------------------------------------------------------

@router.get("/slots")
async def horarios(service_id: str, dia: str, resource_id: str | None = None,
                   user=Depends(require_tenant_member)):
    """Os horários livres de um dia. É o que a tela de marcação manual consulta.

    Mesma função que o bot e o agente de IA usam (`agenda.horarios_do_dia`)
    duas implementações fariam a tela oferecer um horário que o bot recusa.
    """
    db = get_db()
    tenant_id = user["tenant_id"]
    servico = await _get(db, "services", service_id, tenant_id, "Serviço")
    config = await dominio.configuracao(db, tenant_id)
    recursos = await _recursos_para(db, tenant_id, servico, resource_id)
    return {
        "dia": dia,
        "fuso": config["fuso"],
        "horarios": await dominio.horarios_do_dia(
            db, tenant_id, recursos=recursos, servico=servico, dia=dia, config=config),
    }


@router.get("/slots/dias")
async def dias_com_vaga(service_id: str, resource_id: str | None = None,
                        a_partir_de: str | None = None, limite: int = 10,
                        user=Depends(require_tenant_member)):
    db = get_db()
    tenant_id = user["tenant_id"]
    servico = await _get(db, "services", service_id, tenant_id, "Serviço")
    config = await dominio.configuracao(db, tenant_id)
    recursos = await _recursos_para(db, tenant_id, servico, resource_id)
    return await dominio.proximos_dias(
        db, tenant_id, recursos=recursos, servico=servico, config=config,
        a_partir_de=a_partir_de, limite_dias=max(1, min(limite, 30)))


async def _recursos_para(db, tenant_id, servico, resource_id):
    if resource_id:
        r = await _get(db, "resources", resource_id, tenant_id, "Profissional")
        return [r]
    recursos = await dominio.recursos_ativos(db, tenant_id, servico)
    if not recursos:
        raise HTTPException(
            status_code=400,
            detail=f"Nenhum profissional ativo atende {servico['nome']}")
    return recursos


# ---------------------------------------------------------------------------
# Agendamentos
# ---------------------------------------------------------------------------

class AgendamentoIn(BaseModel):
    service_id: str
    resource_id: str
    inicio: str
    # Um contato existente, ou os dados para criar um na hora: quem atende o
    # telefone não vai abrir outra tela para cadastrar antes de marcar.
    contact_id: str | None = None
    contact_nome: str | None = None
    contact_numero: str | None = None
    observacoes: str | None = None
    # Encaixe fora da grade ou dentro da antecedência mínima. Nunca dispensa a
    # checagem de sobreposição: ver `agenda.agendar`.
    forcar: bool = False
    # Manda a confirmação pelo WhatsApp. Ligado por padrão: um agendamento que
    # o cliente não sabe que existe é uma falta esperando para acontecer.
    avisar: bool = True


@router.get("/appointments")
async def listar_agendamentos(de: str | None = None, ate: str | None = None,
                              resource_id: str | None = None,
                              service_id: str | None = None,
                              contact_id: str | None = None,
                              status: str | None = None,
                              user=Depends(require_tenant_member)):
    """A agenda de uma janela. `de`/`ate` são instantes ISO, como no resto do
    sistema; sem eles, a semana a partir de agora."""
    db = get_db()
    agora = dominio._agora()
    inicio = dominio._instante(de, "Data inicial") if de else agora - timedelta(days=1)
    fim = dominio._instante(ate, "Data final") if ate else agora + timedelta(days=7)

    filtro = {"tenant_id": user["tenant_id"],
              "inicio": {"$gte": dominio._iso(inicio), "$lt": dominio._iso(fim)}}
    if resource_id:
        filtro["resource_id"] = resource_id
    if service_id:
        filtro["service_id"] = service_id
    if contact_id:
        filtro["contact_id"] = contact_id
    if status:
        filtro["status"] = {"$in": status.split(",")}

    itens = await db.appointments.find(filtro, {"_id": 0}) \
        .sort([("inicio", 1), ("_id", 1)]).to_list(MAX_AGENDAMENTOS)
    config = await dominio.configuracao(db, user["tenant_id"])
    return {"fuso": config["fuso"], "total": len(itens), "items": itens,
            "truncada": len(itens) >= MAX_AGENDAMENTOS}


@router.get("/summary")
async def resumo(de: str | None = None, ate: str | None = None,
                 user=Depends(require_tenant_member)):
    """Contadores por status na janela, numa agregação só.

    Cinco contagens seriam cinco idas ao banco para produzir cinco números que
    cabem numa linha da tela: mesmo raciocínio de `atividades.resumo`.
    """
    db = get_db()
    agora = dominio._agora()
    inicio = dominio._instante(de, "Data inicial") if de else agora
    fim = dominio._instante(ate, "Data final") if ate else agora + timedelta(days=7)
    cursor = db.appointments.aggregate([
        {"$match": {"tenant_id": user["tenant_id"],
                    "inicio": {"$gte": dominio._iso(inicio), "$lt": dominio._iso(fim)}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ])
    por_status = {s: 0 for s in dominio.STATUS}
    async for linha in cursor:
        por_status[linha["_id"]] = linha["n"]
    por_status["total"] = sum(por_status[s] for s in dominio.STATUS)
    return por_status


@router.post("/appointments")
async def marcar(body: AgendamentoIn, user=Depends(require_tenant_member)):
    db = get_db()
    tenant_id = user["tenant_id"]
    servico = await _get(db, "services", body.service_id, tenant_id, "Serviço")
    recurso = await _get(db, "resources", body.resource_id, tenant_id, "Profissional")
    contato = await _contato(db, tenant_id, body)
    config = await dominio.configuracao(db, tenant_id)

    doc = await dominio.agendar(
        db, tenant_id, recurso=recurso, servico=servico, contato=contato,
        inicio=body.inicio, config=config, origem="manual",
        criado_por=user["id"], observacoes=body.observacoes, forcar=body.forcar)

    if body.avisar:
        # Não bloqueia a resposta com o resultado do envio: a marcação já está
        # feita, e uma conexão fora do ar não pode fazer a tela dizer que o
        # horário não foi reservado. `avisar` nunca levanta.
        doc["aviso_enviado"] = await agenda_worker.avisar(
            db, tenant_id, doc, "confirmacao", config)
    return doc


@router.post("/appointments/{appointment_id}/cancel")
async def cancelar_agendamento(appointment_id: str, motivo: str | None = None,
                               avisar: bool = True,
                               user=Depends(require_tenant_member)):
    db = get_db()
    tenant_id = user["tenant_id"]
    doc = await dominio.cancelar(db, tenant_id, appointment_id,
                                 por=user["id"], motivo=motivo)
    if avisar:
        await agenda_worker.avisar(db, tenant_id, doc, "cancelamento")
    return doc


class StatusIn(BaseModel):
    status: str


@router.patch("/appointments/{appointment_id}/status")
async def mudar_status(appointment_id: str, body: StatusIn,
                       user=Depends(require_tenant_member)):
    """Marca compareceu (`concluido`) ou faltou. É daqui que sai a taxa de falta,
    e por isso o estado é registrado por uma pessoa, não deduzido do relógio: um
    atendimento que passou da hora pode ter acontecido, ter sido remarcado na
    recepção, ou o cliente ter faltado, e só quem estava lá sabe qual."""
    db = get_db()
    return await dominio.mudar_status(db, user["tenant_id"], appointment_id, body.status)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

async def _nome_livre(db, colecao: str, tenant_id: str, nome: str, rotulo: str,
                      exceto: str = None):
    """Recusa nome repetido dentro da empresa.

    É a trava que realmente segura contra duplicata. A tela também impede clique
    repetido, mas ela não cobre duas abas abertas, um F5 no meio do envio nem um
    retry de rede: nesses casos chegam duas requisições idênticas e sem esta
    checagem nascem dois cadastros. Foi assim que um duplo clique em "Salvar"
    criou dois profissionais.

    Comparação sem caixa: "Ana" e "ana" são a mesma pessoa, e deixar as duas
    passarem devolve o problema pela porta dos fundos. O nome vai escapado
    porque entra numa regex do Mongo, e um "(" digitado derrubaria a consulta.
    """
    igual = await db[colecao].find_one(
        {"tenant_id": tenant_id,
         "nome": {"$regex": f"^{re.escape(nome)}$", "$options": "i"}},
        {"_id": 0, "id": 1},
    )
    if igual and igual["id"] != exceto:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe {rotulo} com o nome \"{nome}\". "
                   "Use outro nome ou edite o que já está cadastrado.")


async def _get(db, colecao: str, item_id: str, tenant_id: str, rotulo: str) -> dict:
    doc = await db[colecao].find_one({"id": item_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"{rotulo} não encontrado")
    return doc


async def _valida_recursos(db, tenant_id: str, ids: list):
    """Um id de outra empresa colado no corpo amarraria o serviço a um
    profissional que a empresa não deveria nem saber que existe."""
    for rid in ids or []:
        if not await db.resources.find_one({"id": rid, "tenant_id": tenant_id},
                                           {"_id": 0, "id": 1}):
            raise HTTPException(status_code=400, detail="Profissional inválido")


async def _valida_usuario(db, tenant_id: str, user_id: str | None):
    if user_id and not await db.users.find_one({"id": user_id, "tenant_id": tenant_id},
                                               {"_id": 0, "id": 1}):
        raise HTTPException(status_code=400, detail="Usuário inválido")


async def _sem_futuro(db, tenant_id: str, filtro: dict, prefixo: str):
    """Recusa a exclusão quando ainda há horário marcado à frente.

    Mesma decisão da etapa de funil com negócios: apagar em silêncio deixaria os
    agendamentos apontando para um serviço ou profissional inexistente, e eles
    sumiriam da tela sem nunca terem sido atendidos nem cancelados. Quem quer
    parar de oferecer desativa: o passado continua legível e o futuro continua
    marcado.
    """
    n = await db.appointments.count_documents({
        "tenant_id": tenant_id, **filtro,
        "status": {"$in": [dominio.STATUS_AGENDADO, dominio.STATUS_CONFIRMADO]},
        "inicio": {"$gte": dominio._iso(dominio._agora())},
    })
    if n:
        raise HTTPException(
            status_code=409,
            detail=f"{prefixo} {n} horário(s) marcado(s) à frente. "
                   "Cancele ou atenda antes de excluir, ou desative, "
                   "que preserva o histórico.")


async def _contato(db, tenant_id: str, body: AgendamentoIn) -> dict:
    """O contato do agendamento: o escolhido, o já cadastrado pelo número, ou um
    novo. Nunca dois registros para o mesmo número: ele é a identidade do
    contato em todo o sistema."""
    if body.contact_id:
        return await _get(db, "contacts", body.contact_id, tenant_id, "Contato")
    if not (body.contact_numero or "").strip():
        raise HTTPException(status_code=400,
                            detail="Escolha um contato ou informe nome e WhatsApp")
    numero, erro = contatos_csv.normaliza_numero(body.contact_numero)
    if erro:
        raise HTTPException(status_code=400, detail=f"WhatsApp inválido: {erro}")

    existente = await db.contacts.find_one(
        {"tenant_id": tenant_id, "numero_whatsapp": numero}, {"_id": 0})
    if existente:
        return existente
    contato = {
        "id": str(uuid.uuid4()), "tenant_id": tenant_id,
        "numero_whatsapp": numero,
        "nome": (body.contact_nome or "").strip() or numero,
        "origem": "agendamento manual",
        "created_at": _now(),
    }
    await db.contacts.insert_one(dict(contato))
    contato.pop("_id", None)
    return contato
