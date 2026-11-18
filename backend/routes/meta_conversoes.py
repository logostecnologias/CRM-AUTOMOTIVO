"""Configuração da Conversions API do Meta (ver `meta_conversoes`).

Uma configuração por empresa: o dataset (o "pixel" que recebe os eventos), um
token opcional e o código de teste. O token é cifrado como toda credencial de
cliente e nunca volta inteiro para a tela.
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import cripto
import meta_conversoes as dominio
import whatsapp_client as whatsapp
from auth import require_tenant_admin
from db import get_db

router = APIRouter(prefix="/api/meta-conversoes", tags=["meta-conversoes"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _publico(config: dict | None) -> dict:
    config = config or {}
    token = None
    if config.get("token"):
        try:
            token = cripto.mascara(cripto.decifrar(config["token"]))
        except Exception:
            token = "ilegível — cole de novo"
    return {
        "ativo": bool(config.get("ativo")),
        "dataset_id": config.get("dataset_id") or "",
        "token": token,
        "test_event_code": config.get("test_event_code") or "",
        "eventos": dominio.EVENTOS,
    }


@router.get("")
async def ler(user=Depends(require_tenant_admin)):
    config = await get_db().meta_conversoes.find_one({"tenant_id": user["tenant_id"]}, {"_id": 0})
    return _publico(config)


class ConfigIn(BaseModel):
    ativo: bool = False
    dataset_id: str = ""
    # Ausente = mantém o que está gravado; vazio = apaga (passa a usar o token
    # da conexão de WhatsApp).
    token: str | None = None
    test_event_code: str = ""


@router.put("")
async def salvar(body: ConfigIn, user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    dataset = body.dataset_id.strip()
    if dataset and not re.fullmatch(r"\d{5,25}", dataset):
        raise HTTPException(status_code=400, detail="O ID do dataset é só números")
    if body.ativo and not dataset:
        raise HTTPException(status_code=400, detail="Informe o ID do dataset para ativar")
    campos = {
        "tenant_id": tenant_id,
        "ativo": body.ativo,
        "dataset_id": dataset or None,
        "test_event_code": body.test_event_code.strip() or None,
        "updated_at": _now(),
    }
    if body.token is not None:
        campos["token"] = cripto.cifrar(body.token.strip()) if body.token.strip() else None
    await db.meta_conversoes.update_one({"tenant_id": tenant_id}, {"$set": campos}, upsert=True)
    return _publico(await db.meta_conversoes.find_one({"tenant_id": tenant_id}, {"_id": 0}))


@router.post("/testar")
async def testar(user=Depends(require_tenant_admin)):
    """Manda um evento de teste e devolve o que o Meta respondeu.

    Sem código de teste o evento entraria nos números reais do anunciante,
    então ele é exigido aqui.
    """
    db = get_db()
    tenant_id = user["tenant_id"]
    config = await db.meta_conversoes.find_one({"tenant_id": tenant_id}, {"_id": 0})
    if not config or not config.get("dataset_id"):
        raise HTTPException(status_code=400, detail="Salve o ID do dataset antes de testar")
    if not config.get("test_event_code"):
        raise HTTPException(
            status_code=400,
            detail="Preencha o código de teste (Gerenciador de Eventos → Testar eventos) "
                   "para o evento não contar como venda de verdade")
    contato = {"id": "teste-zappzen", "numero_whatsapp": "5511999999999"}
    evento = dominio.montar_evento("Purchase", {"id": "teste", "valor": 1}, contato, None,
                                   teste=True)
    try:
        resposta = await dominio.enviar(db, tenant_id, config, [evento])
    except whatsapp.WhatsAppError as e:
        raise HTTPException(status_code=400, detail=f"O Meta recusou: {e}")
    return {"ok": True, "recebidos": resposta.get("events_received")}


@router.get("/eventos")
async def eventos(user=Depends(require_tenant_admin)):
    """Últimos envios, para responder "o Meta está recebendo as vendas?"."""
    itens = await get_db().meta_eventos.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort([("created_at", -1)]).limit(50).to_list(50)
    return {"items": itens}
