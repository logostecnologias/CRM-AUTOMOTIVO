"""Apaga de verdade as empresas excluídas há mais que a carência.

Excluir uma empresa no painel só suspende e marca `excluida_em` (ver
`routes.tenants.delete_tenant`). Durante a carência dá para restaurar com um
clique; passada ela, esta varredura chama `apagar_empresa`, que leva tudo,
inclusive a assinatura do webhook da Meta.

Durante a carência os documentos de `media_files` continuam existindo, então a
varredura de órfãos de `media_retention` não toca nos arquivos em disco da
empresa: eles só ficam órfãos depois daqui, e aí seguem o caminho normal.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from db import get_db

logger = logging.getLogger("zappzen.exclusao_empresas")

INTERVALO = 3600
STARTUP_DELAY = 120

_task: asyncio.Task | None = None


async def varrer(db=None, agora: datetime | None = None) -> list[str]:
    """Apaga as empresas cuja carência acabou. Devolve os ids apagados."""
    from routes import tenants as rt  # import tardio: a rota importa muita coisa

    db = db or get_db()
    agora = agora or datetime.now(timezone.utc)
    limite = (agora - timedelta(days=rt.CARENCIA_DIAS)).isoformat()
    vencidas = [t async for t in db.tenants.find(
        {"excluida_em": {"$ne": None}}, {"_id": 0, "id": 1, "name": 1, "excluida_em": 1})]
    apagadas = []
    for t in vencidas:
        # As datas são todas ISO em UTC (+00:00), então comparar texto é
        # comparar instante.
        if not t.get("excluida_em") or t["excluida_em"] > limite:
            continue
        apagados = await rt.apagar_empresa(db, t["id"])
        logger.warning("Empresa %s (%s) apagada após a carência: %s",
                       t.get("name"), t["id"], apagados)
        apagadas.append(t["id"])
    return apagadas


async def _loop():
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        try:
            await varrer()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Varredura de exclusão de empresas falhou: %s", e)
        await asyncio.sleep(INTERVALO)


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
