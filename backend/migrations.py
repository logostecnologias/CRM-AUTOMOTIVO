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


async def _run():
    await asyncio.sleep(STARTUP_DELAY)
    db = get_db()
    filled = await backfill_last_message(db)
    if filled:
        logger.info("Backfill de last_message: %d conversas atualizadas", filled)


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
