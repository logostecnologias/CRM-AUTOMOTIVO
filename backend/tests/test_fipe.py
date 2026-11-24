"""Tabela FIPE: busca por texto, vínculo com o carro do estoque e uso pela IA.

A API da Parallelum é dublada em `fipe._get`: o teste não pode depender da
internet nem gastar o teto diário de consultas do servidor.
"""
import asyncio

from fakedb import FakeDB
from fastapi import HTTPException

import ai_veiculos
import db as db_mod
import fipe
import routes.fipe as rf

DB = FakeDB()
TENANT = "t-fipe"
ADMIN = {"id": "u-1", "tenant_id": TENANT, "role": "tenant_admin", "name": "Ana"}
CHAMADAS: list[str] = []

RESPOSTAS = {
    "/cars/brands": [{"code": "21", "name": "Fiat"}, {"code": "23", "name": "GM - Chevrolet"},
                     {"code": "59", "name": "VW - VolksWagen"}],
    "/cars/brands/21/models": [{"code": "9110", "name": "Strada Freedom 1.3 Flex 8V  CS Plus"},
                               {"code": "9111", "name": "Strada Freedom 1.3 Flex 8V CD"},
                               {"code": "500", "name": "Uno Mille 1.0"}],
    "/cars/brands/21/models/9110/years": [{"code": "2024-5", "name": "2024 Flex"}],
    "/cars/brands/21/models/9111/years": [{"code": "2023-5", "name": "2023 Flex"},
                                          {"code": "2024-5", "name": "2024 Flex"},
                                          {"code": "32000-5", "name": "32000 Flex"}],
    "/cars/brands/21/models/9110/years/2024-5": {
        "price": "R$ 86.784,00", "brand": "Fiat", "model": "Strada Freedom 1.3 Flex 8V  CS Plus",
        "modelYear": 2024, "fuel": "Flex", "codeFipe": "001529-7", "referenceMonth": "novembro de 2026"},
    "/cars/brands/21/models/9111/years/2024-5": {
        "price": "R$ 98.306,00", "brand": "Fiat", "model": "Strada Freedom 1.3 Flex 8V CD",
        "modelYear": 2024, "fuel": "Flex", "codeFipe": "001530-0", "referenceMonth": "novembro de 2026"},
    "/cars/brands/23/models": [{"code": str(i), "name": f"ONIX HATCH {i} 1.0"} for i in range(20)],
}


async def falso_get(caminho, ttl):
    CHAMADAS.append(caminho)
    return RESPOSTAS.get(caminho)


def test_suite():
    original = fipe._get
    fipe._get = falso_get
    db_mod.get_db = lambda: DB
    rf.get_db = lambda: DB
    try:
        asyncio.run(_rodar())
    finally:
        fipe._get = original


async def _rodar():
    # --- busca por texto ---
    r = await fipe.buscar("carro", "fiat", "strada freedom", 2024)
    assert r["marca"] == "Fiat" and r["total"] == 2, r
    assert [i["valor"] for i in r["itens"]] == [86784.0, 98306.0], r
    assert r["itens"][1]["referencia"] == "novembro de 2026"
    assert (await fipe.achar_marca("carro", "vw"))["nome"] == "VW - VolksWagen"
    assert await fipe.achar_marca("carro", "xpto") is None

    # Versões demais: não gasta consulta de preço, devolve os nomes para perguntar.
    antes = len(CHAMADAS)
    r = await fipe.buscar("carro", "chevrolet", "onix", 2019)
    assert r["total"] == 20 and r["versoes"] and not r["itens"], r
    assert len(CHAMADAS) - antes == 2, CHAMADAS[antes:]  # marcas + modelos, nada de preço

    # Zero km aparece com o nome certo, e primeiro.
    anos = await fipe.anos("carro", "21", "9111")
    assert anos[0] == {"id": "32000-5", "nome": "Zero km Flex"}, anos

    # Código esquisito não vira caminho de URL.
    try:
        await fipe.modelos("carro", "21/../x")
        assert False
    except fipe.FipeError:
        pass

    # --- vínculo com o carro do estoque ---
    await DB.veiculos.insert_one({"id": "v-1", "tenant_id": TENANT, "marca": "Fiat",
                                  "modelo": "Strada", "versao": "Freedom CD", "ano_modelo": 2024,
                                  "preco": 92900.0, "status": "disponivel", "fotos": []})
    p = await rf.vincular("v-1", rf.VinculoIn(marca_id="21", modelo_id="9111", ano_id="2024-5"), ADMIN)
    assert p["valor"] == 98306.0 and p["consultado_em"]
    v = await DB.veiculos.find_one({"id": "v-1"})
    assert v["fipe"]["codigo"] == "001530-0"
    try:
        await rf.vincular("v-1", rf.VinculoIn(marca_id="21", modelo_id="9111", ano_id="1990-1"), ADMIN)
        assert False
    except HTTPException as e:
        assert e.status_code == 404
    outro = {**ADMIN, "tenant_id": "outra"}
    try:
        await rf.vincular("v-1", rf.VinculoIn(marca_id="21", modelo_id="9111", ano_id="2024-5"), outro)
        assert False
    except HTTPException as e:
        assert e.status_code == 404

    # --- IA: a FIPE do carro do estoque vai na consulta ---
    executar = ai_veiculos.executor(DB, TENANT)
    texto = await executar("consultar_estoque", {"busca": "strada"})
    assert "tabela FIPE R$ 98.306 (referência novembro de 2026)" in texto, texto
    assert "consultar_fipe" in {f.nome for f in ai_veiculos.FERRAMENTAS}

    # Carro do cliente na troca.
    t = await executar("consultar_fipe", {"marca": "fiat", "modelo": "strada freedom", "ano": 2024})
    assert "R$ 86.784" in t and "R$ 98.306" in t, t
    t = await executar("consultar_fipe", {"marca": "chevrolet", "modelo": "onix", "ano": 2019})
    assert "Pergunte ao cliente motor e versão" in t, t

    # --- a trava de preço aceita FIPE consultada, e só ela ---
    cod = ai_veiculos.codigo(v)
    exec_reg, vistos = ai_veiculos.registrar_consultas(executar)
    await exec_reg("consultar_estoque", {"busca": "strada"})
    ok = await ai_veiculos.conferir(
        DB, TENANT, f"A Strada sai por R$ 92.900, abaixo da FIPE de R$ 98.306 [CARRO:{cod}]", vistos)
    assert ok is None, ok

    exec_reg, vistos = ai_veiculos.registrar_consultas(executar)
    await exec_reg("consultar_fipe", {"marca": "fiat", "modelo": "strada freedom", "ano": 2024})
    assert await ai_veiculos.conferir(DB, TENANT, "Na FIPE o seu está em R$ 86.784.", vistos) is None
    motivo = await ai_veiculos.conferir(DB, TENANT, "Pago R$ 90.000 no seu.", vistos)
    assert motivo and "90.000" in motivo, motivo
