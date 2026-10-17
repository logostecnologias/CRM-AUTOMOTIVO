"""Teste do ritmo humano das respostas automáticas e do nó Aguardar.

O que precisa ficar provado:

1. No canal `wuzapi`, cada resposta do bot sai depois do "digitando…" e de
   uma pausa, e a pausa da primeira desconta o tempo que a resposta já levou
   para ser montada (o agente de IA pensando).
2. Na Cloud API nada disso acontece: lá não há bloqueio a evitar.
3. O nó Aguardar dorme de verdade no envio real, com teto. Antes o output
   `delay` era descartado em `_send_outputs` e o fluxo mandava tudo colado.
4. Falha do indicador nunca impede a mensagem de sair.

Nada dorme de verdade: `flow_runtime._dormir` é trocado por um gravador.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste"}.items():
    os.environ.setdefault(k, v)

import httpx

from fakedb import FakeDB

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import flow_engine
import flow_runtime
import whatsapp_client as whatsapp
import wuzapi_client

REAL_DIGITANDO = whatsapp.digitando
CLOUD = whatsapp.Credencial("pn-teste", "token-de-teste", "waba-teste")
WUZ = whatsapp.Credencial("inst-1", "tok-1", None, whatsapp.CANAL_WUZAPI)
TENANT = "t-1"
SESSAO = "s-1"
NUM = "5511900000001"

# Linha do tempo de tudo que aconteceu, na ordem: ("digitando", audio),
# ("dormiu", segundos), ("texto", conteúdo), ("midia", kind).
EVENTOS: list[tuple] = []
FALHA_DIGITANDO = {"ligada": False}

ok = 0


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        raise AssertionError(nome)


async def fake_dormir(segundos):
    EVENTOS.append(("dormiu", segundos))


async def fake_digitando(cred, numero, audio=False):
    if FALHA_DIGITANDO["ligada"]:
        raise RuntimeError("ponte fora do ar")
    if cred.canal == whatsapp.CANAL_WUZAPI:
        EVENTOS.append(("digitando", audio))


async def fake_send_text(cred, numero, texto):
    EVENTOS.append(("texto", texto))
    return "id-1"


async def fake_send_media(cred, numero, kind, **kw):
    EVENTOS.append(("midia", kind))
    return "id-2"


def _conectar_fake():
    """Reaplicado em cada etapa: os dublês são atributos de módulo
    compartilhados com as outras suítes do mesmo processo."""
    db_mod.get_db = lambda: DB
    flow_runtime.get_db = lambda: DB
    flow_runtime._dormir = fake_dormir
    flow_runtime.whatsapp.digitando = fake_digitando
    flow_runtime.whatsapp.send_text = fake_send_text
    flow_runtime.whatsapp.send_media = fake_send_media
    EVENTOS.clear()
    FALHA_DIGITANDO["ligada"] = False


def _tipos():
    return [e[0] for e in EVENTOS]


async def _enviar(cred, outputs, inicio=None):
    await flow_runtime._send_outputs(DB, TENANT, cred, NUM, SESSAO, outputs, inicio=inicio)


async def etapa_wuzapi_digita_antes():
    _conectar_fake()
    await _enviar(WUZ, [{"type": "text", "content": "Olá! Como posso ajudar?"},
                        {"type": "text", "content": "x" * 500}])
    check("digitando, pausa e texto, duas vezes",
          _tipos() == ["digitando", "dormiu", "texto", "digitando", "dormiu", "texto"], EVENTOS)
    curta, longa = EVENTOS[1][1], EVENTOS[4][1]
    check("pausa proporcional ao texto", curta < longa, (curta, longa))
    teto = flow_runtime.RITMO_MAX * flow_runtime.RITMO_VARIACAO[1]
    check("texto longo respeita o teto", longa <= teto + 1e-9, longa)


async def etapa_desconta_tempo_ja_gasto():
    _conectar_fake()
    # A mensagem começou a ser processada há 30s (o agente pensou muito):
    # a primeira resposta sai sem pausa extra, a segunda tem a sua.
    await _enviar(WUZ, [{"type": "text", "content": "Resposta do agente"},
                        {"type": "text", "content": "Mais uma"}],
                  inicio=time.monotonic() - 30)
    check("primeira sem pausa, mas com digitando",
          _tipos() == ["digitando", "texto", "digitando", "dormiu", "texto"], EVENTOS)


async def etapa_audio_grava():
    _conectar_fake()
    await _enviar(WUZ, [{"type": "media", "media_type": "audio",
                         "url": "https://x.com/a.ogg"}])
    check("áudio mostra 'gravando'", EVENTOS[0] == ("digitando", True), EVENTOS)


async def etapa_cloud_sem_ritmo():
    _conectar_fake()
    await _enviar(CLOUD, [{"type": "text", "content": "Oi"},
                          {"type": "text", "content": "Tudo bem?"}])
    check("Cloud API sai sem pausa nem indicador", _tipos() == ["texto", "texto"], EVENTOS)


async def etapa_aguardar():
    _conectar_fake()
    await _enviar(CLOUD, [{"type": "text", "content": "Um momento"},
                          {"type": "delay", "seconds": 5},
                          {"type": "text", "content": "Pronto"},
                          {"type": "delay", "seconds": 3600},
                          {"type": "text", "content": "Fim"}])
    check("Aguardar dorme de verdade, na ordem",
          EVENTOS == [("texto", "Um momento"), ("dormiu", 5.0), ("texto", "Pronto"),
                      ("dormiu", float(flow_runtime.AGUARDAR_MAX)), ("texto", "Fim")], EVENTOS)


async def etapa_motor_guarda_segundos():
    outputs = []
    flow = {"nodes": [], "edges": []}
    node = {"id": "n1", "type": "delay", "data": {"seconds": 20}}
    await flow_engine._process_node(node, flow, {"variables": {}}, outputs)
    check("motor passa os segundos configurados", outputs == [{"type": "delay", "seconds": 20}], outputs)


async def etapa_falha_do_indicador():
    _conectar_fake()
    FALHA_DIGITANDO["ligada"] = True
    await _enviar(WUZ, [{"type": "text", "content": "Oi"}])
    check("mensagem sai mesmo com o indicador falhando", _tipos() == ["texto"], EVENTOS)


async def etapa_presence_nunca_levanta():
    class ClienteQuebrado:
        async def post(self, *a, **k):
            raise httpx.ConnectError("túnel fora")
    original = wuzapi_client._get_client
    wuzapi_client._get_client = lambda: ClienteQuebrado()
    try:
        await REAL_DIGITANDO(WUZ, NUM)
        await REAL_DIGITANDO(CLOUD, NUM)
    finally:
        wuzapi_client._get_client = original
    check("presence engole erro de rede", True)


async def etapa_interromper_no_meio():
    """O botão "Interromper e assumir" apertado enquanto o agente "digita":
    o que ainda não saiu não sai, e fica no histórico o que ia sair."""
    _conectar_fake()
    await DB.conversation_sessions.insert_one({
        "id": "s-int", "tenant_id": TENANT, "status": "ativa",
        "status_atendimento": "bot", "awaiting": {"node_id": "m1"},
        "whatsapp_connection_id": "c-1", "ia_agente_id": "ag-1", "bot_id": None})

    for uid in ("u-1", "u-2"):
        await DB.user_connection_access.insert_one(
            {"tenant_id": TENANT, "user_id": uid, "whatsapp_connection_id": "c-1"})
    from routes import atendimento
    atendimento.get_db = lambda: DB

    async def assume_durante_pausa(segundos):
        EVENTOS.append(("dormiu", segundos))
        await atendimento.assume("s-int", {"id": "u-1", "name": "Ana", "role": "agent",
                                           "tenant_id": TENANT})
    flow_runtime._dormir = assume_durante_pausa
    await flow_runtime._send_outputs(
        DB, TENANT, WUZ, NUM, "s-int",
        [{"type": "text", "content": "O Onix sai por R$ 12.000"},
         {"type": "text", "content": "Posso reservar?"}])
    check("nenhuma mensagem saiu", "texto" not in _tipos(), EVENTOS)

    s = await DB.conversation_sessions.find_one({"id": "s-int"})
    check("conversa com a pessoa que interrompeu",
          s["status_atendimento"] == "em_atendimento" and s["atendente_id"] == "u-1"
          and s["status"] == "aguardando_humano" and s["awaiting"] is None, s)
    logs = [m["content"] async for m in DB.messages_log.find({"session_id": "s-int"})]
    check("histórico diz quem interrompeu o agente",
          any("Ana interrompeu o agente de IA" in t for t in logs), logs)
    check("histórico guarda o que não saiu",
          any("não enviada" in t and "R$ 12.000" in t and "Posso reservar" in t for t in logs), logs)

    # Outro atendente não toma a conversa de quem já está nela.
    try:
        await atendimento.assume("s-int", {"id": "u-2", "name": "Bia", "role": "agent",
                                           "tenant_id": TENANT})
        check("segundo atendente recusado", False)
    except Exception as e:
        check("segundo atendente recusado", getattr(e, "status_code", None) == 409, e)


async def etapa_motor_nao_devolve_ao_bot():
    """A gravação final do motor não passa por cima de quem assumiu."""
    _conectar_fake()
    await DB.conversation_sessions.insert_one({
        "id": "s-int2", "tenant_id": TENANT, "status": "aguardando_humano",
        "status_atendimento": "em_atendimento", "atendente_id": "u-1"})
    await DB.conversation_sessions.update_one(
        {"id": "s-int2", "status_atendimento": {"$ne": "em_atendimento"}},
        {"$set": {"status": "ativa", "status_atendimento": "bot"}})
    s = await DB.conversation_sessions.find_one({"id": "s-int2"})
    check("filtro do motor preserva o atendimento", s["status_atendimento"] == "em_atendimento", s)


async def _assincronas():
    await etapa_wuzapi_digita_antes()
    await etapa_desconta_tempo_ja_gasto()
    await etapa_audio_grava()
    await etapa_cloud_sem_ritmo()
    await etapa_aguardar()
    await etapa_motor_guarda_segundos()
    await etapa_falha_do_indicador()
    await etapa_presence_nunca_levanta()
    await etapa_interromper_no_meio()
    await etapa_motor_nao_devolve_ao_bot()


def test_suite():
    asyncio.run(_assincronas())
    print(f"\n{ok} verificações passaram")


if __name__ == "__main__":
    test_suite()
