"""Tudo que a agenda diz ao contato pelo WhatsApp: confirmação, lembrete e a
resposta dele ao lembrete.

Separado de `agenda.py` por dependência, não por gosto: enviar mensagem passa
por `outbound` e `flow_runtime`, e `flow_runtime` importa `flow_engine`, que
importa `agenda` para o nó de Agendamento. Deixar o envio dentro de `agenda`
fecharia o ciclo e derrubaria o boot: mesma razão do `_campanhas()` tardio em
`flow_runtime`.

Três decisões:

  - **O lembrete é o módulo inteiro se pagando.** Falta em horário marcado é o
    prejuízo do negócio de serviço, e um lembrete no dia anterior é o que a
    reduz. Sem ele, agendar pelo WhatsApp economiza uma ligação para marcar e
    não economiza a cadeira vazia.

  - **A resposta ao lembrete é cotejada com a mensagem inteira**, normalizada,
    como o opt-out de campanha: "quero cancelar meu pedido" não pode cancelar
    a consulta de amanhã. A diferença é que aqui palavras curtas (`sim`, `ok`,
    `1`) valem: elas só são consultadas quando a conversa está com
    `agenda_aguardando` preenchido, isto é, logo depois de uma pergunta nossa
    que pedia exatamente isso. Sem esse contexto elas seriam ambíguas demais.

  - **Falha de envio não desfaz o agendamento.** O horário está reservado; o
    contato não recebeu o aviso. Cancelar por causa disso trocaria um problema
    de comunicação por um de agenda.
"""
import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import agenda
from db import get_db

logger = logging.getLogger("zappzen.agenda")

# De quanto em quanto tempo a varredura de lembretes roda. Lembrete é sobre
# hora marcada: quem tem consulta às 14h de amanhã não fica pior por receber o
# aviso às 14h05 de hoje em vez de às 14h00. Mesmo raciocínio do polling de 60s
# do selo de atividades atrasadas contra os 3s da fila.
INTERVALO = 5 * 60

# Teto da janela varrida numa passada, independente do que cada empresa
# configurou. Sem ele, uma empresa com `lembrete_horas` absurdo (720) faria a
# varredura carregar um mês de agenda a cada cinco minutos.
MAX_ANTECEDENCIA_HORAS = 168  # 7 dias

# Teto de agendamentos processados por passada. Uma empresa que ligue o lembrete
# depois de já ter mil horários marcados dispararia mil mensagens de uma vez
# que é exatamente o padrão de disparo que derruba número de WhatsApp.
MAX_POR_PASSADA = 200

_task = None


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Mensagens
# ---------------------------------------------------------------------------

# Os padrões existem para o módulo funcionar sem ninguém escrever nada. Cada um
# é sobrescrevível em `scheduling_settings`, porque o tom de uma clínica não é o
# de uma oficina.
MENSAGENS = {
    "confirmacao": (
        "✅ Agendamento confirmado!\n\n"
        "*{servico}*\n"
        "🗓 {data_completa}\n"
        "👤 {profissional}\n\n"
        "Qualquer imprevisto, é só avisar por aqui."
    ),
    "lembrete": (
        "Olá, {contato}! 👋\n\n"
        "Passando para lembrar do seu horário:\n\n"
        "*{servico}*\n"
        "🗓 {data_completa}\n"
        "👤 {profissional}\n\n"
        "Responda *CONFIRMAR* se estiver tudo certo, ou *CANCELAR* se não puder vir."
    ),
    "cancelamento": (
        "Seu agendamento de *{servico}* em {data_completa} foi cancelado.\n\n"
        "Se quiser remarcar, é só me chamar."
    ),
}


def montar(modelo: str, agendamento: dict, config: dict) -> str:
    """Preenche o texto com os dados do agendamento.

    Placeholder desconhecido fica como está, em vez de derrubar o envio: quem
    escreve o texto na tela erra o nome de um campo com facilidade, e perder o
    lembrete inteiro por causa de `{profisional}` seria desproporcional.
    """
    tz = agenda.fuso_de(config)
    inicio = agenda.local(agendamento["inicio"], tz)
    valores = {
        "contato": (agendamento.get("contact_nome") or "").split(" ")[0] or "tudo bem",
        "contato_completo": agendamento.get("contact_nome") or "",
        "servico": agendamento.get("service_nome") or "atendimento",
        "profissional": agendamento.get("resource_nome") or "nossa equipe",
        "data": f"{inicio.day:02d}/{inicio.month:02d}/{inicio.year}",
        "hora": f"{inicio.hour:02d}:{inicio.minute:02d}",
        "data_completa": agenda.rotulo_completo(agendamento["inicio"], tz),
        "duracao": f"{agendamento.get('duracao_min')} min",
    }

    def troca(m):
        return str(valores.get(m.group(1), m.group(0)))

    return re.sub(r"\{([a-zA-Z0-9_]+)\}", troca, modelo)


def texto_de(tipo: str, agendamento: dict, config: dict) -> str:
    modelo = (config.get(f"mensagem_{tipo}") or "").strip() or MENSAGENS[tipo]
    return montar(modelo, agendamento, config)


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------

async def _conexao(db, tenant_id: str, agendamento: dict) -> dict:
    """Por qual número da empresa este aviso sai.

    Preferência para a conexão em que o agendamento nasceu: o contato já
    conversou por ali, e trocar de remetente no meio de um assunto parece outra
    empresa falando: a mesma regra de `_resolve_conexao` na ficha do contato.
    Sem ela (agendamento feito à mão na tela), cai na conversa mais recente do
    contato e, por último, na primeira conexão conectada da empresa.
    """
    conn_id = agendamento.get("whatsapp_connection_id")
    if conn_id:
        conn = await db.whatsapp_connections.find_one(
            {"id": conn_id, "tenant_id": tenant_id}, {"_id": 0})
        if conn:
            return conn

    ultima = await db.conversation_sessions.find(
        {"tenant_id": tenant_id, "contact_id": agendamento["contact_id"]},
        {"_id": 0, "whatsapp_connection_id": 1},
    ).sort([("updated_at", -1), ("_id", -1)]).to_list(1)
    if ultima and ultima[0].get("whatsapp_connection_id"):
        conn = await db.whatsapp_connections.find_one(
            {"id": ultima[0]["whatsapp_connection_id"], "tenant_id": tenant_id}, {"_id": 0})
        if conn:
            return conn

    return await db.whatsapp_connections.find_one(
        {"tenant_id": tenant_id, "status": "conectado"}, {"_id": 0}) \
        or await db.whatsapp_connections.find_one({"tenant_id": tenant_id}, {"_id": 0})


async def avisar(db, tenant_id: str, agendamento: dict, tipo: str, config: dict = None,
                 marcar_espera: bool = False) -> bool:
    """Manda um aviso de agenda para o contato. Devolve se saiu.

    A conversa sai de `outbound.ensure_session`, nunca montada aqui: é a regra
    do projeto, e é ela que garante que a resposta do contato caia numa conversa
    com contexto em vez de abrir uma segunda para o mesmo número.

    Nunca levanta. Um lembrete que não sai é ruim; uma varredura que morre no
    primeiro contato sem conexão deixaria todos os outros sem lembrete nenhum.
    """
    # Tardios: `outbound` puxa `flow_runtime`, que puxa `flow_engine`, que
    # importa `agenda`. No topo, o ciclo fecha e o backend não sobe.
    import outbound
    import flow_runtime

    try:
        config = config or await agenda.configuracao(db, tenant_id)
        contato = await db.contacts.find_one(
            {"id": agendamento["contact_id"], "tenant_id": tenant_id}, {"_id": 0})
        if not contato:
            logger.warning("Agendamento %s sem contato: aviso %s não enviado",
                           agendamento["id"], tipo)
            return False
        conn = await _conexao(db, tenant_id, agendamento)
        if not conn:
            logger.warning("Empresa %s sem conexão de WhatsApp: aviso %s não enviado",
                           tenant_id, tipo)
            return False

        session, _ = await outbound.ensure_session(
            db, tenant_id, conn["id"], contato,
            departamento_id=conn.get("departamento_padrao_id"),
            origem="agenda",
            # `False` de propósito: com a marca de primeira resposta, o caminho
            # de entrada trata a resposta como resposta de disparo e não deixa o
            # agente de IA atender. Quem responde "posso remarcar?" a um lembrete
            # precisa ser atendido, não posto na fila em silêncio.
            aguardar_primeira_resposta=False,
        )
        await flow_runtime.send_human_message(
            tenant_id, session["id"], texto_de(tipo, agendamento, config))

        if marcar_espera:
            # De qual agendamento o "CONFIRMAR" da próxima mensagem fala. Sem
            # isto, a resposta chega sem referência e teria de adivinhar entre os
            # horários futuros do contato.
            await db.conversation_sessions.update_one(
                {"id": session["id"], "tenant_id": tenant_id},
                {"$set": {"agenda_aguardando": agendamento["id"], "updated_at": _now()}},
            )
        return True
    except Exception as e:
        logger.warning("Falha ao avisar (%s) do agendamento %s: %s",
                       tipo, agendamento.get("id"), e)
        return False


# ---------------------------------------------------------------------------
# Resposta do contato ao lembrete
# ---------------------------------------------------------------------------

def _normaliza(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", texto.lower()).strip()


# Cotejo com a mensagem **inteira**, nunca "contém": é a mesma regra do opt-out
# de campanha, pelo mesmo motivo: "preciso confirmar uns dados" não é uma
# confirmação de presença.
CONFIRMA = {"confirmar", "confirmo", "confirmado", "confirmada", "sim", "ok",
            "1", "esta confirmado", "tudo certo", "vou sim", "estarei la"}
CANCELA = {"cancelar", "cancela", "cancelado", "cancelo", "nao", "2",
           "nao vou", "nao posso", "nao poderei", "desmarcar", "desmarca"}


async def responder_lembrete(db, tenant_id: str, session: dict, texto: str) -> str:
    """Trata "CONFIRMAR"/"CANCELAR" quando a conversa está esperando essa resposta.

    Devolve `"confirmado"`, `"cancelado"` ou `None` (não era uma resposta de
    lembrete: a mensagem segue o caminho normal, bot ou agente de IA).

    Chamado antes de qualquer roteamento, como o opt-out: o contato que responde
    ao lembrete não deve depender de haver um bot configurado naquela conexão.
    """
    import flow_runtime

    appointment_id = session.get("agenda_aguardando")
    if not appointment_id:
        return None
    n = _normaliza(texto)
    if not n:
        return None
    if n in CONFIRMA:
        acao = "confirmado"
    elif n in CANCELA:
        acao = "cancelado"
    else:
        return None

    doc = await db.appointments.find_one(
        {"id": appointment_id, "tenant_id": tenant_id}, {"_id": 0})
    # A marca sai de qualquer jeito: se o agendamento sumiu ou já foi resolvido,
    # deixá-la faria a próxima mensagem parecida ser lida como resposta de novo.
    await db.conversation_sessions.update_one(
        {"id": session["id"], "tenant_id": tenant_id},
        {"$set": {"agenda_aguardando": None}},
    )
    session["agenda_aguardando"] = None
    if not doc or doc["status"] not in (agenda.STATUS_AGENDADO, agenda.STATUS_CONFIRMADO):
        return None

    config = await agenda.configuracao(db, tenant_id)
    tz = agenda.fuso_de(config)
    if acao == "confirmado":
        await agenda.mudar_status(db, tenant_id, appointment_id, agenda.STATUS_CONFIRMADO)
        resposta = (f"Perfeito! Presença confirmada para "
                    f"{agenda.rotulo_completo(doc['inicio'], tz)}. Até lá! 👍")
    else:
        await agenda.cancelar(db, tenant_id, appointment_id,
                              por="contato", motivo="Cancelado pelo contato no WhatsApp")
        resposta = (f"Tudo bem, cancelei o seu horário de "
                    f"{agenda.rotulo_completo(doc['inicio'], tz)}. "
                    "Se quiser remarcar, é só me dizer.")

    await flow_runtime.send_human_message(tenant_id, session["id"], resposta)
    return acao


# ---------------------------------------------------------------------------
# Varredura de lembretes
# ---------------------------------------------------------------------------

async def _pendentes(db, agora: datetime) -> list:
    """Agendamentos futuros que ainda não receberam lembrete, na janela máxima.

    Uma consulta só para todas as empresas, filtrando depois pela janela de cada
    uma. O contrário: uma consulta por empresa, seria uma ida ao banco por
    cliente a cada cinco minutos, e o banco está atrás de um túnel SSH. Mesmo
    raciocínio do `_tenant_windows` da retenção de mídia.
    """
    limite = agenda._iso(agora + timedelta(hours=MAX_ANTECEDENCIA_HORAS))
    cursor = db.appointments.find(
        {"status": {"$in": [agenda.STATUS_AGENDADO, agenda.STATUS_CONFIRMADO]},
         "lembrete_enviado_em": None,
         "inicio": {"$gt": agenda._iso(agora), "$lt": limite}},
        {"_id": 0},
    ).sort([("inicio", 1), ("_id", 1)])
    return await cursor.to_list(MAX_POR_PASSADA)


async def _varrer():
    db = get_db()
    agora = agenda._agora()
    pendentes = await _pendentes(db, agora)
    if not pendentes:
        return

    configs = {}
    enviados = 0
    for a in pendentes:
        tenant_id = a["tenant_id"]
        if tenant_id not in configs:
            configs[tenant_id] = await agenda.configuracao(db, tenant_id)
        config = configs[tenant_id]
        if not config.get("lembrete_ativo"):
            continue
        horas = float(config.get("lembrete_horas") or 24)
        if a["inicio"] > agenda._iso(agora + timedelta(hours=horas)):
            continue  # ainda cedo para esta empresa

        # A marca é gravada **antes** do envio. Um envio que falhe no meio e
        # deixasse a marca em branco faria a passada seguinte tentar de novo, e
        # um contato pode acabar recebendo o mesmo lembrete a cada cinco minutos
        # enquanto a conexão estiver instável. Perder um lembrete é melhor que
        # repeti-lo em laço, e a falha fica no log.
        await db.appointments.update_one(
            {"id": a["id"], "tenant_id": tenant_id, "lembrete_enviado_em": None},
            {"$set": {"lembrete_enviado_em": _now(), "updated_at": _now()}},
        )
        await avisar(db, tenant_id, a, "lembrete", config, marcar_espera=True)
        enviados += 1

    if enviados:
        logger.info("Lembretes de agenda enviados: %d", enviados)


async def _loop():
    logger.info("Lembretes de agenda ativos (varredura a cada %ds)", INTERVALO)
    while True:
        try:
            await _varrer()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Varredura de lembretes falhou: %s", e)
        await asyncio.sleep(INTERVALO)


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
