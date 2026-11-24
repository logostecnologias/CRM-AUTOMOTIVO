"""Catálogo público (ver `catalogo.py`): configuração na tela e as páginas.

Duas partes:
  - `/api/catalogo`: a configuração da loja (link, nome, WhatsApp, preço). Ler
    é de toda a equipe (o vendedor copia o link do carro); mudar é do admin.
  - `/c/{slug}`, `/c/{slug}/{id}`, `/c/{slug}/foto/{media_id}`: as páginas
    públicas, sem login. O Caddy manda `/c/*` para cá.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import catalogo as dominio
import media_store
from auth import require_tenant_admin, require_tenant_member
from db import get_db

router = APIRouter(tags=["catalogo"])


def _base_publica(request: Request) -> str:
    """O endereço que o cliente da loja vê. Atrás do Caddy o FastAPI enxerga
    `http://127.0.0.1:8000`; o `Host` e o `X-Forwarded-Proto` são os de fora."""
    env = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{proto}://{host}"


async def _config(db, tenant_id: str) -> dict:
    return await db.catalogos.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}


async def _sugestoes(db, tenant_id: str) -> dict:
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1, "nome": 1}) or {}
    nome = tenant.get("name") or tenant.get("nome") or ""
    conn = await db.whatsapp_connections.find_one(
        {"tenant_id": tenant_id, "numero": {"$nin": [None, ""]}}, {"_id": 0, "numero": 1}) or {}
    return {"nome": nome, "slug": dominio.sugerir_slug(nome), "whatsapp": conn.get("numero") or ""}


def _publico(cfg: dict, base: str, sugestao: dict) -> dict:
    slug = cfg.get("slug")
    return {
        "configurado": bool(slug),
        "ativo": bool(cfg.get("ativo")),
        "slug": slug or sugestao["slug"],
        "nome": cfg.get("nome") or sugestao["nome"],
        "whatsapp": cfg.get("whatsapp") or sugestao["whatsapp"],
        "endereco": cfg.get("endereco") or "",
        "mostrar_preco": cfg.get("mostrar_preco", True),
        "texto_whatsapp": cfg.get("texto_whatsapp") or dominio.TEXTO_WHATSAPP_PADRAO,
        "link": dominio.url_base(base, slug) if slug else None,
        "prefixo": dominio.url_base(base, ""),
    }


@router.get("/api/catalogo")
async def ler(request: Request, user=Depends(require_tenant_member)):
    db = get_db()
    return _publico(await _config(db, user["tenant_id"]), _base_publica(request),
                    await _sugestoes(db, user["tenant_id"]))


class ConfigIn(BaseModel):
    ativo: bool = False
    slug: str = Field(..., max_length=40)
    nome: str = Field(..., min_length=1, max_length=80)
    whatsapp: str = Field("", max_length=30)
    endereco: str = Field("", max_length=160)
    mostrar_preco: bool = True
    texto_whatsapp: str = Field("", max_length=400)


@router.put("/api/catalogo")
async def salvar(body: ConfigIn, request: Request, user=Depends(require_tenant_admin)):
    db = get_db()
    tid = user["tenant_id"]
    slug = body.slug.strip().lower()
    if not dominio.slug_valido(slug):
        raise HTTPException(status_code=422, detail=(
            "Endereço inválido: use de 3 a 40 letras minúsculas, números e hífen, "
            "começando e terminando com letra ou número"))
    dono = await db.catalogos.find_one({"slug": slug}, {"_id": 0, "tenant_id": 1})
    if dono and dono["tenant_id"] != tid:
        raise HTTPException(status_code=409, detail="Esse endereço já é de outra loja. Escolha outro.")
    whatsapp = dominio.so_digitos(body.whatsapp)
    if whatsapp and not 10 <= len(whatsapp) <= 15:
        raise HTTPException(status_code=422, detail="WhatsApp inválido: use o número com DDD, só dígitos")
    if body.ativo and not whatsapp:
        raise HTTPException(status_code=422, detail=(
            "Informe o WhatsApp da loja: é para ele que o botão \"Tenho interesse\" leva"))
    texto = body.texto_whatsapp.strip()
    if texto and "{carro}" not in texto:
        raise HTTPException(status_code=422, detail="A mensagem precisa ter {carro}, que vira o nome do veículo")
    await db.catalogos.update_one({"tenant_id": tid}, {"$set": {
        "tenant_id": tid, "ativo": body.ativo, "slug": slug, "nome": body.nome.strip(),
        "whatsapp": whatsapp, "endereco": body.endereco.strip(), "mostrar_preco": body.mostrar_preco,
        "texto_whatsapp": texto or None, "updated_at": datetime.now(timezone.utc).isoformat(),
    }}, upsert=True)
    return await ler(request, user)


# ---------------------------------------------------------------------------
# Páginas públicas
# ---------------------------------------------------------------------------

async def _catalogo_ativo(db, slug: str) -> dict | None:
    if not dominio.slug_valido(slug):
        return None
    cfg = await db.catalogos.find_one({"slug": slug}, {"_id": 0})
    return cfg if cfg and cfg.get("ativo") else None


def _html(conteudo: str, status: int = 200, cache: int = 60) -> HTMLResponse:
    return HTMLResponse(conteudo, status_code=status, headers={
        "Cache-Control": f"public, max-age={cache}",
        "X-Content-Type-Options": "nosniff",
        # A página não tem script nenhum; a CSP garante que continue assim
        # mesmo que um texto da loja escape do `html.escape`.
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                                   "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    })


def _nao_encontrado() -> HTMLResponse:
    return _html(dominio.pagina_aviso(None, None, "Catálogo não encontrado",
                                      "Confira o link com a loja."), status=404, cache=0)


async def _a_venda(db, tenant_id: str) -> list[dict]:
    return await db.veiculos.find(
        {"tenant_id": tenant_id, "status": {"$in": dominio.A_VENDA}},
        {"_id": 0, "placa": 0, "localizacao": 0, "criado_por": 0}).to_list(2000)


@router.get("/c/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def pagina_lista(slug: str, request: Request, q: str = "", categoria: str = "",
                       ordem: str = "recentes"):
    db = get_db()
    cfg = await _catalogo_ativo(db, slug)
    if not cfg:
        return _nao_encontrado()
    base = dominio.url_base(_base_publica(request), slug)
    todos = await _a_venda(db, cfg["tenant_id"])
    categorias = sorted({v["categoria"] for v in todos if v.get("categoria")},
                        key=lambda c: list(dominio.ROTULOS["categoria"]).index(c)
                        if c in dominio.ROTULOS["categoria"] else 99)
    ordem = ordem if ordem in dominio.ORDENS else "recentes"
    lista = dominio.filtrar(list(todos), q[:80], categoria if categoria in categorias else "", ordem)
    return _html(dominio.pagina_lista(cfg, lista, base, len(todos), q[:80], categoria, ordem, categorias))


@router.get("/c/{slug}/foto/{media_id}", include_in_schema=False)
async def foto(slug: str, media_id: str):
    db = get_db()
    cfg = await _catalogo_ativo(db, slug)
    if not cfg:
        raise HTTPException(status_code=404)
    tid = cfg["tenant_id"]
    # Só foto de carro à venda: vender o carro tira a foto do ar.
    if not await db.veiculos.find_one({"tenant_id": tid, "fotos": media_id,
                                       "status": {"$in": dominio.A_VENDA}}, {"_id": 1}):
        raise HTTPException(status_code=404)
    doc = await db.media_files.find_one({"id": media_id, "tenant_id": tid}, {"_id": 0})
    if not doc or doc.get("purged_at") or doc.get("kind") != "image":
        raise HTTPException(status_code=404)
    path = media_store.file_path(doc)
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=doc.get("mime") or "image/jpeg", headers={
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/c/{slug}/{veiculo_id}", response_class=HTMLResponse, include_in_schema=False)
async def pagina_veiculo(slug: str, veiculo_id: str, request: Request):
    db = get_db()
    cfg = await _catalogo_ativo(db, slug)
    if not cfg:
        return _nao_encontrado()
    base = dominio.url_base(_base_publica(request), slug)
    v = await db.veiculos.find_one({"id": veiculo_id, "tenant_id": cfg["tenant_id"]},
                                   {"_id": 0, "placa": 0, "localizacao": 0, "criado_por": 0})
    if not v or v.get("status") not in dominio.A_VENDA:
        # O link de um carro vendido continua circulando no WhatsApp: em vez de
        # erro, o caminho para os outros carros.
        titulo = "Esse veículo já foi vendido" if v else "Veículo não encontrado"
        return _html(dominio.pagina_aviso(cfg, base, titulo, "Mas temos outros esperando por você."),
                     status=404 if not v else 410, cache=0)
    return _html(dominio.pagina_veiculo(cfg, v, base))
