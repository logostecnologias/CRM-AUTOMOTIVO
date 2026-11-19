"""O que o super admin enxerga da plataforma: a saúde de cada empresa e o todo.

Responde o que quem opera a plataforma pergunta todo dia:

  - **qual cliente está com problema agora?** WhatsApp fora do ar, agente de IA
    com a chave recusada ou parado no teto de IA, campanha pausada. O cliente
    às vezes nem percebeu, e é o suporte que liga antes de ele reclamar;
  - **qual cliente parou de usar?** Empresa ativa sem mensagem há uma semana, ou
    cuja equipe não entra há dias, é cancelamento anunciado; cadastro sem
    WhatsApp é implantação parada;
  - **o sistema está gerando resultado para o cliente?** Leads que entraram e
    negócios ganhos: é o que a revenda compra;
  - **quanto a IA está custando para nós?** Só o consumo pago pela chave da
    plataforma, contra o teto de cada empresa;
  - **o que mudou?** As últimas ações registradas (auditoria e modo suporte).

Os planos saíram em 18/11/2026: não há mais preço, receita nem limite de
robôs/conexões/usuários. O único teto que sobrou é o de IA, como campo da
empresa (`limite_tokens_ia_mes`), porque é custo nosso.

Tudo sai de agregações agrupadas por `tenant_id`, nunca de uma consulta por
empresa: com duzentas empresas na tela e o banco atrás de túnel SSH, o que
pesa é a ida e volta, não o volume. As janelas filtram `tenant_id` + data, que
é o que os índices `(tenant_id, timestamp)` / `(tenant_id, created_at)` cobrem.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from marcas import normaliza_marca

DIAS_SERIE = 14
# Sem mensagem nenhuma por tantos dias, a empresa conta como parada. Uma semana
# porque um cliente pode passar um fim de semana prolongado em silêncio sem
# que isso queira dizer nada.
DIAS_PARADA = 7
# Empresa recém-criada ainda está sendo implantada: cobrar movimento dela no
# primeiro dia transformaria todo cadastro novo em alerta.
DIAS_IMPLANTACAO = 2
# A partir daqui o consumo de IA vira aviso: ainda dá tempo de conversar com o
# cliente antes de o agente parar.
IA_AVISO = 0.8
TOP = 5
TOP_IA = 8
ATIVIDADE = 20


def _iso(d: datetime) -> str:
    return d.isoformat()


def _mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _agrupar(cursor) -> dict:
    return {linha["_id"]: linha async for linha in cursor}


async def saude(db, tenants: list[dict]) -> dict[str, dict]:
    """Um resumo por empresa: conexões, movimento, resultado, IA e problemas.

    É o que a lista de empresas desenha em cada linha, o que a ficha mostra no
    topo e o que os alertas da visão geral juntam. Uma função só para as três
    telas, para a linha da empresa e o alerta nunca dizerem coisas diferentes.
    """
    ids = [t["id"] for t in tenants]
    if not ids:
        return {}
    agora = datetime.now(timezone.utc)
    d7, d14, d30 = (_iso(agora - timedelta(days=n)) for n in (7, 14, 30))
    em = {"$in": ids}

    (conexoes, mensagens, conversas, contagens_bots, equipe, leads, vendas, ia,
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
        # Tamanho da equipe e quando alguém dela entrou pela última vez.
        _agrupar(db.users.aggregate([
            {"$match": {"tenant_id": em}},
            {"$group": {
                "_id": "$tenant_id",
                "n": {"$sum": 1},
                "atendentes": {"$sum": {"$cond": [{"$eq": ["$role", "agent"]}, 1, 0]}},
                "ultimo_acesso": {"$max": "$ultimo_acesso"},
            }},
        ])),
        # Leads: contato novo na base, venha do WhatsApp, do formulário do
        # site ou da importação. É o primeiro número que o cliente olha.
        _agrupar(db.contacts.aggregate([
            {"$match": {"tenant_id": em, "created_at": {"$gte": d14}}},
            {"$group": {
                "_id": "$tenant_id",
                "n7": {"$sum": {"$cond": [{"$gte": ["$created_at", d7]}, 1, 0]}},
                "n7_ant": {"$sum": {"$cond": [{"$lt": ["$created_at", d7]}, 1, 0]}},
            }},
        ])),
        # Vendas: negócio ganho no funil nos últimos 30 dias.
        _agrupar(db.deals.aggregate([
            {"$match": {"tenant_id": em, "status": "ganho", "fechado_em": {"$gte": d30}}},
            {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}, "valor": {"$sum": "$valor"}}},
        ])),
        # IA no mês. `tokens_plataforma` é o que o teto da empresa conta
        # (`ai_runtime._checar_cota` lê o mesmo recorte por origem).
        _agrupar(db.ai_usage.aggregate([
            {"$match": {"tenant_id": em, "mes": _mes_atual()}},
            {"$group": {
                "_id": "$tenant_id",
                "tokens": {"$sum": "$tokens"},
                "tokens_plataforma": {"$sum": {"$cond": [
                    {"$eq": ["$origem", "plataforma"]}, "$tokens", 0]}},
                "custo_plataforma": {"$sum": {"$cond": [
                    {"$eq": ["$origem", "plataforma"]}, "$custo_usd", 0]}},
            }},
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
        # suporte ("qual é o login da R3?").
        db.users.find(
            {"tenant_id": em, "role": "tenant_admin"},
            {"_id": 0, "tenant_id": 1, "email": 1, "name": 1, "created_at": 1},
        ).sort("created_at", 1).to_list(5000),
    )

    def _nomes(docs, tid):
        return [d.get("nome") or "sem nome" for d in docs if d["tenant_id"] == tid]

    implantacao = _iso(agora - timedelta(days=DIAS_IMPLANTACAO))
    saida = {}
    for t in tenants:
        tid = t["id"]
        con = conexoes.get(tid, {})
        msg = mensagens.get(tid, {})
        conv = conversas.get(tid, {})
        eq = equipe.get(tid, {})
        ld = leads.get(tid, {})
        vd = vendas.get(tid, {})
        uso_ia = ia.get(tid, {})

        teto = t.get("limite_tokens_ia_mes") or None
        tokens_plat = uso_ia.get("tokens_plataforma", 0)
        pct_ia = round(tokens_plat / teto * 100) if teto else None

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
            if teto and tokens_plat >= teto:
                problemas.append({"tipo": "ia_no_teto", "nivel": "alto",
                                  "detalhe": [f"{tokens_plat:,} de {teto:,} tokens".replace(",", ".")],
                                  "para": None})
            elif teto and tokens_plat >= teto * IA_AVISO:
                problemas.append({"tipo": "ia_perto_teto", "nivel": "medio", "pct": pct_ia,
                                  "para": None})
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

        saida[tid] = {
            "admins": [{"email": u.get("email"), "name": u.get("name")}
                       for u in admins if u["tenant_id"] == tid],
            "conexoes": {"total": con.get("total", 0), "no_ar": con.get("no_ar", 0)},
            "mensagens_7d": msg.get("n7", 0),
            "mensagens_7d_anterior": msg.get("n7_ant", 0),
            "conversas_7d": conv.get("c7", 0),
            "conversas_7d_anterior": conv.get("c7_ant", 0),
            "leads_7d": ld.get("n7", 0),
            "leads_7d_anterior": ld.get("n7_ant", 0),
            "vendas_30d": vd.get("n", 0),
            "vendas_30d_valor": float(vd.get("valor") or 0),
            "ultima_mensagem": msg.get("ultima"),
            "ultimo_acesso": eq.get("ultimo_acesso"),
            "bots": contagens_bots.get(tid, {}).get("n", 0),
            "usuarios": eq.get("n", 0),
            "atendentes": eq.get("atendentes", 0),
            "ia": {
                "tokens": uso_ia.get("tokens", 0),
                "tokens_plataforma": tokens_plat,
                "custo_usd": round(uso_ia.get("custo_plataforma", 0.0), 4),
                "teto": teto,
                "pct": pct_ia,
            },
            "problemas": problemas,
        }
    return _ordenar_problemas(saida)


def _ordenar_problemas(saida: dict) -> dict:
    """Problemas mais graves primeiro, na linha e na ficha."""
    ordem = {"alto": 0, "medio": 1, "baixo": 2}
    for s in saida.values():
        s["problemas"].sort(key=lambda p: ordem[p["nivel"]])
    return saida


async def serie(db, ids: list[str]) -> list[dict]:
    """Conversas novas por dia em 14 dias, separando o que um atendente pegou
    do que o robô ou o agente resolveram sozinhos. O mesmo corte do painel da
    empresa, somado sobre as empresas pedidas. O dia é o prefixo do ISO, como
    nos relatórios."""
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
            # `assumido_em` preenchido passa.
            "humano": {"$sum": {"$cond": [{"$gt": ["$assumido_em", ""]}, 1, 0]}},
        }},
    ])
    async for linha in cursor:
        dia = por_dia.get(linha["_id"])
        if dia:
            dia["humano"] = linha["humano"]
            dia["automatico"] = linha["total"] - linha["humano"]
    return list(por_dia.values())


async def atividade(db, nomes: dict[str, str], tenant_id: str | None = None,
                    limite: int = ATIVIDADE) -> list[dict]:
    """As últimas ações registradas: a auditoria (suspender, excluir, exportar
    contatos, trocar senha...) e as entradas em modo suporte, numa linha do
    tempo só. Com `tenant_id`, só as daquela empresa (a aba da ficha)."""
    filtro = {"tenant_id": tenant_id} if tenant_id else {}
    auditoria, suporte = await asyncio.gather(
        db.audit_log.find(filtro, {"_id": 0}).sort("em", -1).to_list(limite),
        db.impersonation_log.find(filtro, {"_id": 0}).sort("iniciado_em", -1).to_list(limite),
    )
    # Quem entrou em modo suporte é um super admin: o log guarda só o id.
    ids_sa = list({s.get("super_admin_id") for s in suporte if s.get("super_admin_id")})
    emails = {u["id"]: u.get("email") async for u in db.users.find(
        {"id": {"$in": ids_sa}}, {"_id": 0, "id": 1, "email": 1})} if ids_sa else {}

    linhas = [{
        "tipo": "auditoria",
        "acao": a.get("acao"),
        "em": a.get("em"),
        "ator": a.get("ator_email"),
        "suporte": bool(a.get("impersonation_id")),
        "tenant_id": a.get("tenant_id"),
        # Empresa excluída já não está em `nomes`: a auditoria guardou o nome.
        "empresa": nomes.get(a.get("tenant_id")) or (
            a.get("alvo") if a.get("acao") == "tenant.delete" else None),
        "meta": a.get("meta") or {},
    } for a in auditoria]
    linhas += [{
        "tipo": "suporte",
        "acao": "suporte.entrar",
        "em": s.get("iniciado_em"),
        "fim": s.get("finalizado_em"),
        "ator": emails.get(s.get("super_admin_id")),
        "suporte": True,
        "tenant_id": s.get("tenant_id"),
        "empresa": nomes.get(s.get("tenant_id")),
        "meta": {},
    } for s in suporte]
    linhas.sort(key=lambda l: l.get("em") or "", reverse=True)
    return linhas[:limite]


def visao(tenants: list[dict], saude_por_id: dict, serie_dias: list[dict],
          linha_do_tempo: list[dict]) -> dict:
    """A visão geral, montada do que `saude` já calculou: o alerta da visão
    geral é exatamente o problema da linha da empresa na lista."""
    agora = datetime.now(timezone.utc)
    inicio_mes = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    ativas = [t for t in tenants if t.get("status") == "active"]

    def _s(t):
        return saude_por_id.get(t["id"], {})

    por_marca = {}
    for t in ativas:
        m = normaliza_marca(t.get("marca"))
        linha = por_marca.setdefault(m, {"marca": m, "empresas": 0, "mensagens_7d": 0})
        linha["empresas"] += 1
        linha["mensagens_7d"] += _s(t).get("mensagens_7d", 0)

    # Um alerta por tipo, com a lista de empresas: "3 empresas com WhatsApp
    # fora do ar" e o nome de cada uma, cada uma com o próprio botão de entrar.
    alertas = {}
    for t in tenants:
        for p in _s(t).get("problemas", []):
            a = alertas.setdefault(p["tipo"], {"tipo": p["tipo"], "nivel": p["nivel"],
                                               "empresas": []})
            a["empresas"].append({"id": t["id"], "name": t["name"], "para": p.get("para"),
                                  **{k: p[k] for k in ("n", "nomes", "motivo", "ultima", "detalhe", "pct")
                                     if k in p}})
    ordem = {"alto": 0, "medio": 1, "baixo": 2}
    lista_alertas = sorted(alertas.values(),
                           key=lambda a: (ordem[a["nivel"]], -len(a["empresas"])))

    # O semáforo do topo: cada empresa ativa entra em uma faixa só, a do pior
    # problema dela.
    faixas = {"em_dia": 0, "alto": 0, "medio": 0}
    for t in ativas:
        niveis = {p["nivel"] for p in _s(t).get("problemas", [])}
        faixas["alto" if "alto" in niveis else "medio" if "medio" in niveis else "em_dia"] += 1

    def _soma(campo):
        return sum(_s(t).get(campo, 0) for t in tenants)

    com_movimento = sum(1 for t in ativas if _s(t).get("mensagens_7d"))
    com_movimento_ant = sum(1 for t in ativas if _s(t).get("mensagens_7d_anterior"))

    top = sorted((t for t in ativas if _s(t).get("mensagens_7d")),
                 key=lambda t: -_s(t)["mensagens_7d"])[:TOP]

    consumo = sorted((t for t in tenants if _s(t).get("ia", {}).get("tokens")),
                     key=lambda t: -_s(t)["ia"]["tokens_plataforma"])

    return {
        "empresas": {
            "total": len(tenants),
            "ativas": len(ativas),
            "suspensas": len(tenants) - len(ativas),
            "novas_mes": sum(1 for t in tenants if (t.get("created_at") or "") >= inicio_mes),
            "com_movimento_7d": com_movimento,
            "com_movimento_7d_anterior": com_movimento_ant,
        },
        "faixas": faixas,
        "semana": {
            "mensagens": _soma("mensagens_7d"),
            "mensagens_anterior": _soma("mensagens_7d_anterior"),
            "conversas": _soma("conversas_7d"),
            "conversas_anterior": _soma("conversas_7d_anterior"),
            "leads": _soma("leads_7d"),
            "leads_anterior": _soma("leads_7d_anterior"),
        },
        "vendas_30d": {
            "n": _soma("vendas_30d"),
            "valor": sum(_s(t).get("vendas_30d_valor", 0.0) for t in tenants),
        },
        "ia": {
            "tokens": sum(_s(t).get("ia", {}).get("tokens", 0) for t in tenants),
            "tokens_plataforma": sum(_s(t).get("ia", {}).get("tokens_plataforma", 0) for t in tenants),
            "custo_usd": round(sum(_s(t).get("ia", {}).get("custo_usd", 0.0) for t in tenants), 2),
            "empresas": len(consumo),
            "ranking": [{"id": t["id"], "name": t["name"], **_s(t)["ia"]} for t in consumo[:TOP_IA]],
        },
        "por_marca": sorted(por_marca.values(), key=lambda m: -m["empresas"]),
        "serie": serie_dias,
        "alertas": lista_alertas,
        "top": [{"id": t["id"], "name": t["name"], "marca": normaliza_marca(t.get("marca")),
                 "mensagens_7d": _s(t)["mensagens_7d"],
                 "mensagens_7d_anterior": _s(t)["mensagens_7d_anterior"],
                 "leads_7d": _s(t).get("leads_7d", 0)}
                for t in top],
        "atividade": linha_do_tempo,
        "gerado_em": agora.isoformat(),
    }
