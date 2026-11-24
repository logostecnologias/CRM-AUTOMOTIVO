"""Catálogo público: configuração, páginas, fotos e o link na consulta da IA."""
import asyncio
import os

from fakedb import FakeDB
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import ai_veiculos
import db as db_mod
import media_store
import routes.catalogo as rc

DB = FakeDB()
T1, T2 = "t-cat-1", "t-cat-2"
ADMIN = {"id": "u-1", "tenant_id": T1, "role": "tenant_admin", "name": "Ana"}


class _Req:
    """O bastante de `Request` para as rotas de configuração."""
    headers = {"host": "loja.exemplo.com", "x-forwarded-proto": "https"}

    class url:
        scheme = "http"


def _app():
    app = FastAPI()
    app.include_router(rc.router)
    return TestClient(app)


async def _semear():
    DB._cols.clear()
    await DB.tenants.insert_one({"id": T1, "name": "Atalaia Veículos"})
    await DB.whatsapp_connections.insert_one({"id": "c1", "tenant_id": T1, "numero": "5585999998888"})
    foto = await media_store.store_upload(DB, T1, None, "u-1", "strada.jpg", "image/jpeg", b"jpg", kind="image")
    foto2 = await media_store.store_upload(DB, T1, None, "u-1", "pulse.jpg", "image/jpeg", b"jpg2", kind="image")
    base = {"tenant_id": T1, "marca": "Fiat", "ano_modelo": 2026, "ano_fabricacao": 2025,
            "categoria": "picape", "cambio": "manual", "entrada_em": "2026-11-01"}
    await DB.veiculos.insert_one({**base, "id": "v-strada", "modelo": "Strada", "versao": "Freedom <script>x</script>",
                                  "km": 1200, "preco": 113000.0, "preco_anterior": 118000.0,
                                  "placa": "ABC1D23", "localizacao": "Pátio 2", "status": "disponivel",
                                  "fotos": [foto["id"]], "opcionais": ["Ar-condicionado"]})
    await DB.veiculos.insert_one({**base, "id": "v-pulse", "modelo": "Pulse", "categoria": "suv",
                                  "preco": 99000.0, "status": "vendido", "fotos": [foto2["id"]]})
    await DB.veiculos.insert_one({**base, "id": "v-argo", "modelo": "Argo", "categoria": "hatch",
                                  "preco": 75000.0, "status": "reservado", "fotos": []})
    await DB.veiculos.insert_one({**base, "tenant_id": T2, "id": "v-outra", "modelo": "Uno",
                                  "status": "disponivel", "fotos": []})
    return foto["id"], foto2["id"]


async def _config():
    # Sugestões a partir da empresa, antes de configurar.
    cfg = await rc.ler(_Req(), ADMIN)
    assert cfg["configurado"] is False and cfg["slug"] == "atalaia-veiculos", cfg
    assert cfg["whatsapp"] == "5585999998888" and cfg["nome"] == "Atalaia Veículos"

    for slug in ("ab", "-loja", "api", "loja_1", "loja nova"):
        try:
            await rc.salvar(rc.ConfigIn(slug=slug, nome="X", whatsapp="85999998888"), _Req(), ADMIN)
            assert False, slug
        except HTTPException as e:
            assert e.status_code == 422, slug
    try:
        await rc.salvar(rc.ConfigIn(ativo=True, slug="atalaia", nome="Atalaia"), _Req(), ADMIN)
        assert False, "ligado sem WhatsApp"
    except HTTPException as e:
        assert e.status_code == 422
    try:
        await rc.salvar(rc.ConfigIn(slug="atalaia", nome="A", whatsapp="85999998888",
                                    texto_whatsapp="Oi"), _Req(), ADMIN)
        assert False, "mensagem sem {carro}"
    except HTTPException as e:
        assert e.status_code == 422

    cfg = await rc.salvar(rc.ConfigIn(ativo=True, slug="atalaia", nome="Atalaia Veículos",
                                      whatsapp="(85) 99999-8888", endereco="Av. Central, 100"), _Req(), ADMIN)
    assert cfg["link"] == "https://loja.exemplo.com/c/atalaia", cfg
    assert cfg["whatsapp"] == "85999998888"

    outra = {**ADMIN, "tenant_id": T2}
    try:
        await rc.salvar(rc.ConfigIn(slug="atalaia", nome="Outra"), _Req(), outra)
        assert False, "endereço de outra loja"
    except HTTPException as e:
        assert e.status_code == 409


def _paginas(foto_venda, foto_vendido):
    c = _app()
    h = {"host": "loja.exemplo.com", "x-forwarded-proto": "https"}

    r = c.get("/c/atalaia", headers=h)
    assert r.status_code == 200, r.text
    t = r.text
    assert "Strada" in t and "Argo" in t, t
    assert "Pulse" not in t, "vendido não aparece"
    assert "Uno" not in t, "carro de outra loja"
    assert "ABC1D23" not in t and "Pátio 2" not in t, "placa e localização não saem"
    assert "<script>" not in t and "&lt;script&gt;" in t, "texto da loja escapado"
    assert "Reservado" in t
    assert 'property="og:image" content="https://loja.exemplo.com/c/atalaia/foto/' in t
    assert "2 veículos disponíveis" in t
    assert "script-src" not in r.headers["content-security-policy"]

    r = c.get("/c/atalaia?q=strada", headers=h)
    assert "Strada" in r.text and "Argo" not in r.text and "1 de 2 veículos" in r.text
    r = c.get("/c/atalaia?categoria=hatch", headers=h)
    assert "Argo" in r.text and "Strada" not in r.text

    r = c.get("/c/atalaia/v-strada", headers=h)
    assert r.status_code == 200
    t = r.text
    assert "R$ 113.000" in t and "R$ 118.000" in t, "preço e o de/por"
    assert "https://wa.me/85999998888?text=" in t
    assert "Strada%20Freedom" in t and "https%3A//loja.exemplo.com/c/atalaia/v-strada" in t, t
    assert 'property="og:title" content="Fiat Strada 2025/2026 · R$ 113.000"' in t, t
    assert "Ar-condicionado" in t

    r = c.get("/c/atalaia/v-pulse", headers=h)
    assert r.status_code == 410 and "já foi vendido" in r.text
    assert c.get("/c/atalaia/v-outra", headers=h).status_code == 404
    assert c.get("/c/nao-existe", headers=h).status_code == 404

    assert c.get(f"/c/atalaia/foto/{foto_venda}").status_code == 200
    assert c.get(f"/c/atalaia/foto/{foto_vendido}").status_code == 404, "foto de carro vendido"
    return c, h


async def _desligar_e_ia(c, h):
    os.environ["PUBLIC_BASE_URL"] = "https://loja.exemplo.com"
    try:
        texto = await ai_veiculos.executor(DB, T1)("consultar_estoque", {"busca": "strada"})
        assert "link: https://loja.exemplo.com/c/atalaia/v-strada" in texto, texto
        assert "Link:" in ai_veiculos.INSTRUCOES
    finally:
        os.environ.pop("PUBLIC_BASE_URL", None)
    texto = await ai_veiculos.executor(DB, T1)("consultar_estoque", {"busca": "strada"})
    assert "link:" not in texto, "sem PUBLIC_BASE_URL não há link absoluto"

    await DB.catalogos.update_one({"tenant_id": T1}, {"$set": {"ativo": False}})
    assert c.get("/c/atalaia", headers=h).status_code == 404
    fotos = (await DB.veiculos.find_one({"id": "v-strada"}))["fotos"]
    assert c.get(f"/c/atalaia/foto/{fotos[0]}").status_code == 404, "desligado tira as fotos do ar"


def test_suite():
    # Outra suíte do mesmo processo (a do telefone) define PUBLIC_BASE_URL, e
    # com ela o endereço vem da variável, não do Host. Aqui o Host é que vale.
    anterior = os.environ.pop("PUBLIC_BASE_URL", None)
    try:
        _rodar()
    finally:
        if anterior is not None:
            os.environ["PUBLIC_BASE_URL"] = anterior


def _rodar():
    db_mod.get_db = lambda: DB
    rc.get_db = lambda: DB

    async def preparar():
        fotos = await _semear()
        await _config()
        return fotos

    foto_venda, foto_vendido = asyncio.run(preparar())
    c, h = _paginas(foto_venda, foto_vendido)
    asyncio.run(_desligar_e_ia(c, h))
