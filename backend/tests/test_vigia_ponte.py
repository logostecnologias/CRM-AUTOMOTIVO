"""O vigia da ponte WuzAPI inteira (`health_monitor._vigiar_ponte`).

Nasceu da queda de 03/11/2026: a WuzAPI foi apagada do servidor e as conexões
seguiram "conectado" por três dias e meio, porque a falha de rede de uma
conexão, de propósito, não muda o status dela. O que se confere aqui:

  - uma falha só não derruba ninguém (reinício de segundos da ponte);
  - a segunda falha seguida marca as conexões do canal como desconectadas,
    com o motivo, e não toca nas da Cloud API;
  - a ponte de volta reconsulta cada conexão na hora e devolve o "conectado",
    limpando o aviso.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _chave, _valor in {
    "MONGO_URL": "mongodb://fake/", "DB_NAME": "fake", "JWT_SECRET": "teste",
    "CREDENTIALS_KEY": "VlKvCmSGH9QsR1bwg10fq1e4oiOZ_0MP3B-YxhSL1oo=",
}.items():
    os.environ.setdefault(_chave, _valor)

from fakedb import FakeDB

import cripto
import health_monitor
import wuzapi_client

DB = FakeDB()
RESPOSTA = {"ping": None}


def _conectar_fake():
    health_monitor.get_db = lambda: DB
    health_monitor._ponte.update({"falhas": 0, "fora_desde": None, "motivo": None})

    async def ping():
        return RESPOSTA["ping"]

    async def connection_state(token):
        return {"connected": True, "loggedIn": True}

    async def marcar_inicio(db, conn_id):
        return None

    wuzapi_client.ping = ping
    wuzapi_client.connection_state = connection_state
    health_monitor.aquecimento.marcar_inicio = marcar_inicio


async def etapa_semear():
    bloco = cripto.cifrar("tok-instancia")
    await DB.whatsapp_connections.insert_one({
        "id": "w1", "tenant_id": "t1", "canal": "wuzapi", "status": "conectado",
        "token_cifrado": bloco, "ultimo_erro": None})
    await DB.whatsapp_connections.insert_one({
        "id": "c1", "tenant_id": "t1", "canal": "cloud_api", "status": "conectado",
        "phone_number_id": "123"})


async def etapa_uma_falha_nao_derruba():
    RESPOSTA["ping"] = "sem resposta (ConnectError)"
    await health_monitor._vigiar_ponte()
    w1 = await DB.whatsapp_connections.find_one({"id": "w1"})
    assert w1["status"] == "conectado", "uma falha só não pode derrubar a conexão"
    assert health_monitor.ponte_fora() is None


async def etapa_segunda_falha_marca_fora():
    await health_monitor._vigiar_ponte()
    w1 = await DB.whatsapp_connections.find_one({"id": "w1"})
    c1 = await DB.whatsapp_connections.find_one({"id": "c1"})
    assert w1["status"] == "desconectado"
    assert "não está respondendo" in w1["ultimo_erro"]
    assert c1["status"] == "conectado", "a Cloud API não depende da ponte"
    fora = health_monitor.ponte_fora()
    assert fora and fora["motivo"].startswith("sem resposta")


async def etapa_ponte_volta():
    RESPOSTA["ping"] = None
    await health_monitor._vigiar_ponte()
    w1 = await DB.whatsapp_connections.find_one({"id": "w1"})
    assert w1["status"] == "conectado", "a volta da ponte reconsulta na hora"
    assert w1["ultimo_erro"] is None, "o aviso da queda some com o número de pé"
    assert health_monitor.ponte_fora() is None


def test_suite():
    # Os dublês são atributos de módulo compartilhados no processo do pytest:
    # devolvidos no fim para não vazarem para a suíte seguinte.
    originais = (health_monitor.get_db, wuzapi_client.ping, wuzapi_client.connection_state,
                 health_monitor.aquecimento.marcar_inicio)
    _conectar_fake()

    async def rodar():
        await etapa_semear()
        await etapa_uma_falha_nao_derruba()
        await etapa_segunda_falha_marca_fora()
        await etapa_ponte_volta()

    try:
        asyncio.run(rodar())
    finally:
        (health_monitor.get_db, wuzapi_client.ping, wuzapi_client.connection_state,
         health_monitor.aquecimento.marcar_inicio) = originais
        health_monitor._ponte.update({"falhas": 0, "fora_desde": None, "motivo": None})


if __name__ == "__main__":
    test_suite()
    print("ok")
