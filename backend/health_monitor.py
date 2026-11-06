"""Vigia das conexões de WhatsApp, no mesmo padrão start/stop dos outros workers.

O que este monitor vigia mudou por completo com a Cloud API oficial. Antes ele
existia para completar o pareamento: havia um QR na tela e uma sessão que podia
cair sozinha, então ele varria de cinco em cinco segundos perguntando à WuzAPI
se o aparelho já tinha escaneado, e de trinta em trinta se a sessão continuava
de pé. Sessão não existe mais: um número da Cloud API está registrado na conta
da Meta e não "cai".

Sobraram duas formas de uma conexão morrer em silêncio, e são as duas que este
laço procura:

  - **O token deixou de valer.** Foi revogado, expirou (token de usuário de
    sistema pode ter validade), ou perdeu permissão quando alguém mexeu no
    Business Manager do cliente. O sintoma é toda mensagem falhando com 190 ou
    0, e sem esta varredura o cliente descobre pelo contato que não foi
    respondido.

  - **A qualidade do número caiu.** A Meta rebaixa a nota (GREEN, YELLOW, RED)
    quando muitos contatos bloqueiam ou denunciam, e nota baixa reduz o limite
    diário de conversas iniciadas pela empresa até suspender o número. É o
    número do cliente, e é ele quem precisa saber a tempo de mudar o conteúdo
    dos disparos.

Por isso o intervalo é de quinze minutos, e não de cinco segundos: nada disto
muda de um instante para outro, e cada varredura é uma chamada por conexão
cadastrada de toda a base.
"""
import asyncio
import logging
from datetime import datetime, timezone

from db import get_db
import aquecimento
import whatsapp_client as whatsapp

logger = logging.getLogger("zappzen.health")

INTERVALO = 15 * 60

# Vigia da ponte inteira, separado da varredura por conexão. Nasceu da queda de
# 03/11/2026: a WuzAPI foi apagada do servidor e, por três dias e meio, todas
# as conexões do canal continuaram "conectado" na tela, porque `_probe_wuzapi`
# (de propósito) não muda status em falha de rede. A falha de rede de uma
# conexão não diz nada sobre o número; a ponte inteira sem responder diz tudo:
# nada entra e nada sai por nenhum número do canal.
#
# 60s, e não os 15 min da varredura: é uma chamada só para a base inteira, e
# lead que não entra no CRM é venda perdida a cada minuto.
INTERVALO_PONTE = 60
# Falhas seguidas antes de declarar a ponte fora: um reinício da WuzAPI ou do
# túnel leva segundos, e marcar todo mundo desconectado por isso pausaria
# campanhas sem motivo.
FALHAS_PARA_ALERTA = 2

_task: asyncio.Task | None = None
_task_ponte: asyncio.Task | None = None
_ponte = {"falhas": 0, "fora_desde": None, "motivo": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _probe(row: dict):
    db = get_db()
    conn_id = row["id"]
    cred = whatsapp.credencial(row)
    if not cred:
        return

    try:
        perfil = await whatsapp.perfil_numero(cred)
    except whatsapp.WhatsAppError as e:
        if e.codigo in whatsapp.CODIGOS_TOKEN:
            # Credencial morta: a conexão para de servir para tudo, e dizer
            # isso na tela é a diferença entre o cliente cadastrar um token
            # novo hoje e descobrir na semana que vem que ninguém foi atendido.
            logger.warning("Conexão %s com credencial inválida: %s", conn_id, e)
            await db.whatsapp_connections.update_one(
                {"id": conn_id},
                {"$set": {"status": "erro", "ultimo_erro": str(e), "updated_at": _now()}},
            )
        else:
            # Erro passageiro (rede, 5xx da Meta) não derruba o status: uma
            # conexão marcada como quebrada por causa de uma oscilação faria a
            # campanha pausar sozinha.
            logger.warning("Falha ao consultar a conexão %s: %s", conn_id, e)
        return

    await db.whatsapp_connections.update_one(
        {"id": conn_id},
        {"$set": {
            "status": "conectado",
            "ultimo_erro": None,
            "qualidade": perfil.get("quality_rating"),
            "nome_verificado": perfil.get("verified_name"),
            "updated_at": _now(),
        }},
    )


async def _probe_wuzapi(row: dict):
    """O estado da sessão na ponte, gravado na conexão.

    A ponte avisa por webhook quando conecta e desconecta, mas um evento
    perdido (servidor reiniciando, túnel fora) deixava o status errado até o
    evento seguinte, que pode nunca vir. Com o status em "desconectado", tudo
    que envia sozinho para (lembrete, formulário, ligação, campanha).

    Só muda o status quando a ponte respondeu: falha de rede não diz nada
    sobre o número, e marcá-lo desconectado por isso pararia os envios.
    """
    db = get_db()
    cred = whatsapp.credencial(row)
    if not cred:
        return
    from wuzapi_client import connection_state, WuzapiError
    try:
        estado = await connection_state(cred.token)
    except WuzapiError as e:
        logger.warning("Ponte não respondeu pela conexão %s: %s", row["id"], e)
        return
    ligado = bool(estado.get("connected") and estado.get("loggedIn"))
    novo = "conectado" if ligado else "desconectado"
    # Durante o pareamento a sessão ainda não existe, e "desconectado" apagaria
    # o QR da tela de quem está escaneando.
    pareando = row.get("status") == "pareando" and not ligado
    mudanca = {}
    if not pareando and row.get("status") != novo:
        logger.info("Conexão %s: %s -> %s", row["id"], row.get("status"), novo)
        mudanca["status"] = novo
    if ligado and row.get("ultimo_erro"):
        # O aviso da ponte fora (ou da reinstalação) não vale mais para um
        # número que está de pé.
        mudanca["ultimo_erro"] = None
    if mudanca:
        await db.whatsapp_connections.update_one(
            {"id": row["id"]}, {"$set": {**mudanca, "updated_at": _now()}})
    if ligado:
        await aquecimento.marcar_inicio(db, row["id"])


def ponte_fora() -> dict | None:
    """A ponte está fora? `{desde, motivo}` ou None. Lido pela tela."""
    if _ponte["fora_desde"]:
        return {"desde": _ponte["fora_desde"], "motivo": _ponte["motivo"]}
    return None


async def _vigiar_ponte():
    """Uma rodada do vigia da ponte.

    Fora: marca as conexões do canal como desconectadas, com o motivo em
    `ultimo_erro`. É o status que já acende o alerta no painel da empresa e na
    visão geral do super admin, e a tela de WhatsApp mostra o motivo. Status
    desconectado também para os envios automáticos (lembrete, campanha), que
    falhariam de qualquer jeito com a ponte fora.

    De volta: reconsulta cada conexão na hora, em vez de esperar a varredura
    de 15 min. A WuzAPI religa as sessões sozinha ao subir, e é a consulta que
    devolve o "conectado" a quem voltou.
    """
    db = get_db()
    if not await db.whatsapp_connections.find_one({"canal": "wuzapi"}, {"_id": 1}):
        return
    from wuzapi_client import ping
    motivo = await ping()

    if motivo is None:
        _ponte["falhas"] = 0
        if _ponte["fora_desde"]:
            logger.warning("Ponte WuzAPI voltou (estava fora desde %s)", _ponte["fora_desde"])
            _ponte["fora_desde"] = _ponte["motivo"] = None
            async for row in db.whatsapp_connections.find({"canal": "wuzapi"}):
                try:
                    await _probe_wuzapi(row)
                except Exception as e:
                    logger.exception("Probe falhou para a conexão %s: %s", row.get("id"), e)
        return

    _ponte["falhas"] += 1
    if _ponte["falhas"] < FALHAS_PARA_ALERTA or _ponte["fora_desde"]:
        return
    _ponte["fora_desde"] = _now()
    _ponte["motivo"] = motivo
    logger.error("PONTE WUZAPI FORA DO AR (%s): nenhuma conexão do canal recebe ou envia", motivo)
    await db.whatsapp_connections.update_many(
        {"canal": "wuzapi"},
        {"$set": {
            "status": "desconectado",
            "ultimo_erro": ("O servidor que liga o sistema ao WhatsApp não está respondendo "
                            f"({motivo}). Nenhuma mensagem entra nem sai por este número até ele "
                            "voltar. Não apague a conexão: avise o suporte."),
            "updated_at": _now(),
        }},
    )


async def _sweep():
    db = get_db()
    async for row in db.whatsapp_connections.find({"phone_number_id": {"$ne": None}}):
        try:
            await _probe(row)
        except Exception as e:
            logger.exception("Probe falhou para a conexão %s: %s", row.get("id"), e)
    async for row in db.whatsapp_connections.find({"canal": "wuzapi"}):
        try:
            await _probe_wuzapi(row)
        except Exception as e:
            logger.exception("Probe falhou para a conexão %s: %s", row.get("id"), e)


async def _loop():
    logger.info("Vigia de conexões iniciado (a cada %ds)", INTERVALO)
    while True:
        try:
            await _sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Varredura de saúde falhou: %s", e)
        await asyncio.sleep(INTERVALO)


async def _loop_ponte():
    while True:
        try:
            await _vigiar_ponte()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Vigia da ponte falhou: %s", e)
        await asyncio.sleep(INTERVALO_PONTE)


def start():
    global _task, _task_ponte
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
    if _task_ponte is None or _task_ponte.done():
        _task_ponte = asyncio.create_task(_loop_ponte())


def stop():
    global _task, _task_ponte
    for t in (_task, _task_ponte):
        if t and not t.done():
            t.cancel()
    _task = _task_ponte = None
