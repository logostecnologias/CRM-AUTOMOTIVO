"""Painel inicial da empresa.

Reescrito porque contava pelo campo errado: usava `status` (ativa/finalizada,
o estado do motor de fluxos) para dizer "conversas ativas" e "aguardando
humano", enquanto o Kanban, a Central e os relatórios usam
`status_atendimento`. Os dois campos existem e querem dizer coisas diferentes,
então o painel mostrava números que não fechavam com nenhuma outra tela.

Agora ele resume o que o produto virou: atendimento, funil, agenda e campanhas.
Cada bloco sai de **uma** agregação, não de uma contagem por número — o que
domina aqui não é o volume, é a ida e volta até o banco.

Redesenhado em 20/10/2026, porque o cliente o achou inútil, e com razão: eram
sete caixas de contagem sem comparação, sem tendência e sem nada para clicar.
O que entrou:

  - **`alertas`**: o que precisa de alguém agora, cada um com o lugar onde se
    resolve. Fila com a espera mais antiga, atividade atrasada, conexão fora do
    ar, agente de IA com a chave recusada, campanha pausada. É a primeira coisa
    da tela, e vazia ela diz que está tudo em dia, que também é informação.
  - **`semana`**: conversas novas e espera média dos últimos 7 dias contra os 7
    anteriores. Um número sem comparação não diz se a operação melhorou.
  - **`serie`**: conversas novas por dia em 14 dias, separando as que um
    atendente pegou das que o robô ou o agente resolveram sozinhos. É o número
    que mostra quanto a automação está trabalhando.
  - **`agenda_hoje`**: os horários marcados de hoje, só para empresa que usa a
    agenda. O dia é o do fuso da empresa, não do navegador: mesma regra da
    tela de Agenda, porque o horário é da empresa.

Os tempos não usam `relatorios.atendimento`: aquele lê até 50 mil conversas, e
esta tela abre a cada login. Aqui a janela é de 14 dias e a projeção é de três
campos.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends

import agenda as agenda_mod
import atividades
from auth import accessible_connection_ids, require_tenant_member
from db import get_db
from relatorios import _media, _segundos

router = APIRouter(prefix="/api", tags=["dashboard"])

KANBAN = ("bot", "aguardando", "em_atendimento", "finalizado")
DIAS_SERIE = 14
# Teto da leitura da série. Acima disso a série é cortada e `serie_parcial`
# avisa: uma empresa com 20 mil conversas em duas semanas tem os relatórios
# para o detalhe.
MAX_SESSOES_SERIE = 20000
MAX_AGENDA_HOJE = 8


def _now():
    return datetime.now(timezone.utc).isoformat()


def _filtro_conexoes(filtro: dict, conexoes: list | None) -> dict:
    if conexoes is not None:
        filtro["whatsapp_connection_id"] = {"$in": conexoes}
    return filtro


async def _alertas(db, tenant_id: str, admin: bool, conexoes, conversas: dict,
                   agenda: dict) -> list:
    """O que precisa de alguém agora, do mais grave para o menos.

    Cada alerta tem `para`, o caminho da tela onde ele se resolve: um aviso que
    não leva a lugar nenhum obriga a pessoa a lembrar onde fica cada coisa.
    """
    saida = []

    if conversas["aguardando"]:
        mais_antiga = await db.conversation_sessions.find(
            _filtro_conexoes({"tenant_id": tenant_id, "status_atendimento": "aguardando",
                              "aguardando_desde": {"$ne": None}}, conexoes),
            {"_id": 0, "aguardando_desde": 1},
        ).sort("aguardando_desde", 1).limit(1).to_list(1)
        saida.append({
            "tipo": "fila", "nivel": "alto", "n": conversas["aguardando"],
            "desde": mais_antiga[0]["aguardando_desde"] if mais_antiga else None,
            "para": "/app/inbox",
        })

    if agenda.get("atrasadas"):
        saida.append({"tipo": "atividades", "nivel": "medio", "n": agenda["atrasadas"],
                      "para": "/app/atividades" if admin else None})

    if not admin:
        return saida

    fora = await db.whatsapp_connections.find(
        {"tenant_id": tenant_id, "status": {"$ne": "conectado"}},
        {"_id": 0, "nome": 1, "status": 1},
    ).to_list(20)
    if fora:
        saida.append({"tipo": "conexoes", "nivel": "alto", "n": len(fora),
                      "nomes": [c.get("nome") or "sem nome" for c in fora],
                      "para": "/app/whatsapp"})

    agentes = await db.ai_agents.find(
        # Agente pausado ou desligado com a chave quebrada não atende ninguém,
        # então não é urgência: vira quando alguém religá-lo.
        {"tenant_id": tenant_id, "credencial_status": "erro", "ativo": {"$ne": False},
         "modo": {"$ne": "desligado"}},
        {"_id": 0, "nome": 1},
    ).to_list(20)
    if agentes:
        saida.append({"tipo": "agentes", "nivel": "alto", "n": len(agentes),
                      "nomes": [a.get("nome") or "sem nome" for a in agentes],
                      "para": "/app/ai-agents"})

    pausadas = await db.campaigns.find(
        {"tenant_id": tenant_id, "status": "pausada"},
        {"_id": 0, "nome": 1, "motivo_pausa": 1},
    ).to_list(20)
    if pausadas:
        saida.append({"tipo": "campanhas", "nivel": "medio", "n": len(pausadas),
                      "nomes": [c.get("nome") or "sem nome" for c in pausadas],
                      "motivo": pausadas[0].get("motivo_pausa"),
                      "para": "/app/campanhas"})
    return saida


async def _serie_e_semana(db, tenant_id: str, conexoes) -> dict:
    """Conversas novas por dia (14 dias) e a semana contra a anterior.

    Uma leitura só, com três campos, alimenta as duas coisas. O dia é o prefixo
    do ISO, como nos relatórios: o painel tem de fechar com eles.
    """
    agora = datetime.now(timezone.utc)
    hoje = agora.date()
    de = (agora - timedelta(days=DIAS_SERIE - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0).isoformat()
    corte = (agora - timedelta(days=7)).isoformat()

    sessoes = await db.conversation_sessions.find(
        _filtro_conexoes({"tenant_id": tenant_id, "created_at": {"$gte": de}}, conexoes),
        {"_id": 0, "created_at": 1, "aguardando_desde": 1, "assumido_em": 1},
    ).to_list(MAX_SESSOES_SERIE + 1)
    parcial = len(sessoes) > MAX_SESSOES_SERIE
    sessoes = sessoes[:MAX_SESSOES_SERIE]

    # Todo dia da janela aparece, mesmo zerado: dia sem barra no meio do
    # gráfico é dia sem conversa, não dia que sumiu.
    por_dia = {}
    for n in range(DIAS_SERIE - 1, -1, -1):
        d = (hoje - timedelta(days=n)).isoformat()
        por_dia[d] = {"dia": d, "automatico": 0, "humano": 0}

    atual = {"conversas": 0, "esperas": []}
    anterior = {"conversas": 0, "esperas": []}
    for s in sessoes:
        criado = s.get("created_at") or ""
        linha = por_dia.get(criado[:10])
        if linha:
            linha["humano" if s.get("assumido_em") else "automatico"] += 1
        alvo = atual if criado >= corte else anterior
        alvo["conversas"] += 1
        espera = _segundos(s.get("aguardando_desde"), s.get("assumido_em"))
        if espera is not None:
            alvo["esperas"].append(espera)

    return {
        "serie": list(por_dia.values()),
        "serie_parcial": parcial,
        "semana": {
            "conversas": atual["conversas"],
            "conversas_anterior": anterior["conversas"],
            "espera_media_s": _media(atual["esperas"]),
            "espera_media_anterior_s": _media(anterior["esperas"]),
            "espera_amostra": len(atual["esperas"]),
        },
    }


async def _agenda_hoje(db, tenant_id: str) -> dict | None:
    """Os horários de hoje, ou None se a empresa não usa a agenda.

    "Hoje" no fuso da empresa (ver o cabeçalho). Sem serviço cadastrado o bloco
    some: mostrar "nenhum horário hoje" a quem não agenda nada é ruído.
    """
    if not await db.services.find_one({"tenant_id": tenant_id}, {"_id": 1}):
        return None
    config = await agenda_mod.configuracao(db, tenant_id)
    tz = agenda_mod.fuso_de(config)
    dia = datetime.now(tz).date()
    de = agenda_mod._iso(datetime.combine(dia, datetime.min.time(), tzinfo=tz))
    ate = agenda_mod._iso(datetime.combine(dia + timedelta(days=1),
                                           datetime.min.time(), tzinfo=tz))
    filtro = {"tenant_id": tenant_id, "inicio": {"$gte": de, "$lt": ate},
              "status": {"$in": list(agenda_mod.OCUPAM)}}
    total = await db.appointments.count_documents(filtro)
    itens = await db.appointments.find(
        filtro,
        {"_id": 0, "id": 1, "inicio": 1, "service_nome": 1, "resource_nome": 1,
         "contact_nome": 1, "status": 1},
    ).sort([("inicio", 1), ("_id", 1)]).limit(MAX_AGENDA_HOJE).to_list(MAX_AGENDA_HOJE)
    return {"fuso": str(tz), "total": total, "itens": itens}


@router.get("/dashboard/metrics")
async def dashboard_metrics(hoje_ate: str | None = None, semana_ate: str | None = None,
                            user=Depends(require_tenant_member)):
    """Resumo da operação. `hoje_ate`/`semana_ate` vêm do navegador, que é quem
    sabe o fuso de quem está olhando — mesma regra das atividades.

    O atendente vê a fila só das conexões liberadas para ele e as atividades
    que são dele: o painel não pode mostrar uma fila que a Central não mostra.
    """
    db = get_db()
    tenant_id = user["tenant_id"]
    admin = user.get("role") == "tenant_admin"
    conexoes = await accessible_connection_ids(db, user)
    agora = _now()
    inicio_mes = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    trinta_dias = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    # Atendimento: as quatro colunas do Kanban numa agregação só.
    conversas = {s: 0 for s in KANBAN}
    cursor = db.conversation_sessions.aggregate([
        {"$match": _filtro_conexoes({"tenant_id": tenant_id}, conexoes)},
        {"$group": {"_id": "$status_atendimento", "n": {"$sum": 1}}},
    ])
    async for row in cursor:
        if row["_id"] in conversas:
            conversas[row["_id"]] = row["n"]
    minhas = await db.conversation_sessions.count_documents(
        {"tenant_id": tenant_id, "status_atendimento": "em_atendimento",
         "atendente_id": user["id"]})

    agenda = await atividades.resumo(db, tenant_id, None if admin else user["id"],
                                     hoje_ate, semana_ate)
    alertas = await _alertas(db, tenant_id, admin, conexoes, conversas, agenda)
    serie = await _serie_e_semana(db, tenant_id, conexoes)

    resposta = {
        "atendimento": {
            **conversas,
            # "Em aberto" é o que precisa de alguém: fila + em atendimento.
            "em_aberto": conversas["aguardando"] + conversas["em_atendimento"],
            "minhas": minhas,
        },
        "agenda": agenda,
        "agenda_hoje": await _agenda_hoje(db, tenant_id),
        "alertas": alertas,
        **serie,
        "gerado_em": agora,
    }
    if not admin:
        return resposta

    resposta["atendimento"]["mensagens_30d"] = await db.messages_log.count_documents(
        {"tenant_id": tenant_id, "timestamp": {"$gte": trinta_dias}})

    # Funil: aberto (o que está em jogo), ganho no mês (o que entrou) e a
    # conversão do mês sobre os decididos, a mesma conta do relatório do funil.
    funil = {"aberto": {"n": 0, "valor": 0.0}, "ganho_mes": {"n": 0, "valor": 0.0},
             "perdido_mes": {"n": 0}, "conversao_mes": None}
    cursor = db.deals.aggregate([
        {"$match": {"tenant_id": tenant_id, "status": "aberto"}},
        {"$group": {"_id": None, "n": {"$sum": 1}, "valor": {"$sum": "$valor"}}},
    ])
    async for row in cursor:
        funil["aberto"] = {"n": row["n"], "valor": row.get("valor") or 0}
    cursor = db.deals.aggregate([
        {"$match": {"tenant_id": tenant_id, "status": {"$in": ["ganho", "perdido"]},
                    "fechado_em": {"$gte": inicio_mes}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}, "valor": {"$sum": "$valor"}}},
    ])
    async for row in cursor:
        if row["_id"] == "ganho":
            funil["ganho_mes"] = {"n": row["n"], "valor": row.get("valor") or 0}
        else:
            funil["perdido_mes"] = {"n": row["n"]}
    decididos = funil["ganho_mes"]["n"] + funil["perdido_mes"]["n"]
    if decididos:
        funil["conversao_mes"] = funil["ganho_mes"]["n"] / decididos

    # Campanhas em disparo e o que saiu no mês. `enviado` é o que custou.
    campanhas = {
        "em_andamento": await db.campaigns.count_documents(
            {"tenant_id": tenant_id, "status": {"$in": ["enviando", "agendada"]}}
        ),
        "disparos_mes": await db.campaign_recipients.count_documents(
            {"tenant_id": tenant_id, "status": "enviado", "sent_at": {"$gte": inicio_mes}}
        ),
    }

    resposta.update({
        "funil": funil,
        "campanhas": campanhas,
        "base": {
            "contatos": await db.contacts.count_documents({"tenant_id": tenant_id}),
            "bots_ativos": await db.bots.count_documents(
                {"tenant_id": tenant_id, "status": "ativo"}
            ),
            "conexoes_conectadas": await db.whatsapp_connections.count_documents(
                {"tenant_id": tenant_id, "status": "conectado"}
            ),
            "conexoes_total": await db.whatsapp_connections.count_documents(
                {"tenant_id": tenant_id}
            ),
        },
    })
    return resposta
