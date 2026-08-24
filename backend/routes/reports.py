"""API de relatórios.

O escopo de quem pede é respeitado aqui como em toda tela que mostra conversa:
o atendente vê os números das conexões liberadas para ele, não os da empresa
inteira. Um relatório é o caminho mais fácil de contornar um filtro de acesso —
ele agrega justamente o que a lista esconderia.
"""
from fastapi import APIRouter, Depends, HTTPException

import datas
import relatorios
from auth import accessible_connection_ids, require_tenant_member
from db import get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])


async def _janela(de: str | None, ate: str | None) -> tuple[str, str]:
    inicio = datas.para_utc(de, "Data inicial")
    fim = datas.para_utc(ate, "Data final")
    if not inicio or not fim:
        raise HTTPException(status_code=400, detail="Informe o período do relatório")
    if inicio > fim:
        raise HTTPException(status_code=400, detail="A data inicial é posterior à final")
    return inicio, fim


async def _escopo(db, user: dict, connection_id: str | None) -> list[str] | None:
    """Conexões que entram no relatório. `None` = todas as da empresa."""
    permitidas = await accessible_connection_ids(db, user)
    if connection_id:
        if permitidas is not None and connection_id not in permitidas:
            raise HTTPException(status_code=403, detail="Você não tem acesso a esta conexão")
        return [connection_id]
    return permitidas


@router.get("/atendimento")
async def atendimento(de: str | None = None, ate: str | None = None,
                      connection_id: str | None = None, departamento_id: str | None = None,
                      user=Depends(require_tenant_member)):
    db = get_db()
    inicio, fim = await _janela(de, ate)
    escopo = await _escopo(db, user, connection_id)
    try:
        return await relatorios.atendimento(db, user["tenant_id"], inicio, fim,
                                            escopo, departamento_id)
    except relatorios.RelatorioError as e:
        # 413: o pedido é válido, o período é que é grande demais para responder.
        raise HTTPException(status_code=413, detail=str(e))


@router.get("/campanhas")
async def campanhas(de: str | None = None, ate: str | None = None,
                    user=Depends(require_tenant_member)):
    db = get_db()
    inicio, fim = await _janela(de, ate)
    return await relatorios.campanhas(db, user["tenant_id"], inicio, fim)
