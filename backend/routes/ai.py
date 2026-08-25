"""Conexão da conta de IA da empresa e os agentes que atendem por ela.

Uma conexão por empresa (`ai_connections`, chaveada por `tenant_id`). O
provedor não permite que um SaaS de terceiro use a assinatura do cliente por
OAuth — Anthropic, OpenAI e Google fecharam esse caminho no primeiro trimestre
de 2026 — então a credencial é uma chave de API que o cliente gera no console
do provedor e cola aqui. A tela leva ele direto à página certa (`console_url`
do catálogo) para que isso leve segundos, não uma busca na documentação.

Tudo aqui é `require_tenant_admin`: é configuração e é credencial. A regra do
projeto de abrir a base para o atendente (`require_tenant_member`) vale para
contatos, funil e agenda — não para o segredo que paga a conta da empresa.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import get_db
from auth import require_tenant_admin
import ai_agents
import ai_client
import ai_credentials
import ai_runtime

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class ConexaoIn(BaseModel):
    provedor: str
    modelo: str | None = None
    # Ausente = manter a chave já guardada. É o que permite trocar só o modelo
    # sem obrigar o cliente a gerar uma chave nova (ele não tem a antiga: nós
    # nunca a devolvemos).
    chave_api: str | None = None


def _publica(conexao: dict | None) -> dict | None:
    """O documento como a tela pode vê-lo. A chave cifrada e o texto cifrado
    nunca saem daqui — só a máscara."""
    if not conexao:
        return None
    credencial = conexao.get("credencial") or {}
    return {
        "id": conexao["id"],
        "provedor": conexao["provedor"],
        "provedor_rotulo": ai_client.PROVEDORES.get(conexao["provedor"], {}).get("rotulo", conexao["provedor"]),
        "modelo": conexao["modelo"],
        "mascara": credencial.get("mascara", ""),
        "status": conexao.get("status", "erro"),
        "ultimo_erro": conexao.get("ultimo_erro"),
        "verificada_em": conexao.get("verificada_em"),
        "created_at": conexao.get("created_at"),
    }


@router.get("/providers")
async def listar_provedores(_=Depends(require_tenant_admin)):
    """Catálogo para a tela: provedores, modelos, preço e o link do console."""
    return ai_client.catalogo_publico()


@router.get("/connection")
async def obter_conexao(user=Depends(require_tenant_admin)):
    db = get_db()
    conexao = await db.ai_connections.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})
    return {
        "conexao": _publica(conexao),
        "consumo": await ai_runtime.consumo_do_mes(db, user["tenant_id"]),
        # A tela precisa saber se existe rede de segurança: sem conexão própria
        # e sem chave da plataforma, o agente simplesmente não responde, e o
        # cliente tem que saber disso antes de ligar o agente.
        "plataforma_disponivel": ai_runtime._credencial_plataforma() is not None,
    }


@router.put("/connection")
async def salvar_conexao(body: ConexaoIn, user=Depends(require_tenant_admin)):
    """Valida contra o provedor **antes** de gravar.

    Guardar primeiro e testar depois deixaria a tela dizendo "conectada" com
    uma chave que não funciona, e o cliente só descobriria na primeira mensagem
    de um contato real — quando já é tarde. O teste custa fração de centavo.
    """
    if body.provedor not in ai_client.PROVEDORES:
        raise HTTPException(status_code=400, detail="Provedor desconhecido")

    db = get_db()
    atual = await db.ai_connections.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})

    if body.chave_api:
        chave = body.chave_api.strip()
        prefixo = ai_client.PROVEDORES[body.provedor]["prefixo_chave"]
        if not chave.startswith(prefixo):
            # Checagem de formato antes de gastar uma chamada: o engano comum é
            # colar a chave de um provedor no campo do outro.
            raise HTTPException(
                status_code=400,
                detail=f"Esta não parece uma chave de {ai_client.PROVEDORES[body.provedor]['rotulo']} (deveria começar com \"{prefixo}\").",
            )
    elif atual and atual.get("provedor") == body.provedor:
        try:
            chave = ai_credentials.decifrar(atual.get("credencial") or {})
        except ai_credentials.CredencialError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        # Trocar de provedor sem informar a chave nova não tem como funcionar:
        # a guardada é do provedor antigo.
        raise HTTPException(status_code=400, detail="Informe a chave de API do provedor escolhido")

    modelo = body.modelo or ai_client.modelo_padrao(body.provedor)
    try:
        ai_client.modelo_de(body.provedor, modelo)
    except ai_client.IAError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        await ai_client.validar(body.provedor, chave, modelo)
    except ai_client.IAError as e:
        # 400, não 502: quem precisa agir é o cliente (chave, saldo, acesso ao
        # modelo), e a mensagem de `_traduz_erro` já diz o quê.
        raise HTTPException(status_code=400, detail=str(e))

    try:
        credencial = ai_credentials.cifrar(chave)
    except ai_credentials.CredencialError as e:
        raise HTTPException(status_code=500, detail=str(e))

    doc = {
        "id": (atual or {}).get("id") or str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "provedor": body.provedor,
        "modelo": modelo,
        "credencial": credencial,
        "status": "conectada",
        "ultimo_erro": None,
        "verificada_em": _now(),
        "created_at": (atual or {}).get("created_at") or _now(),
        "updated_at": _now(),
    }
    await db.ai_connections.update_one(
        {"tenant_id": user["tenant_id"]}, {"$set": doc}, upsert=True
    )
    return _publica(doc)


@router.post("/connection/test")
async def testar_conexao(user=Depends(require_tenant_admin)):
    """Reteste da conexão já salva — a chave pode ter sido revogada no console
    do provedor, ou a conta pode ter ficado sem saldo, sem nada mudar aqui.

    O resultado é gravado: é o `status` que a tela mostra e, mais importante, é
    o que explica por que o agente parou de responder.
    """
    db = get_db()
    conexao = await db.ai_connections.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})
    if not conexao:
        raise HTTPException(status_code=404, detail="Nenhuma conta de IA conectada")

    try:
        await ai_client.validar_conexao(conexao)
    except (ai_client.IAError, ai_credentials.CredencialError) as e:
        await db.ai_connections.update_one(
            {"tenant_id": user["tenant_id"]},
            {"$set": {"status": "erro", "ultimo_erro": str(e), "verificada_em": _now()}},
        )
        return {"ok": False, "erro": str(e)}

    await db.ai_connections.update_one(
        {"tenant_id": user["tenant_id"]},
        {"$set": {"status": "conectada", "ultimo_erro": None, "verificada_em": _now()}},
    )
    return {"ok": True}


@router.delete("/connection")
async def remover_conexao(user=Depends(require_tenant_admin)):
    db = get_db()
    await db.ai_connections.delete_one({"tenant_id": user["tenant_id"]})
    return {"ok": True}


@router.get("/usage")
async def consumo(mes: str | None = None, user=Depends(require_tenant_admin)):
    """Consumo do mês. `mes` no formato AAAA-MM; ausente = mês corrente."""
    db = get_db()
    return await ai_runtime.consumo_do_mes(db, user["tenant_id"], mes)


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------
#
# Vários por empresa, cada um amarrado a conexões de WhatsApp. Um número de
# vendas e um de suporte precisam de agentes diferentes.
#
# O prompt não é escrito num campo em branco: a empresa escolhe peças (tipo,
# tom, tamanho, o que não fazer) e `ai_agents.montar_instrucoes` costura. Um
# textarea vazio produz agente ruim, porque ninguém sabe escrever prompt de
# sistema — mas todo mundo sabe dizer "é vendas ou é suporte".


class AgenteIn(BaseModel):
    nome: str
    tipo: str = "geral"
    objetivo: str | None = None          # obrigatório quando tipo = personalizado
    modo: str = ai_agents.MODO_FALLBACK
    ativo: bool = True

    # Sobre a empresa
    empresa_nome: str | None = None
    empresa_site: str | None = None
    empresa_segmento: str | None = None
    empresa_descricao: str | None = None

    # Comportamento
    tom: list[str] = []
    tamanho: str = "normais"
    nao_fazer: str | None = None
    base_conhecimento: str | None = None
    escalar_quando: str | None = None
    max_respostas: int | None = None

    # Onde atende. Vazio = todas as conexões da empresa.
    conexoes: list[str] = []
    # Para qual departamento a conversa vai quando o agente transfere.
    departamento_id: str | None = None


def _valida_agente(body: AgenteIn):
    if body.tipo not in ai_agents.TIPOS:
        raise HTTPException(status_code=400, detail="Tipo de agente desconhecido")
    if body.tipo == "personalizado" and not (body.objetivo or "").strip():
        # Sem objetivo, um agente "personalizado" nao tem estrategia nenhuma:
        # responderia qualquer coisa. Melhor recusar do que criar um agente que
        # so decepciona no primeiro contato real.
        raise HTTPException(status_code=400,
                            detail="Descreva o objetivo do agente personalizado")
    if body.modo not in ai_agents.MODOS:
        raise HTTPException(status_code=400, detail="Modo de atuação desconhecido")
    if body.tamanho not in ai_agents.TAMANHOS:
        raise HTTPException(status_code=400, detail="Tamanho de resposta desconhecido")
    desconhecidos = [t for t in body.tom if t not in ai_agents.TONS]
    if desconhecidos:
        raise HTTPException(status_code=400,
                            detail=f"Tom desconhecido: {', '.join(desconhecidos)}")
    if body.max_respostas is not None and not (1 <= body.max_respostas <= 50):
        raise HTTPException(status_code=400,
                            detail="O limite de respostas deve ficar entre 1 e 50")


@router.get("/agents/catalog")
async def catalogo_de_agentes(_=Depends(require_tenant_admin)):
    """Tipos, tons, tamanhos, segmentos e modos — o que a tela oferece."""
    return ai_agents.catalogo_publico()


@router.get("/agents")
async def listar_agentes(user=Depends(require_tenant_admin)):
    db = get_db()
    return await db.ai_agents.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(50)


@router.post("/agents")
async def criar_agente(body: AgenteIn, user=Depends(require_tenant_admin)):
    _valida_agente(body)
    db = get_db()
    agente = {
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        **body.model_dump(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.ai_agents.insert_one(agente)
    agente.pop("_id", None)
    return agente


@router.patch("/agents/{agent_id}")
async def atualizar_agente(agent_id: str, body: AgenteIn, user=Depends(require_tenant_admin)):
    _valida_agente(body)
    db = get_db()
    res = await db.ai_agents.update_one(
        {"id": agent_id, "tenant_id": user["tenant_id"]},
        {"$set": {**body.model_dump(), "updated_at": _now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    return await db.ai_agents.find_one({"id": agent_id}, {"_id": 0})


@router.delete("/agents/{agent_id}")
async def remover_agente(agent_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    res = await db.ai_agents.delete_one({"id": agent_id, "tenant_id": user["tenant_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    return {"ok": True}


class TesteIn(BaseModel):
    # A conversa do teste, no mesmo formato do histórico real. A última
    # mensagem é a que o agente vai responder.
    mensagens: list[dict]


@router.post("/agents/{agent_id}/test")
async def testar_agente(agent_id: str, body: TesteIn, user=Depends(require_tenant_admin)):
    """Conversa de teste, sem WhatsApp e sem gravar nada.

    Mesma ideia do "Testar" do editor de fluxos: ver o agente responder antes
    de apontá-lo para clientes de verdade. Usa o motor real
    (`ai_runtime.responder_por_tenant`), então também exercita a credencial, o
    teto do plano e a medição de consumo — um teste que passasse por fora
    desses três não provaria que o agente funciona em produção.
    """
    db = get_db()
    agente = await db.ai_agents.find_one({"id": agent_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not agente:
        raise HTTPException(status_code=404, detail="Agente não encontrado")

    historico = [
        {"role": "assistant" if m.get("role") == "assistant" else "user",
         "content": str(m.get("content") or "").strip()}
        for m in body.mensagens if str(m.get("content") or "").strip()
    ]
    while historico and historico[0]["role"] != "user":
        historico.pop(0)
    if not historico:
        raise HTTPException(status_code=400, detail="Envie ao menos uma mensagem do contato")

    ultima = historico[-1]["content"] if historico[-1]["role"] == "user" else ""
    if ultima and ai_agents.pediu_humano(ultima):
        # Mesmo atalho do atendimento real: nem chega a chamar o provedor.
        return {"transferiu": True, "texto": None,
                "motivo": "O contato pediu para falar com uma pessoa"}

    try:
        resposta = await ai_runtime.responder_por_tenant(
            db, user["tenant_id"], ai_agents.montar_instrucoes(agente), historico)
    except ai_client.IAError as e:
        raise HTTPException(status_code=400, detail=str(e))

    texto = (resposta.texto or "").strip()
    if ai_agents.SENTINELA.lower() in texto.lower():
        return {"transferiu": True, "texto": None,
                "motivo": "O agente decidiu transferir para um atendente"}
    return {
        "transferiu": False,
        "texto": texto,
        "tokens": (resposta.tokens_entrada + resposta.tokens_saida
                   + resposta.tokens_cache_leitura + resposta.tokens_cache_escrita),
    }


@router.get("/agents/{agent_id}/prompt")
async def ver_prompt(agent_id: str, user=Depends(require_tenant_admin)):
    """O prompt final montado a partir das escolhas da tela.

    Existe para o admin poder conferir o que o agente realmente recebe. Sem
    isto, ajustar tom e restrições é adivinhação: a pessoa muda um campo e não
    tem como saber o que mudou de fato.
    """
    db = get_db()
    agente = await db.ai_agents.find_one({"id": agent_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not agente:
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    return {"instrucoes": ai_agents.montar_instrucoes(agente)}
