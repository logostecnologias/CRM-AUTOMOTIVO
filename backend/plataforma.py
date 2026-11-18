"""O que o super admin enxerga da plataforma: a saúde de cada empresa e o todo.

O painel anterior eram seis contagens do banco inteiro ("mensagens totais",
"robôs no sistema") sem comparação nem destino, e a lista de empresas mostrava
nome, plano e quantos robôs. Nenhuma das duas respondia o que quem opera a
plataforma pergunta todo dia:

  - **qual cliente está com problema agora?** WhatsApp fora do ar, agente de IA
    com a chave recusada, campanha pausada. O cliente às vezes nem percebeu,
    e é o suporte que liga antes de ele reclamar;
  - **qual cliente parou de usar?** Empresa ativa sem mensagem há uma semana é
    cancelamento anunciado, e cadastro sem WhatsApp é implantação parada;
  - **quem passou do plano?** O excedente continua funcionando (o teto só barra
    criação nova), então só aparece se alguém olhar;
  - **a plataforma está crescendo?** Receita, empresas e volume contra a semana
    anterior.

Tudo sai de agregações agrupadas por `tenant_id`, nunca de uma consulta por
empresa: com duzentas empresas na tela e o banco atrás de túnel SSH, o que
pesa é a ida e volta, não o volume. As janelas de mensagens e conversas filtram
`tenant_id` + data, que é o que os índices `(tenant_id, timestamp)` e
`(tenant_id, created_at)` cobrem.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from plan_limits import LIMITS
from marcas import normaliza_marca

DIAS_SERIE = 14
# Sem mensagem nenhuma por tantos dias, a empresa conta como parada. Uma semana
# porque um cliente de agenda pode passar um fim de semana prolongado em
# silêncio sem que isso queira dizer nada.
DIAS_PARADA = 7
# Empresa recém-criada ainda está sendo implantada: cobrar movimento dela no
# primeiro dia transformaria todo cadastro novo em alerta.
DIAS_IMPLANTACAO = 2
TOP = 5


def _iso(d: datetime) -> str:
    return d.isoformat()


async def _agrupar(cursor) -> dict:
    return {linha["_id"]: linha async for linha in cursor}


async def saude(db, tenants: list[dict]) -> dict[str, dict]:
    """Um resumo por empresa: conexões, movimento, problemas e uso do plano.

    É o que a lista de empresas desenha em cada linha e o que os alertas da
    visão geral juntam. Uma função só para as duas telas, para a linha da
    empresa e o alerta nunca dizerem coisas diferentes.
    """
    ids = [t["id"] for t in tenants]
    if not ids:
        return {}
    agora = datetime.now(timezone.utc)
    d7, d14, d30 = (_iso(agora - timedelta(days=n)) for n in (7, 14, 30))
    em = {"$in": ids}

    (conexoes, mensagens, conversas, contagens_bots, contagens_users,
     agentes, pausadas, admins) = await asyncio.gather(
        _agrupar(db.whatsapp_connections.aggregate([
            {"$match": {"tenant_id": em}},
            {"$group": {
                "_id": "$tenant_id",
                "total": {"$sum": 1},
                "no_ar": {"$sum": {"$cond": [{"$eq": ["$status", "conectado"]}, 1, 0]}},
            }},
        ])),
        # Trinta dias para achar a última mensagem de quem está parado há mais
        # de uma semana; além disso, "sem mensagem há mais de 30 dias" basta.
        _agrupar(db.messages_log.aggregate([
            {"$match": {"tenant_id": em, "timestamp": {"$gte": d30}}},
            {"$group": {
                "_id": "$tenant_id",
                "n7": {"$sum": {"$cond": [{"$gte": ["$timestamp", d7]}, 1, 0]}},
                "n7_ant": {"$sum": {"$cond": [
                    {"$and": [{"$gte": ["$timestamp", d14]}, {"$lt": ["$timestamp", d7]}]}, 1, 0]}},
                "ultima": {"$max": "$timestamp"},
            }},
        ])),
        _agrupar(db.conversation_sessions.aggregate([
            {"$match": {"tenant_id": em, "created_at": {"$gte": d14}}},
            {"$group": {
                "_id": "$tenant_id",
                "c7": {"$sum": {"$cond": [{"$gte": ["$created_at", d7]}, 1, 0]}},
                "c7_ant": {"$sum": {"$cond": [{"$lt": ["$created_at", d7]}, 1, 0]}},
            }},
        ])),
        _agrupar(db.bots.aggregate([
            {"$match": {"tenant_id": em}},
            {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}}},
        ])),
        _agrupar(db.users.aggregate([
            {"$match": {"tenant_id": em}},
            {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}}},
        ])),
        # Mesmo critério do alerta do painel da empresa: agente pausado ou
        # desligado com a chave quebrada não atende ninguém, não é urgência.
        db.ai_agents.find(
            {"tenant_id": em, "credencial_status": "erro", "ativo": {"$ne": False},
             "modo": {"$ne": "desligado"}},
            {"_id": 0, "tenant_id": 1, "nome": 1},
        ).to_list(1000),
        db.campaigns.find(
            {"tenant_id": em, "status": "pausada"},
            {"_id": 0, "tenant_id": 1, "nome": 1, "motivo_pausa": 1},
        ).to_list(1000),
        # O email de quem administra cada empresa é a pergunta mais comum do
        # suporte ("qual é o login da R3?"), e antes só se respondia entrando
        # na empresa e abrindo Usuários.
        db.users.find(
            {"tenant_id": em, "role": "tenant_admin"},
            {"_id": 0, "tenant_id": 1, "email": 1, "name": 1, "created_at": 1},
        ).sort("created_at", 1).to_list(5000),
    )

    def _nomes(docs, tid):
        return [d.get("nome") or "sem nome" for d in docs if d["tenant_id"] == tid]

    contagem = {
        "bots": {k: v["n"] for k, v in contagens_bots.items()},
        "users": {k: v["n"] for k, v in contagens_users.items()},
        "whatsapp_connections": {k: v["total"] for k, v in conexoes.items()},
    }

    implantacao = _iso(agora - timedelta(days=DIAS_IMPLANTACAO))
    saida = {}
    for t in tenants:
        tid = t["id"]
        con = conexoes.get(tid, {})
        msg = mensagens.get(tid, {})
        conv = conversas.get(tid, {})
        plano = t.get("plan") or {}

        # Mesma leitura de `plan_excess`: só os limites de contagem, e 0 ou
        # vazio não conta como teto estourado aqui (o plano sem o campo é
        # ilimitado; o de teto zero já recusa a criação, e o super admin vê
        # isso ao montar o plano).
        acima = []
        for colecao, campo, rotulo in LIMITS:
            teto = plano.get(campo)
            usado = contagem[colecao].get(tid, 0)
            if teto and usado > teto:
                acima.append(f"{usado} {rotulo} (máx. {teto})")

        ativa = t.get("status") == "active"
        nova = (t.get("created_at") or "") >= implantacao
        problemas = []
        if ativa:
            fora = con.get("total", 0) - con.get("no_ar", 0)
            if fora:
                problemas.append({"tipo": "conexoes", "nivel": "alto", "n": fora,
                                  "para": "/app/whatsapp"})
            ag = _nomes(agentes, tid)
            if ag:
                problemas.append({"tipo": "agentes", "nivel": "alto", "n": len(ag),
                                  "nomes": ag, "para": "/app/ai-agents"})
            if not con.get("total") and not nova:
                problemas.append({"tipo": "sem_whatsapp", "nivel": "medio",
                                  "para": "/app/whatsapp"})
            elif con.get("total") and not msg.get("n7") and not nova:
                problemas.append({"tipo": "parada", "nivel": "medio",
                                  "ultima": msg.get("ultima"), "para": "/app"})
            camp = [c for c in pausadas if c["tenant_id"] == tid]
            if camp:
                problemas.append({"tipo": "campanhas", "nivel": "medio", "n": len(camp),
                                  "nomes": _nomes(camp, tid),
                                  "motivo": camp[0].get("motivo_pausa"),
                                  "para": "/app/campanhas"})
            if acima:
                problemas.append({"tipo": "acima_plano", "nivel": "baixo",
                                  "detalhe": acima, "para": None})
            if not t.get("plan_id"):
                problemas.append({"tipo": "sem_plano", "nivel": "baixo", "para": None})

        saida[tid] = {
            "admins": [{"email": u.get("email"), "name": u.get("name")}
                       for u in admins if u["tenant_id"] == tid],
            "conexoes": {"total": con.get("total", 0), "no_ar": con.get("no_ar", 0)},
            "mensagens_7d": msg.get("n7", 0),
            "mensagens_7d_anterior": msg.get("n7_ant", 0),
            "conversas_7d": conv.get("c7", 0),
            "conversas_7d_anterior": conv.get("c7_ant", 0),
            "ultima_mensagem": msg.get("ultima"),
            "bots": contagem["bots"].get(tid, 0),
            "usuarios": contagem["users"].get(tid, 0),
            "acima_do_plano": acima,
            "problemas": problemas,
        }
    return saida


async def serie(db, ids: list[str]) -> list[dict]:
    """Conversas novas por dia em 14 dias, separando o que um atendente pegou
    do que o robô ou o agente resolveram sozinhos. O mesmo corte do painel da
    empresa, somado sobre todas: é o trabalho que a automação faz na
    plataforma inteira. O dia é o prefixo do ISO, como nos relatórios."""
    agora = datetime.now(timezone.utc)
    hoje = agora.date()
    de = (agora - timedelta(days=DIAS_SERIE - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0).isoformat()

    por_dia = {}
    for n in range(DIAS_SERIE - 1, -1, -1):
        d = (hoje - timedelta(days=n)).isoformat()
        por_dia[d] = {"dia": d, "automatico": 0, "humano": 0}
    if not ids:
        return list(por_dia.values())

    cursor = db.conversation_sessions.aggregate([
        {"$match": {"tenant_id": {"$in": ids}, "created_at": {"$gte": de}}},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 10]},
            "total": {"$sum": 1},
            # Contra "" e não contra null: na ordem do BSON, null e campo
            # ausente ficam abaixo de qualquer texto, então só a conversa com
            # `assumido_em` preenchido passa. Contra null, o campo ausente
            # depende de como cada versão compara "missing" com null.
            "humano": {"$sum": {"$cond": [{"$gt": ["$assumido_em", ""]}, 1, 0]}},
        }},
    ])
    async for linha in cursor:
        dia = por_dia.get(linha["_id"])
        if dia:
            dia["humano"] = linha["humano"]
            dia["automatico"] = linha["total"] - linha["humano"]
    return list(por_dia.values())


def visao(tenants: list[dict], saude_por_id: dict, serie_dias: list[dict]) -> dict:
    """A visão geral, montada do que `saude` já calculou: nenhuma consulta a
    mais, e o alerta da visão geral é exatamente o problema da linha da
    empresa na lista."""
    agora = datetime.now(timezone.utc)
    inicio_mes = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    ativas = [t for t in tenants if t.get("status") == "active"]

    # Receita recorrente: o preço do plano de cada empresa ativa. Empresa
    # suspensa não paga, e empresa sem plano não entra (aparece como alerta).
    receita = 0.0
    por_marca = {}
    for t in ativas:
        preco = float((t.get("plan") or {}).get("preco_mensal") or 0)
        receita += preco
        m = normaliza_marca(t.get("marca"))
        linha = por_marca.setdefault(m, {"marca": m, "empresas": 0, "receita": 0.0})
        linha["empresas"] += 1
        linha["receita"] += preco

    # Um alerta por tipo, com a lista de empresas: "3 empresas com WhatsApp
    # fora do ar" e o nome de cada uma, cada uma com o próprio botão de entrar.
    alertas = {}
    for t in tenants:
        for p in saude_por_id.get(t["id"], {}).get("problemas", []):
            a = alertas.setdefault(p["tipo"], {"tipo": p["tipo"], "nivel": p["nivel"],
                                               "empresas": []})
            a["empresas"].append({"id": t["id"], "name": t["name"], "para": p.get("para"),
                                  **{k: p[k] for k in ("n", "nomes", "motivo", "ultima", "detalhe")
                                     if k in p}})
    ordem = {"alto": 0, "medio": 1, "baixo": 2}
    lista_alertas = sorted(alertas.values(),
                           key=lambda a: (ordem[a["nivel"]], -len(a["empresas"])))

    def _soma(campo):
        return sum(saude_por_id.get(t["id"], {}).get(campo, 0) for t in tenants)

    com_movimento = sum(1 for t in ativas if saude_por_id.get(t["id"], {}).get("mensagens_7d"))
    com_movimento_ant = sum(1 for t in ativas
                            if saude_por_id.get(t["id"], {}).get("mensagens_7d_anterior"))

    top = sorted(
        (t for t in ativas if saude_por_id.get(t["id"], {}).get("mensagens_7d")),
        key=lambda t: -saude_por_id[t["id"]]["mensagens_7d"],
    )[:TOP]

    return {
        "empresas": {
            "total": len(tenants),
            "ativas": len(ativas),
            "suspensas": len(tenants) - len(ativas),
            "novas_mes": sum(1 for t in tenants if (t.get("created_at") or "") >= inicio_mes),
            "com_movimento_7d": com_movimento,
            "com_movimento_7d_anterior": com_movimento_ant,
        },
        "receita": {
            "mensal": receita,
            "por_marca": sorted(por_marca.values(), key=lambda m: -m["receita"]),
        },
        "semana": {
            "mensagens": _soma("mensagens_7d"),
            "mensagens_anterior": _soma("mensagens_7d_anterior"),
            "conversas": _soma("conversas_7d"),
            "conversas_anterior": _soma("conversas_7d_anterior"),
        },
        "serie": serie_dias,
        "alertas": lista_alertas,
        "top": [{"id": t["id"], "name": t["name"], "marca": normaliza_marca(t.get("marca")),
                 "mensagens_7d": saude_por_id[t["id"]]["mensagens_7d"],
                 "mensagens_7d_anterior": saude_por_id[t["id"]]["mensagens_7d_anterior"]}
                for t in top],
        "gerado_em": agora.isoformat(),
    }
