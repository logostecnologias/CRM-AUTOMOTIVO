"""Temperatura, pagamento e carro de interesse no negócio; nota interna na
conversa (visual do Carmillion, 24/11/2026)."""
import asyncio

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
import routes.atendimento as ra
import routes.deals as rd

DB = FakeDB()
TENANT = "t-etiq"
ADMIN = {"id": "u-1", "tenant_id": TENANT, "role": "tenant_admin", "name": "Ana", "email": "a@x.com"}
AGENTE = {"id": "u-2", "tenant_id": TENANT, "role": "agent", "name": "Bia", "email": "b@x.com"}


def _conectar_fake():
    db_mod.get_db = lambda: DB
    ra.get_db = lambda: DB
    rd.get_db = lambda: DB


async def _semear():
    await DB.pipelines.insert_one({"id": "p1", "tenant_id": TENANT, "nome": "Vendas", "etapas": [
        {"id": "e1", "nome": "Novo", "tipo": "aberta", "ordem": 0, "cor": "#000"}]})
    await DB.contacts.insert_one({"id": "c1", "tenant_id": TENANT, "nome": "Caio", "numero_whatsapp": "5511999990000"})
    await DB.veiculos.insert_one({"id": "v1", "tenant_id": TENANT, "marca": "Chevrolet", "modelo": "Onix",
                                  "ano_modelo": 2019, "placa": "ABC1D23", "status": "disponivel"})
    await DB.veiculos.insert_one({"id": "v-outro", "tenant_id": "outra", "marca": "Fiat"})
    await DB.conversation_sessions.insert_one({"id": "s1", "tenant_id": TENANT, "contact_id": "c1",
                                               "whatsapp_connection_id": "w1", "last_message": {"content": "oi"}})


async def _etiquetas():
    criado = await rd.create_deal(rd.DealIn(titulo="Onix", contact_id="c1", pipeline_id="p1",
                                            temperatura="Quente", pagamento=["troca", "financiamento", "troca"],
                                            veiculo_id="v1"), user=ADMIN)
    deal = criado.get("deal", criado)
    assert deal["temperatura"] == "quente"
    assert deal["pagamento"] == ["financiamento", "troca"]  # ordem fixa, sem repetir
    assert deal["veiculo_id"] == "v1"

    quadro = await rd.board("p1", user=ADMIN)
    cartao = quadro["colunas"][0]["deals"][0]
    assert cartao["veiculo"]["nome"] == "Chevrolet Onix 2019" and cartao["veiculo"]["placa"] == "ABC1D23"

    # Vazio limpa.
    await rd.update_deal(deal["id"], rd.DealPatch(temperatura="", pagamento=[], veiculo_id=""), user=ADMIN)
    salvo = await DB.deals.find_one({"id": deal["id"]})
    assert salvo["temperatura"] is None and salvo["pagamento"] == [] and salvo["veiculo_id"] is None

    for patch in (rd.DealPatch(temperatura="fervendo"), rd.DealPatch(pagamento=["cheque"]),
                  rd.DealPatch(veiculo_id="v-outro")):  # carro de outra empresa
        try:
            await rd.update_deal(deal["id"], patch, user=ADMIN)
            raise AssertionError(f"deveria recusar {patch}")
        except HTTPException as e:
            assert e.status_code in (400, 422)


async def _nota():
    doc = await ra.nota_interna("s1", ra.NotaIn(content="  Quer blindagem  "), user=ADMIN)
    assert doc["direction"] == "nota" and doc["content"] == "Quer blindagem"
    assert doc["meta"]["autor_nome"] == "Ana"
    # A prévia da lista continua sendo a última mensagem trocada com o contato.
    s = await DB.conversation_sessions.find_one({"id": "s1"})
    assert s["last_message"] == {"content": "oi"}
    # Anotar não assume a conversa.
    assert s.get("status_atendimento") is None

    # Atendente sem acesso à conexão não anota.
    try:
        await ra.nota_interna("s1", ra.NotaIn(content="x"), user=AGENTE)
        raise AssertionError("atendente sem acesso anotou")
    except HTTPException as e:
        assert e.status_code == 403
    try:
        await ra.nota_interna("s1", ra.NotaIn(content="   "), user=ADMIN)
        raise AssertionError("nota vazia passou")
    except HTTPException as e:
        assert e.status_code == 422


def test_suite():
    _conectar_fake()

    async def rodar():
        await _semear()
        await _etiquetas()
        await _nota()

    asyncio.run(rodar())
