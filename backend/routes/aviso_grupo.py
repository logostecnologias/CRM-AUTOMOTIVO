"""Configuração do aviso no grupo de WhatsApp da equipe (ver `aviso_grupo`).

Só admin: escolher em que grupo o sistema escreve é configuração, e entrar num
grupo põe o número da empresa lá dentro.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import aviso_grupo as dominio
import deals
import whatsapp_client as whatsapp
import wuzapi_client
from auth import require_tenant_admin
from db import get_db

router = APIRouter(prefix="/api/aviso-grupo", tags=["aviso-grupo"])


async def _conexao(db, tenant_id: str, connection_id: str):
    conn = await db.whatsapp_connections.find_one(
        {"id": connection_id, "tenant_id": tenant_id}, {"_id": 0})
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    if conn.get("canal") != whatsapp.CANAL_WUZAPI:
        raise HTTPException(status_code=400, detail=(
            "Aviso em grupo só funciona em conexão WuzAPI: a API oficial do "
            "WhatsApp não envia mensagem para grupo"))
    cred = whatsapp.credencial(conn)
    if not cred:
        raise HTTPException(status_code=400, detail="Essa conexão não está pareada")
    return conn, cred


@router.get("")
async def ler(user=Depends(require_tenant_admin)):
    db = get_db()
    tid = user["tenant_id"]
    conexoes = await db.whatsapp_connections.find(
        {"tenant_id": tid, "canal": whatsapp.CANAL_WUZAPI},
        {"_id": 0, "id": 1, "nome": 1, "numero": 1, "status": 1}).to_list(50)
    funis = await deals.funis_da_empresa(db, tid)
    etapas = [{"id": e["id"], "nome": e["nome"], "funil": f["nome"]}
              for f in funis for e in deals.etapas_em_ordem(f)]
    return {**(await dominio.configuracao(db, tid)), "conexoes": conexoes, "etapas_funil": etapas}


@router.get("/grupos")
async def grupos(connection_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    _, cred = await _conexao(db, user["tenant_id"], connection_id)
    try:
        itens = await wuzapi_client.list_groups(cred.token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"A ponte do WhatsApp não listou os grupos: {e}")
    return sorted(itens, key=lambda g: g["nome"].lower())


class EntrarIn(BaseModel):
    connection_id: str
    link: str


@router.post("/entrar")
async def entrar(body: EntrarIn, user=Depends(require_tenant_admin)):
    db = get_db()
    _, cred = await _conexao(db, user["tenant_id"], body.connection_id)
    codigo = wuzapi_client.codigo_do_convite(body.link)
    if not codigo:
        raise HTTPException(status_code=422, detail="Isso não parece um link de convite de grupo")
    try:
        jid = await wuzapi_client.join_group(cred.token, codigo)
    except Exception as e:
        raise HTTPException(status_code=502, detail=(
            f"O número não conseguiu entrar no grupo ({e}). O link pode ter sido "
            "revogado, ou um admin do grupo precisa aprovar a entrada"))
    # A lista é o que confirma a entrada e traz o nome do grupo.
    try:
        lista = await wuzapi_client.list_groups(cred.token)
    except Exception:
        lista = []
    grupo = next((g for g in lista if g["jid"] == jid), None) if jid else None
    return {"jid": jid, "nome": (grupo or {}).get("nome"), "grupos": lista}


class ConfigIn(BaseModel):
    ativo: bool = False
    connection_id: str | None = None
    grupo_jid: str | None = None
    grupo_nome: str | None = None
    etapas: list[str] = []


@router.put("")
async def salvar(body: ConfigIn, user=Depends(require_tenant_admin)):
    db = get_db()
    tid = user["tenant_id"]
    if body.ativo:
        if not body.connection_id or not body.grupo_jid:
            raise HTTPException(status_code=422, detail="Escolha a conexão e o grupo antes de ligar")
        if not body.etapas:
            raise HTTPException(status_code=422, detail="Escolha ao menos uma etapa que avisa o grupo")
    if body.connection_id:
        await _conexao(db, tid, body.connection_id)
    if body.grupo_jid and not body.grupo_jid.endswith("@g.us"):
        raise HTTPException(status_code=422, detail="Grupo inválido")
    funis = await deals.funis_da_empresa(db, tid)
    validas = {e["id"] for f in funis for e in f.get("etapas") or []}
    await db.avisos_grupo.update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "ativo": body.ativo, "connection_id": body.connection_id,
                  "grupo_jid": body.grupo_jid, "grupo_nome": (body.grupo_nome or "")[:200] or None,
                  "etapas": [e for e in body.etapas if e in validas], "ultimo_erro": None}},
        upsert=True)
    return await ler(user)


@router.post("/teste")
async def teste(user=Depends(require_tenant_admin)):
    db = get_db()
    cfg = await dominio.configuracao(db, user["tenant_id"])
    try:
        await dominio.enviar(db, user["tenant_id"], cfg,
                             "✅ Teste: a partir de agora o sistema avisa aqui as visitas agendadas.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Não foi possível enviar: {e}")
    return {"ok": True}
