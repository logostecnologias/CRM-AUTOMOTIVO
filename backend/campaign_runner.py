"""Motor de disparo das campanhas — mesmo padrão start/stop do health_monitor.

Duas camadas, por motivos diferentes:

  - um **laço supervisor** (`_loop`), que a cada TICK promove campanha agendada
    cuja hora chegou e garante que exista um runner para cada campanha
    enviando. Ele não envia nada;
  - um **runner por campanha**, que envia um destinatário por vez com pausa
    entre um e outro. Uma task por campanha, em vez de um laço só varrendo
    tudo, porque cada campanha tem sua própria cadência: duas rodando juntas
    não podem se atrapalhar no ritmo.

A cadência continua sendo o coração disto, com outro motivo desde a mudança
para a Cloud API oficial. Antes ela existia para o número não ser bloqueado
pelo WhatsApp, risco real de API não oficial. Agora ela existe para respeitar
a vazão do número (80 mensagens por segundo por padrão, e menos que isso no
limite diário de contatos iniciados por empresa) e para o disparo não ocupar a
conexão inteira: enquanto 2.000 modelos saem, a mesma conexão precisa
responder quem está conversando. O `jitter` ficou porque continua sendo bom
não empilhar picos exatamente iguais, mas ele deixou de ser disfarce.

Também mudou a natureza da recusa: quem está fora da janela de 24h só recebe
modelo aprovado, e isso é decidido em `campaigns.send_one`, não aqui.

Retomada não precisa de nada especial porque o estado não está aqui: ele está
em `campaign_recipients.status`. Depois de um restart, o supervisor reencontra
a campanha em `enviando` e o runner continua pelos `pendente` que sobraram.
"""
import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from pymongo import ReturnDocument

import aquecimento
import campaigns
import whatsapp_client as whatsapp
from db import get_db

logger = logging.getLogger("zappzen.campaign_runner")

TICK = 5                    # segundos entre varreduras do supervisor
STARTUP_DELAY = 15          # deixa o boot/índices terminarem antes de disparar
JITTER = (0.75, 1.4)        # multiplicador aleatório do intervalo entre envios
# Destinatário travado em "enviando" há mais que isto voltou de um processo que
# morreu no meio do envio. Generoso de propósito: o envio de um vídeo grande
# leva tempo, e reenviar por impaciência manda a mensagem duas vezes.
CLAIM_STALE_MIN = 15
# De quanto em quanto tempo a campanha parada pelo aquecimento confere se a
# janela de 24h já liberou mais um envio.
ESPERA_AQUECIMENTO = 10 * 60

_dormir = asyncio.sleep   # trocável no teste
_task: asyncio.Task | None = None
_runners: dict[str, asyncio.Task] = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _intervalo(campaign: dict) -> float:
    por_minuto = max(1, int((campaign.get("cadencia") or {}).get("por_minuto") or 12))
    return 60.0 / por_minuto


async def _pausar(db, campaign_id: str, motivo: str):
    logger.info("Campanha %s pausada: %s", campaign_id, motivo)
    await db.campaigns.update_one(
        {"id": campaign_id},
        {"$set": {"status": "pausada", "motivo_pausa": motivo, "updated_at": _now()}},
    )


async def _reclaim_stale(db, campaign_id: str):
    """Devolve para a fila quem ficou preso em "enviando".

    Só acontece quando o processo morre entre o claim e a gravação do
    resultado. Sem isto a campanha nunca fecharia: ficaria com destinatários
    que não estão pendentes nem enviados.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CLAIM_STALE_MIN)).isoformat()
    res = await db.campaign_recipients.update_many(
        {"campaign_id": campaign_id, "status": "enviando", "claimed_at": {"$lt": cutoff}},
        {"$set": {"status": "pendente", "claimed_at": None}},
    )
    if res.modified_count:
        logger.info("Campanha %s: %d destinatários travados devolvidos à fila",
                    campaign_id, res.modified_count)


async def _claim(db, campaign_id: str) -> dict | None:
    """Toma posse do próximo destinatário pendente, atomicamente.

    `find_one_and_update` e não "busca depois atualiza": com dois processos de
    backend no ar (ou um restart em cima do outro), a janela entre ler e
    marcar é o suficiente para o mesmo contato receber a campanha duas vezes.
    Aqui o Mongo garante que só um dos dois consegue mudar o documento.
    """
    return await db.campaign_recipients.find_one_and_update(
        {"campaign_id": campaign_id, "status": "pendente"},
        {"$set": {"status": "enviando", "claimed_at": _now()}},
        sort=[("_id", 1)],
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )


async def _credencial_da_conexao(db, campaign: dict):
    """Credencial de envio da conexão da campanha, ou o motivo de não enviar.

    Conexão sem credencial válida pausa a campanha em vez de queimar
    destinatários como falha: o público é o ativo da campanha, e marcar 1.800
    contatos como "falha" porque o token expirou tornaria a campanha
    inaproveitável.
    """
    conn = await db.whatsapp_connections.find_one(
        {"id": campaign.get("whatsapp_connection_id"), "tenant_id": campaign["tenant_id"]},
        {"_id": 0},
    )
    if not conn:
        return None, None, "Conexão de WhatsApp não existe mais"
    if conn.get("status") != "conectado":
        return None, None, f"Conexão '{conn.get('nome') or conn['id']}' está {conn.get('status')}"
    cred = whatsapp.credencial(conn)
    if not cred:
        return None, None, "Conexão sem credencial da Cloud API cadastrada"
    return cred, conn, None


async def _finalizar(db, campaign_id: str):
    await db.campaigns.update_one(
        {"id": campaign_id, "status": "enviando"},
        {"$set": {"status": "concluida", "concluida_em": _now(), "updated_at": _now(),
                  "motivo_pausa": None}},
    )
    logger.info("Campanha %s concluída", campaign_id)


async def _run_campaign(campaign_id: str):
    """Envia uma campanha até acabar, pausar ou ser cancelada."""
    db = get_db()
    await _reclaim_stale(db, campaign_id)

    while True:
        campaign = await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})
        if not campaign:
            return
        if campaign.get("status") != "enviando":
            # Pausada/cancelada pela tela no meio do disparo. O destinatário
            # já em posse deste ciclo não fica preso: o claim seguinte é que
            # não acontece.
            return

        cred, conn, motivo = await _credencial_da_conexao(db, campaign)
        if not cred:
            await _pausar(db, campaign_id, motivo)
            return

        # Número novo no canal não oficial: o limite de 24h do aquecimento
        # segura a campanha **sem pausá-la**. Pausar exigiria alguém voltar à
        # tela todo dia para retomar; esperando, ela continua sozinha quando a
        # janela libera, e o motivo fica na campanha para a tela mostrar.
        espera = await aquecimento.motivo_para_esperar(db, conn)
        if espera:
            if campaign.get("aguardando_aquecimento") != espera:
                await db.campaigns.update_one(
                    {"id": campaign_id},
                    {"$set": {"aguardando_aquecimento": espera, "updated_at": _now()}})
            await _dormir(ESPERA_AQUECIMENTO)
            continue
        if campaign.get("aguardando_aquecimento"):
            await db.campaigns.update_one(
                {"id": campaign_id}, {"$set": {"aguardando_aquecimento": None}})

        recipient = await _claim(db, campaign_id)
        if not recipient:
            await _finalizar(db, campaign_id)
            return

        status, erro = await campaigns.send_one(db, campaign, recipient, cred)
        await db.campaign_recipients.update_one(
            {"id": recipient["id"]},
            {"$set": {"status": status, "erro": erro, "sent_at": _now(), "claimed_at": None}},
        )
        campo = {"enviado": "enviados", "falha": "falhas", "ignorado": "ignorados"}[status]
        await db.campaigns.update_one(
            {"id": campaign_id},
            {"$inc": {f"totais.{campo}": 1}, "$set": {"updated_at": _now()}},
        )

        await _dormir(_intervalo(campaign) * random.uniform(*JITTER))


async def _promover_agendadas(db):
    agora = _now()
    cursor = db.campaigns.find(
        {"status": "agendada", "agendada_para": {"$ne": None, "$lte": agora}},
        {"_id": 0, "id": 1, "nome": 1},
    )
    async for c in cursor:
        await db.campaigns.update_one(
            {"id": c["id"], "status": "agendada"},
            {"$set": {"status": "enviando", "iniciada_em": agora, "updated_at": agora}},
        )
        logger.info("Campanha agendada %s (%s) entrou em disparo", c["id"], c.get("nome"))


async def _garantir_runners(db):
    for morto in [cid for cid, t in _runners.items() if t.done()]:
        _runners.pop(morto, None)
    cursor = db.campaigns.find({"status": "enviando"}, {"_id": 0, "id": 1})
    async for c in cursor:
        if c["id"] not in _runners:
            _runners[c["id"]] = asyncio.create_task(_run_campaign(c["id"]))


async def _sweep():
    db = get_db()
    await _promover_agendadas(db)
    await _garantir_runners(db)


async def _loop():
    logger.info("Campaign runner started (tick=%ds)", TICK)
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        try:
            await _sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Varredura de campanhas falhou: %s", e)
        await asyncio.sleep(TICK)


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None
    for t in _runners.values():
        if not t.done():
            t.cancel()
    _runners.clear()
