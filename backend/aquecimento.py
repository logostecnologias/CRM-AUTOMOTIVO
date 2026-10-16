"""Cuidados de número não oficial: aquecimento e espaçamento de envio ativo.

Só vale no canal `wuzapi`. Ali o número é do cliente e o protocolo não é
oficial: o WhatsApp não tem como saber que é um sistema a não ser pelo
comportamento, e os dois comportamentos que mais derrubam número são estes:

  - **Número novo que já começa disparando.** Um número recém-conectado sem
    histórico de conversa que manda centenas de mensagens a quem nunca falou
    com ele é o padrão de spam que o WhatsApp procura. O limite diário de
    campanha cresce com a idade da conexão (`LIMITES`), contado a partir de
    `aquecimento_desde`, gravado na primeira vez em que ela fica conectada.
    Só a campanha é limitada: responder quem escreveu é o uso normal de um
    número, e é justamente o que o aquece.

  - **Envio ativo em rajada.** Quarenta lembretes de agenda saindo no mesmo
    segundo. `espacar` põe um intervalo aleatório entre os envios ativos de
    uma mesma conexão. Só para quem roda em segundo plano (varredura de
    lembretes, ligação, formulário): numa rota HTTP a espera seguraria a tela
    de quem clicou.

Na Cloud API nada disto se aplica: lá o limite é da Meta, que o aplica sozinha.
"""
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

CANAL_WUZAPI = "wuzapi"

# (a partir do dia, mensagens de campanha por 24h). O dia 0 é o da conexão.
# Depois do último degrau não há limite nosso; continua valendo a cadência da
# campanha. Os números são conservadores de propósito: perder alguns dias de
# disparo custa menos que perder o número do cliente.
LIMITES = ((0, 20), (3, 50), (7, 150))
DIAS_AQUECIMENTO = 14

# Intervalo entre envios ativos da mesma conexão, em segundos.
ESPACO = (12.0, 30.0)

_dormir = asyncio.sleep   # trocável no teste, que não pode esperar segundos
_ultimo: dict[str, float] = {}
_travas: dict[str, asyncio.Lock] = {}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _agora().isoformat()


def nao_oficial(conn: dict | None) -> bool:
    return (conn or {}).get("canal") == CANAL_WUZAPI


async def marcar_inicio(db, conn_id: str) -> None:
    """Grava o começo do aquecimento, uma vez só: reconectar o mesmo número
    não recomeça a contagem. Chamado onde a conexão fica conectada."""
    await db.whatsapp_connections.update_one(
        {"id": conn_id, "canal": CANAL_WUZAPI, "aquecimento_desde": None},
        {"$set": {"aquecimento_desde": _now()}},
    )


def situacao(conn: dict | None) -> dict | None:
    """Em que dia do aquecimento a conexão está e quanto pode disparar.

    None quando não há limite: Cloud API, aquecimento terminado, ou conexão que
    nunca ficou conectada (não dispara de qualquer jeito).
    """
    if not nao_oficial(conn) or not conn.get("aquecimento_desde"):
        return None
    try:
        inicio = datetime.fromisoformat(conn["aquecimento_desde"])
    except (TypeError, ValueError):
        return None
    dia = (_agora() - inicio).days
    if dia >= DIAS_AQUECIMENTO:
        return None
    limite = next(n for desde, n in reversed(LIMITES) if dia >= desde)
    return {"dia": dia + 1, "dias": DIAS_AQUECIMENTO, "limite_24h": limite,
            "termina_em": (inicio + timedelta(days=DIAS_AQUECIMENTO)).isoformat()}


async def disparos_24h(db, conn: dict) -> int:
    """Mensagens de campanha que saíram por esta conexão nas últimas 24h.

    Janela corrida, e não "hoje": o corte de dia dependeria de um fuso, e o que
    o WhatsApp observa é volume num intervalo, não o calendário de ninguém.
    """
    ids = [c["id"] async for c in db.campaigns.find(
        {"tenant_id": conn["tenant_id"], "whatsapp_connection_id": conn["id"]},
        {"_id": 0, "id": 1})]
    if not ids:
        return 0
    corte = (_agora() - timedelta(hours=24)).isoformat()
    return await db.campaign_recipients.count_documents({
        "tenant_id": conn["tenant_id"], "campaign_id": {"$in": ids},
        "status": "enviado", "sent_at": {"$gte": corte},
    })


async def motivo_para_esperar(db, conn: dict) -> str | None:
    """Por que a campanha não pode mandar a próxima agora, ou None."""
    s = situacao(conn)
    if not s:
        return None
    feitos = await disparos_24h(db, conn)
    if feitos < s["limite_24h"]:
        return None
    return (f"Número em aquecimento (dia {s['dia']} de {s['dias']}): limite de "
            f"{s['limite_24h']} mensagens de campanha a cada 24h atingido. "
            "O envio continua sozinho quando a janela liberar.")


async def espacar(conn: dict | None) -> None:
    """Espera o intervalo desde o último envio ativo desta conexão.

    A trava por conexão serializa quem chega junto: dois lembretes e um
    formulário ao mesmo tempo saem um depois do outro, com o intervalo entre
    cada um. Conexões diferentes não esperam umas pelas outras.
    """
    if not nao_oficial(conn):
        return
    cid = conn["id"]
    trava = _travas.setdefault(cid, asyncio.Lock())
    async with trava:
        anterior = _ultimo.get(cid)
        if anterior is not None:
            espera = anterior + random.uniform(*ESPACO) - time.monotonic()
            if espera > 0:
                await _dormir(espera)
        _ultimo[cid] = time.monotonic()
