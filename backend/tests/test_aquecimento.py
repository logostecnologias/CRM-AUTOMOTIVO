"""Cuidados do número não oficial: aquecimento, espaçamento e leitura.

Mongo falso, ponte dublada. Cobre os três cuidados de 16/10/2026 e o bug que
apareceu junto: a migração que marcava toda conexão WuzAPI como desconectada a
cada reinício do servidor.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("MONGO_URL", "mongodb://x/")
os.environ.setdefault("DB_NAME", "x")
os.environ.setdefault("JWT_SECRET", "x")

from fakedb import FakeDB

import db as db_mod
DB = FakeDB()

import aquecimento
import campaign_runner
import health_monitor
import migrations
import whatsapp_client
import wuzapi_client

FALHAS = []
TENANT = "t-aq"


def check(nome, cond, extra=None):
    if cond:
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        FALHAS.append(nome)


def _conectar_fake():
    db_mod.get_db = lambda: DB
    for mod in (campaign_runner, health_monitor, migrations):
        mod.get_db = lambda: DB


def _iso(dias=0, horas=0):
    return (datetime.now(timezone.utc) - timedelta(days=dias, hours=horas)).isoformat()


def _conn(cid="c1", canal="wuzapi", dias=0, **extra):
    return {"id": cid, "tenant_id": TENANT, "canal": canal, "status": "conectado",
            "aquecimento_desde": _iso(dias) if dias is not None else None, **extra}


async def etapa_situacao():
    print("\n[o limite cresce com a idade do numero]")
    check("cloud api nao tem aquecimento", aquecimento.situacao(_conn(canal="cloud_api")) is None)
    check("sem data de inicio nao limita", aquecimento.situacao(_conn(dias=None)) is None)
    s = aquecimento.situacao(_conn(dias=0))
    check("dia 1 limita a 20", s and s["dia"] == 1 and s["limite_24h"] == 20, s)
    check("dia 6 limita a 50", aquecimento.situacao(_conn(dias=5))["limite_24h"] == 50)
    check("dia 11 limita a 150", aquecimento.situacao(_conn(dias=10))["limite_24h"] == 150)
    check("depois de 14 dias nao ha limite", aquecimento.situacao(_conn(dias=14)) is None)


async def etapa_marcar_inicio():
    print("\n[o inicio e gravado uma vez so]")
    await DB.whatsapp_connections.insert_one(_conn("c-ini", dias=None))
    await aquecimento.marcar_inicio(DB, "c-ini")
    primeiro = (await DB.whatsapp_connections.find_one({"id": "c-ini"}))["aquecimento_desde"]
    check("grava na primeira conexao", bool(primeiro))
    await DB.whatsapp_connections.update_one(
        {"id": "c-ini"}, {"$set": {"aquecimento_desde": _iso(dias=9)}})
    await aquecimento.marcar_inicio(DB, "c-ini")
    depois = (await DB.whatsapp_connections.find_one({"id": "c-ini"}))["aquecimento_desde"]
    check("reconectar nao recomeca a contagem", depois != primeiro and depois < primeiro)


async def _semear_envios(conn, n, horas_atras=1, campanha="camp-aq"):
    await DB.campaigns.update_one(
        {"id": campanha},
        {"$set": {"id": campanha, "tenant_id": TENANT, "whatsapp_connection_id": conn["id"]}},
        upsert=True)
    for i in range(n):
        await DB.campaign_recipients.insert_one({
            "id": f"{campanha}-{horas_atras}-{i}", "tenant_id": TENANT, "campaign_id": campanha,
            "status": "enviado", "sent_at": _iso(horas=horas_atras)})


async def etapa_limite_de_24h():
    print("\n[limite de campanha numa janela de 24h]")
    conn = _conn("c-lim", dias=0)
    await _semear_envios(conn, 19)
    check("19 de 20 ainda deixa enviar",
          await aquecimento.motivo_para_esperar(DB, conn) is None)
    await _semear_envios(conn, 5, horas_atras=30)
    check("envio de mais de 24h atras nao conta",
          await aquecimento.motivo_para_esperar(DB, conn) is None)
    await _semear_envios(conn, 1, horas_atras=2)
    motivo = await aquecimento.motivo_para_esperar(DB, conn)
    check("no 20o segura e diz por que", motivo and "20 mensagens" in motivo, motivo)


async def etapa_campanha_espera():
    print("\n[a campanha espera em vez de pausar]")
    conn = _conn("c-camp", dias=0, nome="Loja")
    await DB.whatsapp_connections.insert_one(conn)
    await DB.campaigns.insert_one({"id": "camp-espera", "tenant_id": TENANT,
                                   "whatsapp_connection_id": "c-camp", "status": "enviando"})
    await DB.campaign_recipients.insert_one({"id": "r-pend", "tenant_id": TENANT,
                                             "campaign_id": "camp-espera", "status": "pendente"})
    await _semear_envios(conn, 20, campanha="camp-antiga")

    dormidas = []

    async def dormir(s):
        dormidas.append(s)
        # Segunda volta: alguém pausou pela tela, e o runner sai.
        await DB.campaigns.update_one({"id": "camp-espera"}, {"$set": {"status": "pausada"}})

    cred = whatsapp_client.Credencial("inst", "tok", None, "wuzapi")
    orig_dormir, orig_cred = campaign_runner._dormir, campaign_runner.whatsapp.credencial
    campaign_runner._dormir = dormir
    campaign_runner.whatsapp.credencial = lambda c: cred
    try:
        await campaign_runner._run_campaign("camp-espera")
    finally:
        campaign_runner._dormir = orig_dormir
        campaign_runner.whatsapp.credencial = orig_cred
    camp = await DB.campaigns.find_one({"id": "camp-espera"})
    r = await DB.campaign_recipients.find_one({"id": "r-pend"})
    check("nao tocou no destinatario", r["status"] == "pendente", r)
    check("esperou a janela", dormidas == [campaign_runner.ESPERA_AQUECIMENTO], dormidas)
    check("e deixou o motivo na campanha",
          "aquecimento" in (camp.get("aguardando_aquecimento") or ""), camp)


async def etapa_espacar():
    print("\n[envio ativo espacado por conexao]")
    dormidas = []

    async def dormir(s):
        dormidas.append(s)

    orig = aquecimento._dormir
    aquecimento._dormir = dormir
    aquecimento._ultimo.clear()
    try:
        await aquecimento.espacar(_conn("c-esp"))
        check("o primeiro sai na hora", dormidas == [], dormidas)
        await aquecimento.espacar(_conn("c-esp"))
        check("o segundo espera o intervalo",
              len(dormidas) == 1 and aquecimento.ESPACO[0] - 1 < dormidas[0] <= aquecimento.ESPACO[1],
              dormidas)
        await aquecimento.espacar(_conn("c-outra"))
        check("outra conexao nao espera", len(dormidas) == 1, dormidas)
        await aquecimento.espacar(_conn("c-cloud", canal="cloud_api"))
        await aquecimento.espacar(_conn("c-cloud", canal="cloud_api"))
        check("cloud api nao espera", len(dormidas) == 1, dormidas)
    finally:
        aquecimento._dormir = orig


async def etapa_marcar_lida():
    print("\n[os dois tiques azuis na wuzapi]")
    pedidos = []

    async def mark_read(token, ids, numero):
        pedidos.append((token, ids, numero))

    orig = wuzapi_client.mark_read
    wuzapi_client.mark_read = mark_read
    try:
        cred = whatsapp_client.Credencial("inst", "tok", None, "wuzapi")
        await whatsapp_client.marcar_lida(cred, "MSG1", numero="5598999990000")
        check("marca pela ponte com o numero da conversa",
              pedidos == [("tok", ["MSG1"], "5598999990000")], pedidos)
        await whatsapp_client.marcar_lida(cred, "MSG2")
        check("sem numero nao chama a ponte", len(pedidos) == 1, pedidos)
    finally:
        wuzapi_client.mark_read = orig


async def etapa_reinicio_nao_desconecta():
    print("\n[reiniciar o servidor nao derruba a conexao wuzapi]")
    await DB.whatsapp_connections.insert_one(
        {"id": "c-mig", "tenant_id": TENANT, "canal": "wuzapi", "status": "conectado",
         "phone_number_id": None, "created_at": _iso(dias=4)})
    await DB.whatsapp_connections.insert_one(
        {"id": "c-velha", "tenant_id": TENANT, "status": "conectado", "phone_number_id": None})
    await migrations.limpar_conexoes_da_api_antiga(DB)
    wz = await DB.whatsapp_connections.find_one({"id": "c-mig"})
    velha = await DB.whatsapp_connections.find_one({"id": "c-velha"})
    check("a wuzapi continua conectada", wz["status"] == "conectado", wz["status"])
    check("a da api antiga continua sendo desligada", velha["status"] == "desconectado")
    await migrations.iniciar_aquecimento(DB)
    wz = await DB.whatsapp_connections.find_one({"id": "c-mig"})
    check("conexao antiga ganha a data de criacao como inicio",
          wz.get("aquecimento_desde") == wz["created_at"], wz)


async def etapa_vigia_wuzapi():
    print("\n[o vigia acerta o status pela ponte]")
    await DB.whatsapp_connections.insert_one(
        {"id": "c-vig", "tenant_id": TENANT, "canal": "wuzapi", "status": "desconectado"})
    estado = {"connected": True, "loggedIn": True}

    async def connection_state(token):
        if estado is None:
            raise wuzapi_client.WuzapiError("rede")
        return estado

    cred = whatsapp_client.Credencial("inst", "tok", None, "wuzapi")
    orig_estado, orig_cred = wuzapi_client.connection_state, health_monitor.whatsapp.credencial
    wuzapi_client.connection_state = connection_state
    health_monitor.whatsapp.credencial = lambda c: cred
    try:
        await health_monitor._probe_wuzapi(await DB.whatsapp_connections.find_one({"id": "c-vig"}))
        doc = await DB.whatsapp_connections.find_one({"id": "c-vig"})
        check("sessao de pe vira conectado", doc["status"] == "conectado", doc["status"])
        check("e comeca o aquecimento", bool(doc.get("aquecimento_desde")))
        estado = None
        await health_monitor._probe_wuzapi(doc)
        doc = await DB.whatsapp_connections.find_one({"id": "c-vig"})
        check("ponte sem resposta nao muda o status", doc["status"] == "conectado", doc["status"])
        estado = {"connected": False, "loggedIn": False}
        await health_monitor._probe_wuzapi(doc)
        doc = await DB.whatsapp_connections.find_one({"id": "c-vig"})
        check("sessao caida vira desconectado", doc["status"] == "desconectado", doc["status"])
    finally:
        wuzapi_client.connection_state = orig_estado
        health_monitor.whatsapp.credencial = orig_cred


async def _tudo():
    _conectar_fake()
    await etapa_situacao()
    await etapa_marcar_inicio()
    await etapa_limite_de_24h()
    await etapa_campanha_espera()
    await etapa_espacar()
    await etapa_marcar_lida()
    await etapa_reinicio_nao_desconecta()
    await etapa_vigia_wuzapi()


def test_suite():
    FALHAS.clear()
    asyncio.run(_tudo())
    assert not FALHAS, FALHAS


if __name__ == "__main__":
    test_suite()
