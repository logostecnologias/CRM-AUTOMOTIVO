"""Tabela FIPE na tela (ver `fipe.py`): os seletores marca → modelo → ano e
o vínculo do carro do estoque com o modelo FIPE.

Consultar é de qualquer pessoa da empresa (o vendedor consulta o carro do
cliente na troca). Ligar o carro do estoque à FIPE muda a ficha, então é do
admin, como o resto da edição do estoque.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import fipe
from auth import require_tenant_admin, require_tenant_member
from db import get_db

router = APIRouter(prefix="/api", tags=["fipe"])


async def _chamar(coro):
    try:
        return await coro
    except fipe.FipeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/fipe/marcas")
async def marcas(tipo: str = "carro", user=Depends(require_tenant_member)):
    return await _chamar(fipe.marcas(tipo))


@router.get("/fipe/modelos")
async def modelos(marca: str, tipo: str = "carro", user=Depends(require_tenant_member)):
    return await _chamar(fipe.modelos(tipo, marca))


@router.get("/fipe/anos")
async def anos(marca: str, modelo: str, tipo: str = "carro", user=Depends(require_tenant_member)):
    return await _chamar(fipe.anos(tipo, marca, modelo))


@router.get("/fipe/preco")
async def preco(marca: str, modelo: str, ano: str, tipo: str = "carro",
                user=Depends(require_tenant_member)):
    p = await _chamar(fipe.preco(tipo, marca, modelo, ano))
    if not p:
        raise HTTPException(status_code=404, detail="Esse ano não está na tabela FIPE")
    return p


class VinculoIn(BaseModel):
    tipo: str = "carro"
    marca_id: str
    modelo_id: str
    ano_id: str


@router.put("/estoque/veiculos/{veiculo_id}/fipe")
async def vincular(veiculo_id: str, body: VinculoIn, user=Depends(require_tenant_admin)):
    """Liga o carro ao modelo FIPE e grava o valor do mês. Chamar de novo com
    o mesmo vínculo é o "atualizar": a tabela muda todo mês."""
    db = get_db()
    tid = user["tenant_id"]
    if not await db.veiculos.find_one({"id": veiculo_id, "tenant_id": tid}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    p = await _chamar(fipe.preco(body.tipo, body.marca_id, body.modelo_id, body.ano_id))
    if not p or not p.get("valor"):
        raise HTTPException(status_code=404, detail="Esse ano não está na tabela FIPE")
    p["consultado_em"] = datetime.now(timezone.utc).isoformat()
    await db.veiculos.update_one({"id": veiculo_id, "tenant_id": tid}, {"$set": {"fipe": p}})
    return p


@router.delete("/estoque/veiculos/{veiculo_id}/fipe")
async def desvincular(veiculo_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    r = await db.veiculos.update_one({"id": veiculo_id, "tenant_id": user["tenant_id"]},
                                     {"$set": {"fipe": None}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return {"ok": True}
