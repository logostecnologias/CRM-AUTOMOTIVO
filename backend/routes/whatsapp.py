"""Conexões de WhatsApp: uma por número da Cloud API oficial.

O que era pareamento por QR virou cadastro de credencial. A diferença não é só
de tela: antes a conexão nascia vazia e ganhava vida ao escanear um código, com
estado ("pareando") que só a WuzAPI conhecia. Aqui a conexão é um par
(`phone_number_id`, token de acesso) que ou vale ou não vale, e descobrir isso
é uma chamada à Meta.

Três decisões:

  - **A credencial é validada antes de ser gravada.** Mesma regra da chave de
    IA. Gravar primeiro deixaria a tela dizendo "conectado" com um token morto,
    e o cliente descobriria na primeira mensagem de um contato real. A chamada
    de teste é a mesma que o monitor de saúde usa depois.

  - **Assinar o webhook faz parte de conectar.** Sem `POST /{waba_id}/
    subscribed_apps` a conta existe, o token funciona, o envio funciona e
    **nada entra**. O sintoma (sai mas não entra) parece problema de webhook e
    manda o suporte para o lado errado, então isso acontece aqui, uma vez, no
    momento em que o cliente cadastra o número.

  - **O token nunca volta para o navegador.** Fica cifrado em repouso e sai
    apenas como máscara, exatamente como a chave de IA. Quem copia esse token
    manda mensagem em nome da empresa para a base inteira de contatos dela.
"""
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import cripto
import whatsapp_client as whatsapp
import wuzapi_client as wuzapi
from auth import require_tenant_admin, get_current_user, accessible_connection_ids
from db import get_db
from plan_limits import enforce_plan_limit

logger = logging.getLogger("zappzen.whatsapp")

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


def _now():
    return datetime.now(timezone.utc).isoformat()


# Campos que NUNCA vão para o navegador (ZZ-06). `token_cifrado` é a credencial
# de envio da conta do cliente: mesmo cifrado, ele não tem por que trafegar.
#
# `wuzapi_hmac` entrou pela mesma porta e é ainda mais direto: é a chave com
# que o webhook do canal não oficial é assinado. Quem a tem forja mensagem em
# qualquer conversa desta conexão, porque o receptor a aceita como prova de
# origem.
_CAMPOS_OCULTOS = ("_id", "token_cifrado", "wuzapi_hmac")


def _is_admin(user: dict) -> bool:
    return user.get("role") in ("tenant_admin", "super_admin")


def _serialize(conn: dict | None, is_admin: bool) -> dict | None:
    """A conexão como ela pode sair para o cliente.

    Os identificadores da Meta (`phone_number_id`, `waba_id`) ficam só para
    admin: não são segredo, mas também não servem ao atendente, e são o que
    alguém precisaria para tentar falar com a conta por fora.
    """
    if not conn:
        return conn
    saida = {k: v for k, v in conn.items() if k not in _CAMPOS_OCULTOS}
    if not is_admin:
        saida.pop("phone_number_id", None)
        saida.pop("waba_id", None)
        saida.pop("token_mascara", None)
        # Mesma regra do canal não oficial: o id da instância é o que alguém
        # precisaria para falar com ela por fora, e o QR corrente **pareia o
        # número** — mostrá-lo ao atendente entregaria a conta de WhatsApp da
        # empresa a quem só devia responder conversas.
        saida.pop("wuzapi_id", None)
        saida.pop("qrcode_atual", None)
    return saida


async def _buscar(db, conn_id: str, tenant_id: str) -> dict:
    conn = await db.whatsapp_connections.find_one({"id": conn_id, "tenant_id": tenant_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    return conn


# ---------- CRUD ----------

# O vínculo com bots mora no bot (`bots.connection_id`), não aqui: é lá que se
# escolhe a conexão, e a regra de um bot de cada tipo por conexão é validada em
# bot_binding.
class ConnectionIn(BaseModel):
    nome: str
    departamento_padrao_id: str | None = None
    # `cloud_api` é o padrão e continua sendo: conexão criada antes desta
    # versão não tem o campo, e ler a ausência como "não oficial" mudaria o
    # canal de conexões em produção sem ninguém pedir. Mesma decisão do
    # `formato` do nó de Menu.
    canal: str = whatsapp.CANAL_CLOUD


class WuzapiIn(BaseModel):
    """A credencial do canal não oficial: a instância e o token dela.

    Não há `phone_number_id` nem WABA aqui — quem identifica a conexão na
    WuzAPI é o par (instância, token). A instância é criada fora do produto,
    de propósito: criá-la pela tela exigiria que o ZappZen guardasse o token de
    **administração** da WuzAPI, que apaga qualquer instância do servidor,
    inclusive as de outros sistemas que compartilham aquela ponte.
    """
    wuzapi_id: str
    token: str | None = None  # ausente = manter o que já está gravado


class ConnectionPatch(BaseModel):
    nome: str | None = None
    departamento_padrao_id: str | None = None


class CredenciaisIn(BaseModel):
    phone_number_id: str
    waba_id: str
    token: str | None = None  # ausente = manter o que já está gravado


@router.get("/connections")
async def list_connections(user: dict = Depends(get_current_user)):
    if not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Usuário sem empresa vinculada")
    db = get_db()
    q: dict = {"tenant_id": user["tenant_id"]}
    if user["role"] not in ("tenant_admin", "super_admin"):
        access = await db.user_connection_access.find(
            {"tenant_id": user["tenant_id"], "user_id": user["id"]}, {"_id": 0}
        ).to_list(500)
        q["id"] = {"$in": [a["whatsapp_connection_id"] for a in access]}
    rows = await db.whatsapp_connections.find(q).sort("created_at", 1).to_list(200)
    admin = _is_admin(user)
    return [_serialize(r, admin) for r in rows]


@router.post("/connections")
async def create_connection(body: ConnectionIn, user=Depends(require_tenant_admin)):
    db = get_db()
    await enforce_plan_limit(db, user["tenant_id"], "whatsapp_connections", "max_conexoes", "conexões WhatsApp")
    conn = {
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "nome": body.nome,
        "departamento_padrao_id": body.departamento_padrao_id,
        "canal": (body.canal if body.canal in (whatsapp.CANAL_CLOUD, whatsapp.CANAL_WUZAPI)
                  else whatsapp.CANAL_CLOUD),
        "phone_number_id": None,
        "waba_id": None,
        # Canal não oficial: a instância na WuzAPI, a chave com que assinamos
        # o webhook dela, e o QR corrente durante o pareamento.
        "wuzapi_id": None,
        "wuzapi_hmac": None,
        "qrcode_atual": None,
        "token_cifrado": None,
        "token_mascara": None,
        "numero": None,
        "numero_exibicao": None,
        "nome_verificado": None,
        "qualidade": None,
        "status": "desconectado",
        "ultimo_erro": None,
        "last_webhook_event_at": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.whatsapp_connections.insert_one(conn)
    return _serialize(conn, True)


@router.get("/connections/{conn_id}")
async def get_connection(conn_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    # ZZ-06: a rota por id também respeita o escopo do atendente. Sem isto, um
    # agente sem nenhuma conexão liberada lia qualquer uma da empresa por id.
    accessible = await accessible_connection_ids(db, user)
    if accessible is not None and conn_id not in accessible:
        raise HTTPException(status_code=403, detail="Sem acesso a esta conexão")
    return _serialize(conn, _is_admin(user))


@router.patch("/connections/{conn_id}")
async def update_connection(conn_id: str, body: ConnectionPatch, user=Depends(require_tenant_admin)):
    db = get_db()
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if upd:
        upd["updated_at"] = _now()
        await db.whatsapp_connections.update_one(
            {"id": conn_id, "tenant_id": user["tenant_id"]}, {"$set": upd}
        )
    conn = await db.whatsapp_connections.find_one(
        {"id": conn_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    return _serialize(conn, True)


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    await _buscar(db, conn_id, user["tenant_id"])
    await db.whatsapp_connections.delete_one({"id": conn_id, "tenant_id": user["tenant_id"]})
    await db.user_connection_access.delete_many({"whatsapp_connection_id": conn_id})
    return {"ok": True}


# ---------- Credenciais e verificação ----------

async def _aplicar_perfil(db, conn_id: str, perfil: dict, extra: dict | None = None) -> dict:
    """Grava na conexão o que a Meta respondeu sobre o número."""
    exibicao = perfil.get("display_phone_number") or ""
    mudanca = {
        "numero": "".join(c for c in exibicao if c.isdigit()) or None,
        "numero_exibicao": exibicao or None,
        "nome_verificado": perfil.get("verified_name"),
        "qualidade": perfil.get("quality_rating"),
        "status": "conectado",
        "ultimo_erro": None,
        "updated_at": _now(),
        **(extra or {}),
    }
    await db.whatsapp_connections.update_one({"id": conn_id}, {"$set": mudanca})
    conn = await db.whatsapp_connections.find_one({"id": conn_id}, {"_id": 0})
    return _serialize(conn, True)


@router.post("/connections/{conn_id}/credenciais")
async def salvar_credenciais(conn_id: str, body: CredenciaisIn, user=Depends(require_tenant_admin)):
    """Cadastra (ou troca) o número da Cloud API desta conexão.

    O token só é exigido na primeira vez: trocar apenas o `phone_number_id`
    reaproveita o que está guardado, porque devolver o token à tela para o
    cliente recolá-lo o faria trafegar sem necessidade.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])

    token = (body.token or "").strip()
    if not token:
        if not conn.get("token_cifrado"):
            raise HTTPException(status_code=400, detail="Informe o token de acesso da Meta")
        try:
            token = cripto.decifrar(conn["token_cifrado"])
        except cripto.CredencialError as e:
            raise HTTPException(status_code=400, detail=str(e))

    cred = whatsapp.Credencial(body.phone_number_id.strip(), token, body.waba_id.strip())

    # Validação antes de gravar: é o que impede a tela dizer "conectado" com
    # credencial morta. O erro da Meta vai inteiro para o cliente porque ele é
    # específico o suficiente para dizer o que corrigir (número não registrado,
    # token sem permissão, id de outra conta).
    try:
        perfil = await whatsapp.perfil_numero(cred)
    except whatsapp.WhatsAppError as e:
        raise HTTPException(status_code=400, detail=f"Não foi possível validar o número: {e}")

    aviso = None
    try:
        await whatsapp.assinar_webhook(cred)
    except whatsapp.WhatsAppError as e:
        # Assinar pode falhar por permissão faltando no token
        # (whatsapp_business_management) sem que o envio esteja quebrado. A
        # conexão fica gravada e o aviso aparece na tela, porque sem assinatura
        # nenhuma mensagem entra e isso precisa ficar explícito.
        aviso = (f"Número validado, mas não foi possível assinar o webhook: {e}. "
                 "Sem isso as mensagens recebidas não chegam.")

    bloco = cripto.cifrar(token)
    saida = await _aplicar_perfil(db, conn_id, perfil, {
        "phone_number_id": cred.phone_number_id,
        "waba_id": cred.waba_id,
        "token_cifrado": bloco,
        "token_mascara": bloco["mascara"],
        "webhook_assinado": aviso is None,
    })
    if aviso:
        saida["aviso"] = aviso
    return saida


@router.post("/connections/{conn_id}/verificar")
async def verificar(conn_id: str, user=Depends(require_tenant_admin)):
    """Reconsulta a Meta com a credencial já gravada.

    É o "Conectar" da tela antiga sem QR nenhum: serve para conferir se o token
    continua válido, e para atualizar nome verificado e nota de qualidade, que
    mudam sozinhos do lado da Meta.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    cred = whatsapp.credencial(conn)
    if not cred:
        raise HTTPException(status_code=400, detail="Conexão sem credencial cadastrada")
    try:
        perfil = await whatsapp.perfil_numero(cred)
    except whatsapp.WhatsAppError as e:
        await db.whatsapp_connections.update_one(
            {"id": conn_id},
            {"$set": {"status": "erro", "ultimo_erro": str(e), "updated_at": _now()}},
        )
        raise HTTPException(status_code=400, detail=str(e))
    return await _aplicar_perfil(db, conn_id, perfil)


# ---------------------------------------------------------------------------
# Canal não oficial (WuzAPI): credencial, pareamento por QR e sessão
#
# A diferença de forma com a Cloud API é toda aqui. Lá conectar é cadastrar uma
# credencial que ou vale ou não vale; aqui existe **sessão**, e ela nasce de um
# QR lido por um celular — então há estado a acompanhar (`pareando`,
# `conectado`, `desconectado`) e ele chega por webhook, não por consulta.
# ---------------------------------------------------------------------------

def _exigir_wuzapi(conn: dict) -> None:
    if (conn.get("canal") or whatsapp.CANAL_CLOUD) != whatsapp.CANAL_WUZAPI:
        raise HTTPException(
            status_code=400,
            detail="Esta conexão é da Cloud API oficial; o pareamento por QR "
                   "só existe no canal não oficial",
        )


def _url_webhook_wuzapi() -> str:
    """A URL que a instância chama quando chega mensagem.

    Vai sem os ids na rota de propósito. A WuzAPI já foi observada entregando
    evento de mensagem real na rota simples mesmo com URL por conexão
    configurada, e o receptor sem rota resolve a conexão pelo `userID` do
    payload — que é justamente o id da instância. Uma URL só, portanto, e o
    roteamento sai do corpo, como no receptor da Cloud API.
    """
    base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL não configurada: sem ela não há como dizer "
                   "à WuzAPI para onde mandar as mensagens recebidas",
        )
    return f"{base}/api/webhooks/wuzapi"


@router.post("/connections/{conn_id}/wuzapi")
async def salvar_wuzapi(conn_id: str, body: WuzapiIn, user=Depends(require_tenant_admin)):
    """Cadastra a instância da WuzAPI desta conexão.

    Mesma regra da credencial da Cloud API, pelos mesmos motivos: **valida
    antes de gravar** (uma chamada real de status), e configura o webhook no
    mesmo passo — sem ele o número envia e não recebe nada, que é o sintoma
    que manda o suporte procurar no lugar errado.

    A chave de assinatura é gerada aqui, uma por conexão. Ela nunca volta para
    a tela (ver `_CAMPOS_OCULTOS`): é com ela que o receptor distingue um
    evento da WuzAPI de um POST de qualquer um na internet.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    _exigir_wuzapi(conn)

    token = (body.token or "").strip()
    if not token:
        if not conn.get("token_cifrado"):
            raise HTTPException(status_code=400, detail="Informe o token da instância")
        try:
            token = cripto.decifrar(conn["token_cifrado"])
        except cripto.CredencialError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        estado = await wuzapi.connection_state(token)
    except wuzapi.WuzapiError as e:
        raise HTTPException(status_code=400,
                            detail=f"Não foi possível falar com a instância: {e}")

    # A chave é reaproveitada quando já existe: trocá-la a cada gravação
    # invalidaria os eventos em vôo, que a WuzAPI reentrega — eles chegariam
    # assinados com a chave anterior e seriam recusados como forjados.
    hmac_key = conn.get("wuzapi_hmac") or secrets.token_hex(32)

    aviso = None
    try:
        await wuzapi.set_webhook(token, _url_webhook_wuzapi())
    except wuzapi.WuzapiError as e:
        aviso = (f"Instância validada, mas o webhook não foi configurado: {e} "
                 "Sem isso as mensagens recebidas não chegam.")

    bloco = cripto.cifrar(token)
    await db.whatsapp_connections.update_one({"id": conn_id}, {"$set": {
        "wuzapi_id": body.wuzapi_id.strip(),
        "wuzapi_hmac": hmac_key,
        "token_cifrado": bloco,
        "token_mascara": bloco["mascara"],
        "webhook_assinado": aviso is None,
        "status": "conectado" if estado.get("loggedIn") else "desconectado",
        "numero": (estado.get("jid") or "").split("@")[0].split(":")[0] or None,
        "ultimo_erro": None,
        "updated_at": _now(),
    }})
    saida = _serialize(await db.whatsapp_connections.find_one({"id": conn_id}), True)
    if aviso:
        saida["aviso"] = aviso
    return saida


@router.post("/connections/{conn_id}/wuzapi/conectar")
async def conectar_wuzapi(conn_id: str, user=Depends(require_tenant_admin)):
    """Inicia a sessão. Se não houver pareamento, a WuzAPI passa a emitir QR.

    O QR **não** volta nesta resposta: ele nasce assíncrono, como evento de
    webhook, e chega alguns instantes depois. A tela consulta `/qr` em seguida,
    que é também o que a faz mostrar um QR novo quando o anterior expira — o
    código do WhatsApp vence em ~20 segundos.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    _exigir_wuzapi(conn)
    cred = whatsapp.credencial(conn)
    if not cred:
        raise HTTPException(status_code=400, detail="Cadastre a instância antes de conectar")
    try:
        await wuzapi.connect(cred.token)
    except wuzapi.WuzapiError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.whatsapp_connections.update_one(
        {"id": conn_id}, {"$set": {"status": "pareando", "updated_at": _now()}})
    return {"ok": True, "status": "pareando"}


@router.get("/connections/{conn_id}/wuzapi/qr")
async def qr_wuzapi(conn_id: str, user=Depends(require_tenant_admin)):
    """O QR corrente, para o celular ler.

    Duas fontes, e as duas importam: o que o webhook gravou (`qrcode_atual`) e
    o que a instância devolve agora. A consulta direta vem primeiro porque o
    código expira em segundos, e mostrar um QR vencido faz a pessoa tentar ler
    algo que nunca vai funcionar.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    _exigir_wuzapi(conn)
    cred = whatsapp.credencial(conn)
    if not cred:
        raise HTTPException(status_code=400, detail="Cadastre a instância antes de parear")

    qr, estado = None, {}
    try:
        estado = await wuzapi.connection_state(cred.token)
        if not estado.get("loggedIn"):
            qr = await wuzapi.fetch_qr(cred.token)
    except wuzapi.WuzapiError:
        # Falha de consulta não apaga o QR que o webhook trouxe: ele pode
        # continuar válido, e devolver vazio aqui esvaziaria a tela no meio do
        # pareamento.
        pass
    qr = qr or conn.get("qrcode_atual")

    if estado.get("loggedIn"):
        numero = (estado.get("jid") or "").split("@")[0].split(":")[0] or None
        await db.whatsapp_connections.update_one({"id": conn_id}, {"$set": {
            "status": "conectado", "qrcode_atual": None,
            "numero": numero,
            "numero_exibicao": f"+{numero}" if numero else None,
            "updated_at": _now(),
        }})
        return {"status": "conectado", "qr": None, "numero": numero}
    return {"status": conn.get("status") or "pareando", "qr": qr}


@router.post("/connections/{conn_id}/wuzapi/desconectar")
async def desconectar_wuzapi(conn_id: str, user=Depends(require_tenant_admin)):
    """Desconecta mantendo o pareamento: reconectar depois não pede QR novo."""
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    _exigir_wuzapi(conn)
    cred = whatsapp.credencial(conn)
    if cred:
        try:
            await wuzapi.disconnect_instance(cred.token)
        except wuzapi.WuzapiError as e:
            logger.warning("Desconexão da instância %s falhou: %s", conn_id, e)
    await db.whatsapp_connections.update_one(
        {"id": conn_id},
        {"$set": {"status": "desconectado", "qrcode_atual": None, "updated_at": _now()}})
    return {"ok": True, "status": "desconectado"}


@router.post("/connections/{conn_id}/wuzapi/sair")
async def sair_wuzapi(conn_id: str, user=Depends(require_tenant_admin)):
    """Apaga a sessão no WhatsApp: o próximo uso exige ler o QR de novo.

    Separado de `desconectar` de propósito. São operações que parecem a mesma
    coisa e não são: uma cai a conexão e a outra **desvincula o aparelho**, e
    confundi-las custa uma ida ao celular do cliente.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    _exigir_wuzapi(conn)
    cred = whatsapp.credencial(conn)
    if cred:
        try:
            await wuzapi.logout_instance(cred.token)
        except wuzapi.WuzapiError as e:
            logger.warning("Logout da instância %s falhou: %s", conn_id, e)
    await db.whatsapp_connections.update_one({"id": conn_id}, {"$set": {
        "status": "desconectado", "qrcode_atual": None,
        "numero": None, "numero_exibicao": None, "updated_at": _now(),
    }})
    return {"ok": True, "status": "desconectado"}


@router.get("/connections/{conn_id}/templates")
async def templates(conn_id: str, user: dict = Depends(get_current_user)):
    """Modelos aprovados da conta, que é o que a campanha oferece para escolher.

    Não é `require_tenant_admin`: quem monta campanha é a equipe, e a lista é
    só leitura do que já existe na conta do cliente. O escopo de conexão do
    atendente continua valendo.
    """
    db = get_db()
    conn = await _buscar(db, conn_id, user["tenant_id"])
    acessiveis = await accessible_connection_ids(db, user)
    if acessiveis is not None and conn_id not in acessiveis:
        raise HTTPException(status_code=403, detail="Sem acesso a esta conexão")
    cred = whatsapp.credencial(conn)
    if not cred:
        raise HTTPException(status_code=400, detail="Conexão sem credencial cadastrada")
    try:
        lista = await whatsapp.listar_templates(cred)
    except whatsapp.WhatsAppError as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar modelos: {e}")
    return [
        {
            "nome": t.get("name"),
            "idioma": (t.get("language") or ""),
            "categoria": t.get("category"),
            "corpo": next((c.get("text") for c in (t.get("components") or [])
                           if (c.get("type") or "").upper() == "BODY"), ""),
            "variaveis": whatsapp.variaveis_do_template(t),
            "tem_midia": any((c.get("format") or "").upper() in ("IMAGE", "VIDEO", "DOCUMENT")
                             for c in (t.get("components") or [])
                             if (c.get("type") or "").upper() == "HEADER"),
        }
        for t in lista
    ]


# ---------- Legacy compat (returns first connection) ----------

async def _first_conn(db, tenant_id: str):
    return await db.whatsapp_connections.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}, sort=[("created_at", 1)]
    )


@router.get("/status")
async def legacy_status(user=Depends(require_tenant_admin)):
    db = get_db()
    conn = await _first_conn(db, user["tenant_id"])
    if not conn:
        return {"status": "desconectado", "id": None, "numero": None,
                "departamento_padrao_id": None}
    return _serialize(conn, True)


@router.get("/connection")
async def legacy_connection(user=Depends(require_tenant_admin)):
    return await legacy_status(user)
