"""Como uma empresa efetivamente obtém uma resposta de IA: qual credencial
usar, quanto ela já consumiu no mês e se ainda pode consumir.

Separado de `ai_client.py` de propósito: lá é só protocolo (falar com o
provedor); aqui é a regra de negócio (de quem é a conta, quem paga, até quanto
pode). Quem precisa de uma resposta chama `responder_por_tenant`, e não o
`ai_client` direto — é essa função que garante que o consumo foi medido e o
teto respeitado.

**Duas origens de credencial.** A empresa pode conectar a conta dela
(`ai_connections`), e aí o consumo é dela e não tem teto nosso; ou não conectar
nada, e aí cai na chave da plataforma, com o consumo medido e limitado pelo
plano. As duas convivem porque atendem clientes diferentes: quem já tem conta
no provedor quer usar a dele, e quem nunca ouviu falar de token quer que
simplesmente funcione.

**O consumo é gravado sempre**, nas duas origens. Na chave da plataforma
porque é o que fatura; na chave do cliente porque é o que permite mostrar a
ele quanto o atendimento automatizado custou no mês — que é a informação que
justifica a mensalidade.
"""
import os
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

import ai_client
import ai_credentials

logger = logging.getLogger("zappzen.ia")

ORIGEM_CLIENTE = "cliente"
ORIGEM_PLATAFORMA = "plataforma"


def _hoje() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Credencial
# ---------------------------------------------------------------------------

def _credencial_plataforma() -> dict | None:
    """A chave do dono do SaaS, se configurada. Lida do ambiente a cada uso —
    nunca do banco, e nunca guardada em variável de módulo."""
    chave = os.environ.get("AI_PLATFORM_KEY")
    if not chave:
        return None
    provedor = os.environ.get("AI_PLATFORM_PROVIDER", "openai")
    if provedor not in ai_client.PROVEDORES:
        logger.warning("AI_PLATFORM_PROVIDER inválido (%s) — ignorando chave da plataforma", provedor)
        return None
    modelo = os.environ.get("AI_PLATFORM_MODEL") or ai_client.modelo_padrao(provedor)
    return {"provedor": provedor, "chave": chave, "modelo": modelo, "origem": ORIGEM_PLATAFORMA}


async def resolver_credencial(db, tenant_id: str) -> dict:
    """Qual conta responde por esta empresa. A dela vem primeiro.

    Levanta 400/403 com texto que a tela pode mostrar — quem chama não precisa
    distinguir "não configurou" de "estourou o plano".
    """
    conexao = await db.ai_connections.find_one(
        {"tenant_id": tenant_id, "status": "conectada"}, {"_id": 0}
    )
    if conexao:
        return {
            "provedor": conexao["provedor"],
            "chave": ai_credentials.decifrar(conexao.get("credencial") or {}),
            "modelo": conexao["modelo"],
            "origem": ORIGEM_CLIENTE,
        }

    plataforma = _credencial_plataforma()
    if plataforma is None:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma conta de IA conectada. Conecte a conta da empresa em Agentes de IA.",
        )
    await _checar_cota(db, tenant_id)
    return plataforma


# ---------------------------------------------------------------------------
# Cota do plano (só vale para a chave da plataforma)
# ---------------------------------------------------------------------------

async def _checar_cota(db, tenant_id: str):
    """Teto de tokens no mês, quando quem paga somos nós.

    Não entra na tabela `LIMITS` do `plan_limits.py` pelo mesmo motivo que
    `max_disparos_mes` não entra: aquele helper conta documentos existentes por
    tenant, e este limite é sobre uma janela de tempo.

    Conta tokens, e não mensagens, porque é token que custa: uma conversa longa
    com base de conhecimento grande consome dez vezes o de uma pergunta seca, e
    um teto por mensagem cobraria as duas igual.
    """
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "plan_id": 1})
    if not tenant or not tenant.get("plan_id"):
        return
    plano = await db.plans.find_one({"id": tenant["plan_id"]}, {"_id": 0})
    if not plano:
        return
    teto = plano.get("max_tokens_ia_mes")
    if not teto:  # None ou 0 = ilimitado
        return
    usados = await consumo_do_mes(db, tenant_id)
    if usados["tokens"] >= teto:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Limite de IA do plano \"{plano['nome']}\" atingido "
                f"({usados['tokens']:,} de {teto:,} tokens no mês). "
                "Conecte a conta de IA da empresa para continuar sem limite."
            ).replace(",", "."),
        )


# ---------------------------------------------------------------------------
# Medição
# ---------------------------------------------------------------------------

async def registrar_uso(db, tenant_id: str, origem: str, provedor: str,
                        modelo_id: str, resposta: ai_client.Resposta):
    """Soma esta chamada no acumulado do dia.

    Um documento por (empresa, dia, modelo), incrementado — não um documento
    por chamada. Com 9.000 respostas/mês por empresa, um registro por chamada
    viraria uma coleção grande e quente para produzir um número que é sempre
    lido agregado. O corte por dia é o que permite a série do gráfico depois.

    Nunca levanta: perder a contagem de uma resposta é ruim, deixar de
    responder o contato porque a contagem falhou é pior. Mesma regra do
    `deals.registrar_evento`.
    """
    try:
        modelo = ai_client.modelo_de(provedor, modelo_id)
        custo = resposta.custo_usd(modelo)
        tokens = (resposta.tokens_entrada + resposta.tokens_saida
                  + resposta.tokens_cache_leitura + resposta.tokens_cache_escrita)
        await db.ai_usage.update_one(
            {"tenant_id": tenant_id, "dia": _hoje(), "provedor": provedor,
             "modelo": modelo_id, "origem": origem},
            {
                "$inc": {
                    "chamadas": 1,
                    "tokens": tokens,
                    "tokens_entrada": resposta.tokens_entrada,
                    "tokens_saida": resposta.tokens_saida,
                    "tokens_cache_leitura": resposta.tokens_cache_leitura,
                    "tokens_cache_escrita": resposta.tokens_cache_escrita,
                    "custo_usd": custo,
                },
                "$setOnInsert": {"mes": _mes_atual()},
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning("Falha ao registrar consumo de IA do tenant %s: %s", tenant_id, e)


async def consumo_do_mes(db, tenant_id: str, mes: str | None = None) -> dict:
    """Total do mês corrente (ou do mês pedido), por empresa.

    Uma agregação, não uma contagem por modelo somada em Python: o que domina
    aqui é a ida e volta pelo túnel, não o volume de documentos.
    """
    mes = mes or _mes_atual()
    cursor = db.ai_usage.aggregate([
        {"$match": {"tenant_id": tenant_id, "mes": mes}},
        {"$group": {
            "_id": None,
            "chamadas": {"$sum": "$chamadas"},
            "tokens": {"$sum": "$tokens"},
            "custo_usd": {"$sum": "$custo_usd"},
        }},
    ])
    linhas = await cursor.to_list(1)
    if not linhas:
        return {"mes": mes, "chamadas": 0, "tokens": 0, "custo_usd": 0.0}
    l = linhas[0]
    return {
        "mes": mes,
        "chamadas": l.get("chamadas", 0),
        "tokens": l.get("tokens", 0),
        "custo_usd": round(l.get("custo_usd", 0.0), 4),
    }


# ---------------------------------------------------------------------------
# O ponto de entrada de quem quer uma resposta
# ---------------------------------------------------------------------------

async def responder_por_tenant(db, tenant_id: str, instrucoes: str,
                               historico: list[dict]) -> ai_client.Resposta:
    """Resolve a credencial, chama o provedor e mede — nesta ordem.

    É por aqui que o agente de IA, o nó de fluxo e a sugestão ao atendente
    devem passar. Chamar `ai_client.responder` direto pula a cota e a medição.
    """
    cred = await resolver_credencial(db, tenant_id)
    resposta = await ai_client.responder(
        cred["provedor"], cred["chave"], cred["modelo"], instrucoes, historico
    )
    await registrar_uso(db, tenant_id, cred["origem"], cred["provedor"],
                        cred["modelo"], resposta)
    return resposta
