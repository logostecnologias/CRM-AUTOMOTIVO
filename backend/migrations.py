"""Migrações de dados que rodam uma vez, no start do backend.

Mesmo padrão start/stop do `health_monitor` e do `media_retention`, e pelo
mesmo motivo: são tarefas de fundo, não podem atrasar o boot nem derrubá-lo se
falharem. Cada migração precisa ser idempotente — o backend reinicia com
frequência, e toda subida passa por aqui.
"""
import asyncio
import logging

from db import get_db
from flow_runtime import last_message_preview

logger = logging.getLogger("zappzen.migrations")

STARTUP_DELAY = 5   # deixa o boot terminar antes de tocar no banco
BATCH = 200

_task: asyncio.Task | None = None


async def backfill_last_message(db) -> int:
    """Preenche `last_message` nas conversas criadas antes da prévia existir.

    A prévia passou a ser gravada junto de cada mensagem, mas as conversas
    anteriores nasceram sem ela e mostrariam um card vazio na Central até
    receberem mensagem nova. Este é o mesmo aggregate que a lista rodava a
    cada atualização de tela — a diferença é que agora roda uma vez, e não
    vinte vezes por minuto por atendente.

    Idempotente: só olha para sessões em que o campo ainda não existe, então
    a segunda subida encontra zero e não faz nada.
    """
    total = 0
    while True:
        sessions = await db.conversation_sessions.find(
            {"last_message": {"$exists": False}}, {"_id": 0, "id": 1}
        ).limit(BATCH).to_list(BATCH)
        if not sessions:
            break

        ids = [s["id"] for s in sessions]
        last = {
            row["_id"]: row["last"]
            async for row in db.messages_log.aggregate([
                {"$match": {"session_id": {"$in": ids}}},
                {"$sort": {"timestamp": -1}},
                {"$group": {"_id": "$session_id", "last": {"$first": "$$ROOT"}}},
            ])
        }
        for session_id in ids:
            doc = last.get(session_id)
            # Conversa sem mensagem nenhuma grava `None` de propósito: sem
            # isso ela seria relida em todo lote, para sempre.
            await db.conversation_sessions.update_one(
                {"id": session_id},
                {"$set": {"last_message": last_message_preview(doc) if doc else None}},
            )
            total += 1

        if len(sessions) < BATCH:
            break

    return total


async def limpar_conexoes_da_api_antiga(db) -> int:
    """Conexão que ficou de pé na API não oficial não pode parecer conectada.

    O pareamento por QR deixava a conexão em `conectado` com um token de
    instância. Esse token não existe mais, e sem `phone_number_id` a conexão
    não envia nem recebe nada. Deixá-la como "conectado" faria a tela mentir e,
    pior, faria a campanha tentar disparar por ela: o runner só pausa quando o
    status é diferente de conectado.

    Os campos mortos saem junto, para o documento não carregar credencial de um
    sistema que não é mais usado.

    Idempotente: na segunda subida o filtro não casa mais nada.
    """
    # O canal `wuzapi` voltou depois desta migração, e as conexões dele também
    # não têm `phone_number_id`: sem excluí-lo, todo reinício do servidor as
    # marcava como desconectadas, e lembrete, formulário, ligação e campanha
    # paravam de sair até o próximo evento da ponte (16/10/2026).
    res = await db.whatsapp_connections.update_many(
        {"phone_number_id": None, "canal": {"$ne": "wuzapi"}},
        {"$set": {"status": "desconectado"},
         "$unset": {"wuzapi_token": "", "wuzapi_user_id": "", "qrcode_atual": ""}},
    )
    return res.modified_count


async def iniciar_aquecimento(db) -> int:
    """Conexão WuzAPI anterior ao aquecimento ganha a data em que foi criada.

    É a melhor estimativa da idade do número que existe no banco. Uma conexão
    criada há uma semana entra no meio do aquecimento, e não no começo: ela já
    vinha conversando.

    Idempotente: na segunda subida o filtro não casa mais nada.
    """
    n = 0
    async for c in db.whatsapp_connections.find(
            {"canal": "wuzapi", "aquecimento_desde": None},
            {"_id": 0, "id": 1, "created_at": 1}):
        res = await db.whatsapp_connections.update_one(
            {"id": c["id"], "aquecimento_desde": None},
            {"$set": {"aquecimento_desde": c.get("created_at") or _agora_iso()}})
        n += res.modified_count
    return n


def _agora_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def desmarcar_chaves_de_ia(db) -> int:
    """Chave de IA marcada como quebrada por um erro que não era dela.

    Até 16/10/2026 o chat de teste marcava a chave em qualquer falha: limite
    por minuto da Groq, provedor fora do ar, resposta vazia. Marcada, ela sai de
    uso no atendimento real e na transcrição, e o agente parecia "sem chave".
    Hoje só recusa e falta de saldo marcam; as marcas antigas por outro motivo
    são desfeitas aqui.

    Idempotente: na segunda subida o filtro não casa mais nada.
    """
    res = await db.ai_agents.update_many(
        {"credencial_status": "erro",
         "credencial_erro": {"$not": {"$regex": "recusada|sem saldo|workspace"}}},
        {"$set": {"credencial_status": "ok", "credencial_erro": None}},
    )
    return res.modified_count


async def planos_para_empresa(db) -> int:
    """Os planos saíram em 18/11/2026. Dois campos deles continuam valendo,
    agora na própria empresa: o teto de tokens de IA (protege o custo da chave
    da plataforma) e a janela de retenção de mídia.

    Copia o valor do plano em que a empresa estava, para nada mudar de um dia
    para o outro: sem isto o teto de IA sumiria (custo sem freio) e a mídia de
    quem tinha retenção maior que o default começaria a ser apagada.

    Só acrescenta. `plan_id` e a coleção `plans` ficam onde estão: ninguém mais
    os lê, e apagar dado de produção por arrumação não compensa o risco.
    Idempotente: a marca é a presença de `limite_tokens_ia_mes`.
    """
    alvo = {"plan_id": {"$nin": [None, ""]}, "limite_tokens_ia_mes": {"$exists": False}}
    tenants = await db.tenants.find(alvo, {"_id": 0, "id": 1, "plan_id": 1}).to_list(5000)
    if not tenants:
        return 0
    planos = {
        p["id"]: p async for p in db.plans.find(
            {"id": {"$in": list({t["plan_id"] for t in tenants})}},
            {"_id": 0, "id": 1, "max_tokens_ia_mes": 1, "retencao_midia_dias": 1})
    }
    n = 0
    for t in tenants:
        plano = planos.get(t["plan_id"]) or {}
        campos = {"limite_tokens_ia_mes": plano.get("max_tokens_ia_mes") or None}
        if plano.get("retencao_midia_dias") is not None:
            campos["retencao_midia_dias"] = plano["retencao_midia_dias"]
        await db.tenants.update_one({"id": t["id"]}, {"$set": campos})
        n += 1
    return n


async def _run():
    await asyncio.sleep(STARTUP_DELAY)
    db = get_db()
    # Primeiro de propósito: a varredura de mídia começa aos 60s e lê a janela
    # de retenção que esta cópia grava. Uma falha nas outras não pode pular esta.
    copiadas = await planos_para_empresa(db)
    if copiadas:
        logger.info("Teto de IA e retenção copiados do plano para a empresa: %d", copiadas)
    filled = await backfill_last_message(db)
    if filled:
        logger.info("Backfill de last_message: %d conversas atualizadas", filled)
    limpas = await limpar_conexoes_da_api_antiga(db)
    if limpas:
        logger.info("Conexões sem número da Cloud API marcadas como desconectadas: %d", limpas)
    aquecendo = await iniciar_aquecimento(db)
    if aquecendo:
        logger.info("Conexões WuzAPI com início de aquecimento preenchido: %d", aquecendo)
    chaves = await desmarcar_chaves_de_ia(db)
    if chaves:
        logger.info("Chaves de IA desmarcadas (erro que não era da chave): %d", chaves)


async def _guarded():
    try:
        await _run()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Uma migração que falha não pode derrubar o backend: o pior caso é a
        # prévia faltar em conversas antigas, que a próxima mensagem resolve.
        logger.exception("Migração falhou: %s", e)


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_guarded())


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
