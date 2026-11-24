"""Atalhos de funil na conversa e aviso no grupo da equipe (Atalaia, 24/11/2026)."""
import asyncio

from fakedb import FakeDB
from fastapi import HTTPException

import aviso_grupo
import db as db_mod
import deals
import meta_conversoes
import routes.atendimento as ra
import routes.aviso_grupo as rag
import whatsapp_client as whatsapp
import wuzapi_client

DB = FakeDB()
TENANT = "t-aviso"
ADMIN = {"id": "u-1", "tenant_id": TENANT, "role": "tenant_admin", "name": "Ana", "email": "a@x.com"}
GRUPO = "120363000000000001@g.us"
ENVIADOS: list[tuple] = []
FALHAR = {"sim": False}


async def fake_send_text(cred, numero, texto):
    if FALHAR["sim"]:
        raise whatsapp.WhatsAppError("ponte fora do ar")
    ENVIADOS.append((numero, texto))
    return "id-1"


def _conectar_fake():
    db_mod.get_db = lambda: DB
    ra.get_db = lambda: DB
    rag.get_db = lambda: DB
    aviso_grupo.whatsapp.send_text = fake_send_text
    aviso_grupo.whatsapp.credencial = lambda conn: whatsapp.Credencial("i", "tok", None, "wuzapi")


async def _semear():
    DB._cols.clear()
    ENVIADOS.clear()
    FALHAR["sim"] = False
    etapas = [
        {"id": "e-novo", "nome": "Novo lead", "tipo": "aberta", "ordem": 0},
        {"id": "e-agend", "nome": "Visita agendada", "tipo": "aberta", "ordem": 1},
        {"id": "e-real", "nome": "Visita Realizada", "tipo": "aberta", "ordem": 2},
        {"id": "e-vend", "nome": "Vendido", "tipo": "ganho", "ordem": 3},
        {"id": "e-perd", "nome": "Perdido", "tipo": "perdido", "ordem": 4},
    ]
    await DB.pipelines.insert_one({"id": "p-1", "tenant_id": TENANT, "nome": "Funil",
                                   "etapas": etapas, "created_at": "2026-01-01"})
    await DB.whatsapp_connections.insert_one({"id": "conn-1", "tenant_id": TENANT,
                                              "canal": "wuzapi", "nome": "Loja"})
    await DB.contacts.insert_one({"id": "c-1", "tenant_id": TENANT, "nome": "João",
                                  "numero_whatsapp": "5585999998888"})
    await DB.conversation_sessions.insert_one({
        "id": "s-1", "tenant_id": TENANT, "contact_id": "c-1",
        "whatsapp_connection_id": "conn-1", "status_atendimento": "em_atendimento"})


async def _esperar():
    await aviso_grupo.aguardar_pendentes()
    await meta_conversoes.aguardar_pendentes()


async def _etapas_atalho():
    r = await ra.funil_da_conversa("s-1", ADMIN)
    assert r["visita"] == {"id": "e-real", "nome": "Visita Realizada"}, r
    assert r["venda"] == {"id": "e-vend", "nome": "Vendido"}, r
    assert r["negocio"] is None

    # Sem negócio: o botão cria, na etapa da visita, com quem clicou de dono.
    r = await ra.funil_acao("s-1", ra.FunilAcaoIn(acao="visita"), ADMIN)
    d = await DB.deals.find_one({"id": r["negocio_id"]})
    assert d["etapa_id"] == "e-real" and d["status"] == "aberto" and d["responsavel_id"] == "u-1"
    assert d["contact_id"] == "c-1"

    # Venda: o mesmo negócio vai para Ganho, com valor, data e ciclo.
    r2 = await ra.funil_acao("s-1", ra.FunilAcaoIn(acao="venda", valor=113000), ADMIN)
    assert r2["negocio_id"] == d["id"]
    d = await DB.deals.find_one({"id": d["id"]})
    assert d["status"] == "ganho" and d["valor"] == 113000 and d["fechado_em"]
    assert d["ciclo_dias"] is not None
    tipos = [e["tipo"] for e in await DB.deal_events.find({"deal_id": d["id"]}).to_list(20)]
    assert tipos == ["criado", "valor", "ganho"], tipos
    log = await DB.messages_log.find({"session_id": "s-1"}).to_list(10)
    assert any("registrou a venda" in m["content"] for m in log)
    await _esperar()

    # Ganho não é "aberto": um clique novo cria outro negócio, não reabre a venda.
    r3 = await ra.funil_acao("s-1", ra.FunilAcaoIn(acao="visita"), ADMIN)
    assert r3["negocio_id"] != d["id"]

    # Funil sem etapa de visita realizada: o botão some, e a rota recusa.
    await DB.pipelines.update_one({"id": "p-1"}, {"$set": {"etapas": [
        {"id": "e-novo", "nome": "Novo lead", "tipo": "aberta", "ordem": 0},
        {"id": "e-vend", "nome": "Vendido", "tipo": "ganho", "ordem": 1}]}})
    await DB.deals.delete_many({})
    r = await ra.funil_da_conversa("s-1", ADMIN)
    assert r["visita"] is None
    try:
        await ra.funil_acao("s-1", ra.FunilAcaoIn(acao="visita"), ADMIN)
        assert False, "devia recusar"
    except HTTPException as e:
        assert e.status_code == 400

    # Atendente sem acesso à conexão não mexe.
    agente = {**ADMIN, "id": "u-2", "role": "agent"}
    try:
        await ra.funil_acao("s-1", ra.FunilAcaoIn(acao="venda"), agente)
        assert False, "devia recusar"
    except HTTPException as e:
        assert e.status_code == 403


async def _aviso():
    assert wuzapi_client.codigo_do_convite(
        "https://chat.whatsapp.com/BpXHcPM9dWJ2a9PgenXQH5?s=sw&p=i&iam=2") == "BpXHcPM9dWJ2a9PgenXQH5"
    assert wuzapi_client.codigo_do_convite("oi") is None

    # Ligar sem grupo é recusado.
    try:
        await rag.salvar(rag.ConfigIn(ativo=True, connection_id="conn-1", etapas=["e-agend"]), ADMIN)
        assert False
    except HTTPException as e:
        assert e.status_code == 422
    cfg = await rag.salvar(rag.ConfigIn(ativo=True, connection_id="conn-1", grupo_jid=GRUPO,
                                        grupo_nome="R3 marketing - Atalaia",
                                        etapas=["e-agend", "nao-existe"]), ADMIN)
    assert cfg["etapas"] == ["e-agend"]

    # Conexão da API oficial não serve.
    await DB.whatsapp_connections.insert_one({"id": "conn-cloud", "tenant_id": TENANT,
                                              "canal": "cloud_api"})
    try:
        await rag.grupos("conn-cloud", ADMIN)
        assert False
    except HTTPException as e:
        assert e.status_code == 400

    # Entrar na etapa configurada avisa o grupo, com cliente, carro e horário.
    await DB.scheduling_settings.insert_one({"tenant_id": TENANT, "fuso": "America/Sao_Paulo"})
    await DB.appointments.insert_one({"id": "a-1", "tenant_id": TENANT, "contact_id": "c-1",
                                      "status": "agendado", "inicio": "2099-12-01T13:00:00+00:00"})
    deal = {"id": "d-1", "tenant_id": TENANT, "pipeline_id": "p-1", "contact_id": "c-1",
            "titulo": "Strada Freedom 2026", "valor": 113000.0, "responsavel_id": "u-1",
            "etapa_id": "e-agend", "status": "aberto"}
    await DB.users.insert_one({"id": "u-1", "tenant_id": TENANT, "name": "Ana"})
    await DB.deals.insert_one(dict(deal))
    await deals.registrar_evento(DB, deal, "etapa", {"name": "Agente de IA Matheus"})
    await _esperar()
    assert len(ENVIADOS) == 1, ENVIADOS
    numero, texto = ENVIADOS[0]
    assert numero == GRUPO
    for trecho in ("Visita agendada", "João", "(85) 99999-8888", "Strada Freedom 2026",
                   "R$ 113.000,00", "às 10:00", "Responsável: Ana", "Agente de IA Matheus"):
        assert trecho in texto, (trecho, texto)

    # Mesmo negócio na mesma etapa: não avisa de novo.
    await deals.registrar_evento(DB, deal, "etapa", {"name": "Ana"})
    await _esperar()
    assert len(ENVIADOS) == 1

    # Etapa que não está na configuração: nada.
    await DB.deals.update_one({"id": "d-1"}, {"$set": {"etapa_id": "e-novo"}})
    await deals.registrar_evento(DB, deal, "etapa", {"name": "Ana"})
    await _esperar()
    assert len(ENVIADOS) == 1

    # Falha da ponte: fica o erro na configuração e o par é liberado para tentar de novo.
    deal2 = {**deal, "id": "d-2"}
    await DB.deals.insert_one(dict(deal2))
    FALHAR["sim"] = True
    await deals.registrar_evento(DB, deal2, "criado", {"name": "Ana"})
    await _esperar()
    cfg = await aviso_grupo.configuracao(DB, TENANT)
    assert "ponte fora do ar" in (cfg["ultimo_erro"] or ""), cfg
    FALHAR["sim"] = False
    await deals.registrar_evento(DB, deal2, "etapa", {"name": "Ana"})
    await _esperar()
    assert len(ENVIADOS) == 2
    assert (await aviso_grupo.configuracao(DB, TENANT))["ultimo_erro"] is None

    # Desligado: nada sai.
    await rag.salvar(rag.ConfigIn(ativo=False, connection_id="conn-1", grupo_jid=GRUPO,
                                  etapas=["e-agend"]), ADMIN)
    deal3 = {**deal, "id": "d-3"}
    await DB.deals.insert_one(dict(deal3))
    await deals.registrar_evento(DB, deal3, "criado", {"name": "Ana"})
    await _esperar()
    assert len(ENVIADOS) == 2


def test_suite():
    # `whatsapp_client` é o mesmo módulo para todos os testes do processo: os
    # dublês saem no fim, senão a suíte seguinte herda um envio falso.
    originais = (whatsapp.send_text, whatsapp.credencial)
    _conectar_fake()

    async def rodar():
        await _semear()
        await _etapas_atalho()
        await _semear()
        await _aviso()

    try:
        asyncio.run(rodar())
    finally:
        whatsapp.send_text, whatsapp.credencial = originais
