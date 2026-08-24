"""Relatórios de atendimento e de campanhas.

O funil já tinha os dele (`deals.metricas`). Aqui ficam os dois que faltavam: o
que a operação de atendimento produz e o que as campanhas devolvem.

Duas escolhas estruturais valem explicação:

  - **Os tempos são calculados na leitura, não gravados.** `espera` é
    `assumido_em - aguardando_desde` e `atendimento` é `finalizado_em -
    assumido_em`, e o `$avg` do Mongo não subtrai duas datas guardadas como
    string ISO. No funil isso foi resolvido gravando `ciclo_dias` no
    fechamento, mas ali o campo nasceu junto com a coleção; aqui existem
    conversas antigas, e um campo novo exigiria migrar a base inteira para
    produzir um número que só é lido quando alguém abre um relatório. Então a
    conta é feita em Python sobre as conversas da janela, com projeção de
    quatro campos.

  - **A série por dia usa `$substr` no ISO.** `"2026-08-24T18:30:00+00:00"[:10]`
    é `"2026-08-24"`, e agrupar por esse prefixo dá o dia sem converter data
    nenhuma. É o único lugar em que o formato ISO em texto vira uma vantagem.

Nada é truncado em silêncio: acima de `MAX_SESSOES` na janela o relatório
recusa e diz para encurtar o período, em vez de responder com meia conta.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("zappzen.relatorios")

# Teto de conversas por janela. Os tempos são calculados em Python, então o
# custo é linear no número de conversas — e é melhor pedir um período menor do
# que devolver um número que ninguém sabe que está incompleto.
MAX_SESSOES = 50000

# Lote do `$in` de mensagens quando há filtro de conexão/departamento.
LOTE_IDS = 1000

STATUS_KANBAN = ("bot", "aguardando", "em_atendimento", "finalizado")


def _now():
    return datetime.now(timezone.utc).isoformat()


class RelatorioError(Exception):
    pass


def _segundos(inicio: str | None, fim: str | None) -> float | None:
    if not inicio or not fim:
        return None
    try:
        d = (datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)).total_seconds()
    except ValueError:
        return None
    # Negativo significa dado inconsistente (relógio, ou campo preenchido fora
    # de ordem). Entra como ausente em vez de puxar a média para baixo.
    return d if d >= 0 else None


def _percentil(valores: list[float], p: float) -> float | None:
    """p90 junto com a média porque média sozinha esconde a cauda: uma fila com
    média de 4 minutos e p90 de 40 é uma operação com problema que a média
    não mostra."""
    if not valores:
        return None
    ordenados = sorted(valores)
    i = min(len(ordenados) - 1, int(round((len(ordenados) - 1) * p)))
    return ordenados[i]


def _media(valores: list[float]) -> float | None:
    return sum(valores) / len(valores) if valores else None


async def atendimento(db, tenant_id: str, de: str, ate: str,
                      connection_ids: list[str] | None = None,
                      departamento_id: str | None = None) -> dict:
    """Volume, tempos e produtividade do atendimento na janela."""
    filtro: dict = {"tenant_id": tenant_id, "created_at": {"$gte": de, "$lte": ate}}
    if connection_ids is not None:
        filtro["whatsapp_connection_id"] = {"$in": connection_ids}
    if departamento_id:
        filtro["departamento_id"] = departamento_id

    quantas = await db.conversation_sessions.count_documents(filtro)
    if quantas > MAX_SESSOES:
        raise RelatorioError(
            f"O período tem {quantas} conversas, acima do limite de {MAX_SESSOES} por "
            "relatório. Escolha um intervalo menor."
        )

    sessoes = await db.conversation_sessions.find(
        filtro,
        {"_id": 0, "id": 1, "created_at": 1, "aguardando_desde": 1, "assumido_em": 1,
         "finalizado_em": 1, "atendente_id": 1, "departamento_id": 1,
         "whatsapp_connection_id": 1, "status_atendimento": 1, "origem": 1},
    ).to_list(MAX_SESSOES)

    esperas: list[float] = []
    atendimentos: list[float] = []
    por_dia: dict[str, dict] = {}
    por_atendente: dict[str, dict] = {}
    por_departamento: dict[str, int] = {}
    por_conexao: dict[str, int] = {}
    por_status = {s: 0 for s in STATUS_KANBAN}
    finalizadas = 0
    de_campanha = 0

    for s in sessoes:
        dia = (s.get("created_at") or "")[:10]
        alvo = por_dia.setdefault(dia, {"dia": dia, "conversas": 0, "recebidas": 0, "enviadas": 0})
        alvo["conversas"] += 1

        espera = _segundos(s.get("aguardando_desde"), s.get("assumido_em"))
        if espera is not None:
            esperas.append(espera)
        duracao = _segundos(s.get("assumido_em"), s.get("finalizado_em"))
        if duracao is not None:
            atendimentos.append(duracao)

        if s.get("finalizado_em"):
            finalizadas += 1
        if s.get("origem") == "campanha":
            de_campanha += 1
        estado = s.get("status_atendimento")
        if estado in por_status:
            por_status[estado] += 1

        if s.get("atendente_id"):
            a = por_atendente.setdefault(
                s["atendente_id"],
                {"atendente_id": s["atendente_id"], "assumidas": 0, "finalizadas": 0,
                 "_duracoes": []},
            )
            a["assumidas"] += 1
            if s.get("finalizado_em"):
                a["finalizadas"] += 1
            if duracao is not None:
                a["_duracoes"].append(duracao)
        if s.get("departamento_id"):
            por_departamento[s["departamento_id"]] = por_departamento.get(s["departamento_id"], 0) + 1
        if s.get("whatsapp_connection_id"):
            cid = s["whatsapp_connection_id"]
            por_conexao[cid] = por_conexao.get(cid, 0) + 1

    # Mensagens. Sem filtro, direto por tenant (o índice cobre); com filtro, só
    # das conversas que entraram no recorte — senão o gráfico mostraria o volume
    # da empresa inteira ao lado de números de uma conexão só.
    filtrando = connection_ids is not None or bool(departamento_id)
    recebidas = enviadas = 0
    if filtrando:
        ids = [s["id"] for s in sessoes]
        for i in range(0, len(ids), LOTE_IDS):
            r, e = await _conta_mensagens(db, tenant_id, de, ate, por_dia,
                                          ids[i:i + LOTE_IDS])
            recebidas += r
            enviadas += e
    else:
        recebidas, enviadas = await _conta_mensagens(db, tenant_id, de, ate, por_dia, None)

    for a in por_atendente.values():
        duracoes = a.pop("_duracoes")
        a["atendimento_medio_s"] = _media(duracoes)

    nomes = {
        u["id"]: (u.get("name") or u.get("email"))
        async for u in db.users.find(
            {"id": {"$in": list(por_atendente)}}, {"_id": 0, "id": 1, "name": 1, "email": 1}
        )
    } if por_atendente else {}
    for uid, a in por_atendente.items():
        a["nome"] = nomes.get(uid) or "(usuário removido)"

    deps = {
        d["id"]: d
        async for d in db.departments.find(
            {"id": {"$in": list(por_departamento)}, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "nome": 1, "cor": 1},
        )
    } if por_departamento else {}
    conns = {
        c["id"]: c
        async for c in db.whatsapp_connections.find(
            {"id": {"$in": list(por_conexao)}, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "nome": 1},
        )
    } if por_conexao else {}

    return {
        "periodo": {"de": de, "ate": ate},
        "resumo": {
            "conversas": len(sessoes),
            "finalizadas": finalizadas,
            "em_aberto": len(sessoes) - finalizadas,
            "de_campanha": de_campanha,
            "mensagens_recebidas": recebidas,
            "mensagens_enviadas": enviadas,
        },
        "tempos": {
            "espera_media_s": _media(esperas),
            "espera_p90_s": _percentil(esperas, 0.9),
            "espera_amostra": len(esperas),
            "atendimento_medio_s": _media(atendimentos),
            "atendimento_p90_s": _percentil(atendimentos, 0.9),
            "atendimento_amostra": len(atendimentos),
        },
        "por_status": por_status,
        "por_dia": sorted(por_dia.values(), key=lambda x: x["dia"]),
        "por_atendente": sorted(por_atendente.values(),
                                key=lambda x: x["assumidas"], reverse=True),
        "por_departamento": sorted(
            [{"id": k, "nome": deps.get(k, {}).get("nome", "(excluído)"),
              "cor": deps.get(k, {}).get("cor"), "conversas": v}
             for k, v in por_departamento.items()],
            key=lambda x: x["conversas"], reverse=True),
        "por_conexao": sorted(
            [{"id": k, "nome": conns.get(k, {}).get("nome", "(excluída)"), "conversas": v}
             for k, v in por_conexao.items()],
            key=lambda x: x["conversas"], reverse=True),
    }


async def _conta_mensagens(db, tenant_id: str, de: str, ate: str,
                           por_dia: dict, session_ids: list[str] | None) -> tuple[int, int]:
    """Soma as mensagens por dia e por direção, alimentando `por_dia`."""
    match: dict = {"tenant_id": tenant_id, "timestamp": {"$gte": de, "$lte": ate}}
    if session_ids is not None:
        match["session_id"] = {"$in": session_ids}
    recebidas = enviadas = 0
    cursor = db.messages_log.aggregate([
        {"$match": match},
        # O dia sai do prefixo do próprio ISO: agrupar por `$substr` evita
        # converter data e mantém a consulta dentro do índice de `timestamp`.
        {"$group": {"_id": {"dia": {"$substr": ["$timestamp", 0, 10]},
                            "direcao": "$direction"},
                    "n": {"$sum": 1}}},
    ])
    async for row in cursor:
        dia = row["_id"]["dia"]
        direcao = row["_id"]["direcao"]
        alvo = por_dia.setdefault(dia, {"dia": dia, "conversas": 0, "recebidas": 0, "enviadas": 0})
        if direcao == "recebida":
            alvo["recebidas"] += row["n"]
            recebidas += row["n"]
        elif direcao == "enviada":
            alvo["enviadas"] += row["n"]
            enviadas += row["n"]
    return recebidas, enviadas


async def campanhas(db, tenant_id: str, de: str, ate: str) -> dict:
    """Consolidado das campanhas: o que saiu, o que voltou e o que virou negócio.

    A junção com `deals` é o que fecha a conta que a agência cobra — taxa de
    resposta é meio caminho; receita fechada é o argumento.
    """
    por_campanha: dict[str, dict] = {}

    cursor = db.campaign_recipients.aggregate([
        {"$match": {"tenant_id": tenant_id, "sent_at": {"$gte": de, "$lte": ate}}},
        {"$group": {"_id": {"campanha": "$campaign_id", "status": "$status"},
                    "n": {"$sum": 1},
                    "respostas": {"$sum": {"$cond": ["$respondeu", 1, 0]}}}},
    ])
    async for row in cursor:
        cid = row["_id"]["campanha"]
        alvo = por_campanha.setdefault(cid, {
            "campanha_id": cid, "enviados": 0, "falhas": 0, "ignorados": 0,
            "respostas": 0, "negocios": 0, "valor": 0.0,
        })
        chave = {"enviado": "enviados", "falha": "falhas", "ignorado": "ignorados"}.get(
            row["_id"]["status"])
        if chave:
            alvo[chave] += row["n"]
        alvo["respostas"] += row.get("respostas", 0)

    cursor = db.deals.aggregate([
        {"$match": {"tenant_id": tenant_id, "status": "ganho",
                    "campanha_id": {"$ne": None},
                    "fechado_em": {"$gte": de, "$lte": ate}}},
        {"$group": {"_id": "$campanha_id", "n": {"$sum": 1}, "valor": {"$sum": "$valor"}}},
    ])
    async for row in cursor:
        # Campanha que fechou negócio nesta janela mas disparou antes precisa
        # aparecer: senão a receita ficaria sem dono no relatório.
        alvo = por_campanha.setdefault(row["_id"], {
            "campanha_id": row["_id"], "enviados": 0, "falhas": 0, "ignorados": 0,
            "respostas": 0, "negocios": 0, "valor": 0.0,
        })
        alvo["negocios"] = row["n"]
        alvo["valor"] = row.get("valor") or 0

    nomes = {
        c["id"]: c.get("nome")
        async for c in db.campaigns.find(
            {"id": {"$in": list(por_campanha)}, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "nome": 1},
        )
    } if por_campanha else {}

    itens = []
    for cid, dados in por_campanha.items():
        dados["nome"] = nomes.get(cid) or "(excluída)"
        dados["taxa_resposta"] = (round(dados["respostas"] / dados["enviados"] * 100, 1)
                                  if dados["enviados"] else None)
        itens.append(dados)
    itens.sort(key=lambda x: (x["valor"], x["enviados"]), reverse=True)

    return {
        "periodo": {"de": de, "ate": ate},
        "resumo": {
            "campanhas": len(itens),
            "enviados": sum(i["enviados"] for i in itens),
            "falhas": sum(i["falhas"] for i in itens),
            "respostas": sum(i["respostas"] for i in itens),
            "negocios": sum(i["negocios"] for i in itens),
            "valor": sum(i["valor"] for i in itens),
        },
        "itens": itens,
    }
