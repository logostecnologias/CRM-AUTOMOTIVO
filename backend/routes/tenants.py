import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field, StringConstraints
from pymongo.errors import DuplicateKeyError

from db import get_db
from auth import (require_super_admin, hash_password, create_access_token,
                  create_refresh_token, _set_auth_cookies, _cookie_secure)
import ai_runtime
import campaigns as campanhas
import plataforma
import whatsapp_client as whatsapp
import audit

router = APIRouter(prefix="/api/admin", tags=["super_admin"])

# Piso da senha inicial do admin da empresa. Não existe troca obrigatória no
# primeiro acesso, então a senha digitada aqui é a que o cliente vai usar por
# tempo indefinido: aceitar "1" era aceitar isso para sempre. A tela mostra o
# mesmo número e oferece uma senha gerada, mas a barreira é esta.
SENHA_MIN = 8

# Texto que sobrevive a espaço em volta: `min_length` sozinho aceita "  " como
# nome de dois caracteres, e a empresa nasceria sem nome legível na lista.
Nome = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]

# A marca que o cliente da empresa vê: ver `marcas.py`.
from marcas import Marca, MARCA_PADRAO  # noqa: E402

# Os planos saíram em 18/11/2026. O que sobrou deles são dois campos da própria
# empresa, definidos aqui pelo super admin: o teto de tokens de IA (custo da
# chave da plataforma, ver `ai_runtime._checar_cota`) e a retenção de mídia
# (ver `media_retention`). Nulo é "sem teto" / "padrão do servidor".


class TenantCreate(BaseModel):
    name: Nome
    admin_name: Nome
    admin_email: EmailStr
    admin_password: str = Field(min_length=SENHA_MIN, max_length=128)
    marca: Marca = MARCA_PADRAO


class TenantUpdate(BaseModel):
    name: Nome | None = None
    status: Literal["active", "suspended"] | None = None
    marca: Marca | None = None
    # Enviado como `null` limpa o campo (sem teto / padrão do servidor). Por
    # isso a rota lê só o que veio no corpo (`exclude_unset`), em vez de
    # descartar os nulos.
    limite_tokens_ia_mes: int | None = Field(default=None, ge=0, le=10_000_000_000)
    retencao_midia_dias: int | None = Field(default=None, ge=0, le=3650)


class SenhaNova(BaseModel):
    password: str = Field(min_length=SENHA_MIN, max_length=128)


@router.get("/tenants")
async def list_tenants(_=Depends(require_super_admin)):
    """Lista as empresas com a saúde de cada uma (ver `plataforma.saude`):
    quem administra, WhatsApp no ar, movimento, leads, vendas, IA e o que
    precisa de atenção. Tudo em agregações agrupadas, nenhuma consulta por
    empresa."""
    db = get_db()
    tenants = await db.tenants.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    por_id = await plataforma.saude(db, tenants)
    return [{**t, "saude": por_id.get(t["id"])} for t in tenants]


async def _resumo(db, tenant_id: str) -> dict:
    """Os números da operação de uma empresa, para a aba Resumo da ficha.
    Contagens simples por `tenant_id`, em paralelo: é uma empresa só."""
    q = {"tenant_id": tenant_id}
    (contatos, abertos, veiculos, disponiveis, agentes, robos, campanhas_n,
     disparos, conversas_abertas) = await asyncio.gather(
        db.contacts.count_documents(q),
        db.deals.count_documents({**q, "status": "aberto"}),
        db.veiculos.count_documents(q),
        db.veiculos.count_documents({**q, "status": "disponivel"}),
        db.ai_agents.count_documents({**q, "ativo": {"$ne": False}, "modo": {"$ne": "desligado"}}),
        db.bots.count_documents(q),
        db.campaigns.count_documents(q),
        campanhas.disparos_no_mes(db, tenant_id),
        db.conversation_sessions.count_documents(
            {**q, "status_atendimento": {"$in": ["aguardando", "em_atendimento"]}}),
    )
    return {
        "contatos": contatos,
        "negocios_abertos": abertos,
        "veiculos": veiculos,
        "veiculos_disponiveis": disponiveis,
        "agentes_ativos": agentes,
        "robos": robos,
        "campanhas": campanhas_n,
        "disparos_mes": disparos,
        "conversas_abertas": conversas_abertas,
    }


@router.get("/tenants/{tenant_id}")
async def tenant_detalhe(tenant_id: str, _=Depends(require_super_admin)):
    """A ficha de uma empresa para o super admin: resumo da operação, série de
    conversas, equipe com último acesso, conexões, consumo de IA contra o teto
    e o histórico de ações (auditoria + modo suporte)."""
    db = get_db()
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    usuarios, conexoes, por_id, resumo, serie, ia_mes, historico = await asyncio.gather(
        db.users.find({"tenant_id": tenant_id},
                      {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
                       "status": 1, "created_at": 1, "ultimo_acesso": 1})
        .sort("created_at", 1).to_list(500),
        db.whatsapp_connections.find(
            {"tenant_id": tenant_id},
            {"_id": 0, "id": 1, "nome": 1, "status": 1, "numero_exibicao": 1, "numero": 1,
             "canal": 1, "ultimo_erro": 1}).to_list(100),
        plataforma.saude(db, [tenant]),
        _resumo(db, tenant_id),
        plataforma.serie(db, [tenant_id]),
        ai_runtime.consumo_do_mes(db, tenant_id),
        plataforma.atividade(db, {tenant_id: tenant["name"]}, tenant_id=tenant_id, limite=40),
    )
    return {**tenant, "usuarios": usuarios, "conexoes": conexoes,
            "saude": por_id.get(tenant_id), "resumo": resumo, "serie": serie,
            "ia_mes": ia_mes, "historico": historico}


@router.post("/tenants")
async def create_tenant(body: TenantCreate, admin=Depends(require_super_admin)):
    db = get_db()
    email = body.admin_email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    tenant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    tenant = {
        "id": tenant_id,
        "name": body.name,
        "marca": body.marca,
        "status": "active",
        "limite_tokens_ia_mes": None,
        "created_at": now,
    }
    await db.tenants.insert_one(tenant)
    try:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "name": body.admin_name,
            "email": email,
            "role": "tenant_admin",
            "status": "active",
            "password_hash": hash_password(body.admin_password),
            "created_at": now,
        })
    except DuplicateKeyError:
        # A empresa é gravada antes do admin, então quem perde a corrida no
        # índice único de `users.email` deixaria uma empresa sem nenhum
        # usuário: ela apareceria na lista, ninguém entraria nela e nem o
        # cliente nem o suporte saberiam por quê. Acontece com duas abas
        # abertas, F5 no meio do envio ou retry de rede: a checagem acima não
        # cobre esses casos, porque entre ela e o insert existe uma janela.
        await db.tenants.delete_one({"id": tenant_id})
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    tenant.pop("_id", None)
    await audit.registrar(db, ator=admin, acao="tenant.create", tenant_id=tenant_id,
                          alvo=body.name, meta={"admin_email": email, "marca": body.marca})
    return tenant


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: TenantUpdate, admin=Depends(require_super_admin)):
    db = get_db()
    update = body.model_dump(exclude_unset=True)
    # Nome, status e marca não aceitam nulo: só os dois campos de teto usam o
    # nulo como valor ("sem teto" / "padrão do servidor").
    for campo in ("name", "status", "marca"):
        if campo in update and update[campo] is None:
            update.pop(campo)
    if not update:
        return {"ok": True}
    atual = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "excluida_em": 1})
    if atual and atual.get("excluida_em"):
        # Reativar por aqui deixaria a marca de exclusão de pé e o worker
        # apagaria uma empresa "ativa" no fim da carência.
        raise HTTPException(status_code=409, detail="Empresa excluída: restaure antes de alterar")
    res = await db.tenants.update_one({"id": tenant_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    # Toda decisão do super admin sobre a empresa deixa rastro (ZZ-21).
    await audit.registrar(db, ator=admin, acao="tenant.update",
                          tenant_id=tenant_id, meta=update)
    return tenant


@router.post("/tenants/{tenant_id}/users/{user_id}/senha")
async def redefinir_senha(tenant_id: str, user_id: str, body: SenhaNova,
                          admin=Depends(require_super_admin)):
    """O super admin define uma senha nova para alguém da empresa.

    Era o que mais obrigava a entrar em modo suporte: o cliente esqueceu a
    senha, e o banco só guarda o hash. A senha nova aparece uma vez na tela,
    para ser passada adiante, e derruba as sessões abertas daquela pessoa
    (bump de `token_version`, igual à troca feita pelo admin da empresa).
    """
    db = get_db()
    alvo = await db.users.find_one({"id": user_id, "tenant_id": tenant_id},
                                   {"_id": 0, "id": 1, "email": 1})
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta empresa")
    await db.users.update_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"$set": {"password_hash": hash_password(body.password)},
         "$inc": {"token_version": 1}},
    )
    await audit.registrar(db, ator=admin, acao="user.senha_redefinida", tenant_id=tenant_id,
                          alvo=alvo.get("email"), meta={"user_id": user_id})
    return {"ok": True}


# Tudo que morre com a empresa, numa lista só. Estava escrito como uma
# sequência de `delete_many` no corpo da rota, e o jeito de essa sequência ficar
# defasada é criar uma coleção nova em outro módulo e não lembrar daqui: foi
# assim que a agenda, os agentes de IA, as mídias, os departamentos, o acesso
# por conexão e o próprio histórico de mensagens ficaram para trás. Coleção
# nova com `tenant_id` entra aqui no mesmo commit em que nasce.
#
# Fora da lista de propósito:
#   impersonation_log   é auditoria do super admin, e auditoria que desaparece
#                       junto com o objeto auditado não serve de nada
#   processed_messages  não tem `tenant_id` (é dedup por id de mensagem) e
#                       expira sozinha por TTL em 7 dias
COLECOES_DA_EMPRESA = (
    "users",
    "bots",
    "flows",
    "flow_versions",
    "whatsapp_connections",
    "user_connection_access",
    "departments",
    "conversation_sessions",
    # O histórico das conversas e a ficha dos arquivos. O binário em disco fica
    # para a varredura de órfãos do `media_retention`: sem o documento ela
    # deixa de reconhecer o arquivo e o recolhe na passagem seguinte, 24h
    # depois. Apagar arquivo aqui dentro trocaria uma exclusão de banco por uma
    # operação de disco que pode falhar no meio.
    "messages_log",
    "media_files",
    "contacts",
    "contact_notes",
    "contact_field_defs",
    # Campanhas e a lista de destinatários de cada uma. Sem isto o runner
    # continuaria encontrando campanha em "enviando" de uma empresa que não
    # existe mais, e tentaria disparar por uma conexão já apagada.
    "campaigns",
    "campaign_recipients",
    "pipelines",
    "deals",
    "deal_events",
    "meta_conversoes",
    "avisos_grupo",
    "catalogos",
    "meta_eventos",
    "activities",
    # Agenda: grade, catálogo e o que estava marcado. O `agenda_worker` varre
    # os agendamentos de todas as empresas de uma vez, então lembrete de
    # empresa excluída continuaria saindo por uma conexão que já não existe.
    "appointments",
    "resources",
    "services",
    "scheduling_settings",
    # Agentes de IA e o consumo medido deles.
    "ai_agents",
    "ai_usage",
    "ai_estoque",
    # Telefone: a conta Twilio (com o Auth Token cifrado) e o registro das
    # ligações, que guarda o número de quem ligou.
    "voz_config",
    "ligacoes",
    # Formulários de site e cada envio recebido, com o que a pessoa digitou.
    "formularios",
    "formulario_respostas",
    # Estoque de veículos. As fotos são `media_files` (já na lista acima).
    "veiculos",
)


# Exclusão com carência (19/11/2026). Até aqui "Excluir" apagava tudo na hora,
# sem volta, e uma empresa em uso (R3 COMPANY, 18/11) foi apagada por engano:
# sem backup, o que voltou veio de recuperação forense dos arquivos do banco, e
# negócios, agenda e formulário se perderam. Agora excluir só suspende e marca a
# data; dá para restaurar com um clique durante a carência, e o worker
# `exclusao_empresas` apaga de verdade depois dela.
CARENCIA_DIAS = 30


def apagar_em(excluida_em: str) -> str:
    return (datetime.fromisoformat(excluida_em) + timedelta(days=CARENCIA_DIAS)).isoformat()


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, admin=Depends(require_super_admin)):
    """Marca a empresa como excluída. Não apaga nada: suspende (login e sessões
    abertas param na hora, como na suspensão) e some da lista normal."""
    db = get_db()
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    if tenant.get("excluida_em"):
        return {"ok": True, "apagar_em": apagar_em(tenant["excluida_em"])}
    agora = datetime.now(timezone.utc).isoformat()
    await db.tenants.update_one({"id": tenant_id}, {"$set": {
        "status": "suspended",
        "excluida_em": agora,
        "excluida_por": admin.get("email"),
        # Para a restauração devolver a empresa como estava, inclusive se ela
        # já estava suspensa antes de ser excluída.
        "status_antes_da_exclusao": tenant.get("status") or "active",
    }})
    await audit.registrar(db, ator=admin, acao="tenant.delete", tenant_id=tenant_id,
                          alvo=tenant.get("name"),
                          meta={"carencia_dias": CARENCIA_DIAS, "apagar_em": apagar_em(agora)})
    return {"ok": True, "apagar_em": apagar_em(agora)}


@router.post("/tenants/{tenant_id}/restaurar")
async def restaurar_tenant(tenant_id: str, admin=Depends(require_super_admin)):
    db = get_db()
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(status_code=404, detail="Empresa não encontrada: a carência já passou")
    if not tenant.get("excluida_em"):
        raise HTTPException(status_code=409, detail="Esta empresa não está excluída")
    status = tenant.get("status_antes_da_exclusao") or "active"
    await db.tenants.update_one({"id": tenant_id}, {
        "$set": {"status": status},
        "$unset": {"excluida_em": "", "excluida_por": "", "status_antes_da_exclusao": ""},
    })
    await audit.registrar(db, ator=admin, acao="tenant.restore", tenant_id=tenant_id,
                          alvo=tenant.get("name"), meta={"status": status})
    return await db.tenants.find_one({"id": tenant_id}, {"_id": 0})


async def apagar_empresa(db, tenant_id: str, ator: dict | None = None) -> dict:
    """Apaga a empresa e tudo dela, de verdade. Só o worker de exclusão chama,
    depois da carência. Devolve o que saiu, por coleção."""
    alvo = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1})
    # Best-effort: cancela a assinatura do nosso app nas contas da Meta antes
    # de apagar as conexões (ZZ-14). Sem isto a Meta continua entregando o
    # webhook de números de uma empresa que não existe mais, e cada evento
    # desses vira uma consulta ao banco que nunca casa com nada. Falha aqui
    # não impede a exclusão: a coleção é apagada logo abaixo de qualquer jeito.
    async for conn in db.whatsapp_connections.find(
        {"tenant_id": tenant_id, "phone_number_id": {"$ne": None}}, {"_id": 0},
    ):
        try:
            cred = whatsapp.credencial(conn)
            if cred:
                await whatsapp.desassinar_webhook(cred)
        except Exception:
            pass
    await db.tenants.delete_one({"id": tenant_id})
    apagados = {}
    for colecao in COLECOES_DA_EMPRESA:
        res = await db[colecao].delete_many({"tenant_id": tenant_id})
        if res.deleted_count:
            apagados[colecao] = res.deleted_count
    await audit.registrar(
        db, ator=ator, acao="tenant.purge", tenant_id=tenant_id,
        alvo=(alvo or {}).get("name"), meta={"apagados": apagados},
    )
    # O que saiu, por coleção: também vai para a auditoria.
    return apagados


@router.post("/tenants/{tenant_id}/impersonate")
async def impersonate(tenant_id: str, response: Response, super_admin=Depends(require_super_admin)):
    """SA vira tenant_admin desse tenant. Guarda o token SA original em cookie
    separado para restauração posterior via /auth/exit-impersonation."""
    import uuid
    db = get_db()
    tenant = await db.tenants.find_one({"id": tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.impersonation_log.insert_one({
        "id": log_id,
        "super_admin_id": super_admin["id"],
        "tenant_id": tenant_id,
        "iniciado_em": now,
        "finalizado_em": None,
    })
    # Issue new access as tenant_admin (borrowing SA identity but with tenant scope).
    # `tv` é o do próprio Super Admin: trocar a senha dele invalida também as
    # sessões de suporte abertas em nome dele (ZZ-09).
    access = create_access_token(super_admin["id"], super_admin["email"], "tenant_admin",
                                 tenant_id, log_id, token_version=super_admin.get("token_version", 0))
    refresh = create_refresh_token(super_admin["id"], super_admin.get("token_version", 0))
    _set_auth_cookies(response, access, refresh)
    secure = _cookie_secure()
    response.set_cookie("impersonation_id", log_id, httponly=True, secure=secure,
                        samesite="lax", max_age=12 * 3600, path="/")
    response.set_cookie("impersonated_role", "super_admin", httponly=False, secure=secure,
                        samesite="lax", max_age=12 * 3600, path="/")
    return {"ok": True, "tenant_name": tenant["name"], "impersonation_id": log_id}


@router.get("/visao")
async def visao_geral(_=Depends(require_super_admin)):
    """A visão geral da plataforma: o que precisa de atenção, volume e
    resultado contra a semana anterior, consumo de IA, quem mais usa e as
    últimas ações (ver `plataforma`)."""
    db = get_db()
    # Empresa excluída (na carência) não entra nos números da plataforma.
    todas = await db.tenants.find({}, {"_id": 0}).to_list(5000)
    tenants = [t for t in todas if not t.get("excluida_em")]
    ids = [t["id"] for t in tenants]
    # Os nomes vêm de todas: a linha do tempo mostra também o que se fez numa
    # empresa que depois foi excluída.
    nomes = {t["id"]: t["name"] for t in todas}
    por_id, serie, linha_do_tempo = await asyncio.gather(
        plataforma.saude(db, tenants),
        plataforma.serie(db, ids),
        plataforma.atividade(db, nomes),
    )
    return plataforma.visao(tenants, por_id, serie, linha_do_tempo)
