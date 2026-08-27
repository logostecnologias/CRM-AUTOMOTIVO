"""Conversa iniciada por nós — a base de todo envio ativo.

Nasceu dentro de `campaigns.py`, e saiu de lá quando a ficha do contato ganhou
o botão de enviar mensagem: o conceito não é "campanha", é "a plataforma
escreveu primeiro". Os dois casos precisam da mesma coisa — uma
`conversation_sessions` que exista **antes** do envio, para a resposta do
contato ter onde cair com contexto.

A diferença entre os dois está em quem assume a conversa:

  - **campanha** não tem dono. A conversa nasce em `bot` (a maioria dos
    disparados não responde, e jogar o público inteiro na fila encheria a
    Central de conversas mudas) e só entra na fila quando o contato responde;
  - **mensagem direta da ficha** já nasce com dono: quem clicou em enviar. A
    conversa vai direto para `em_atendimento` no nome dessa pessoa, porque foi
    ela que começou o assunto e é a ela que a resposta interessa.
"""
import logging
import uuid
from datetime import datetime, timezone

import flow_runtime

logger = logging.getLogger("zappzen.outbound")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def sessao_aberta(db, tenant_id: str, conn_id: str, contact_id: str) -> dict | None:
    """A conversa viva deste contato nesta conexão, se houver.

    Existe separada porque quem vai escrever precisa dela **antes** de decidir
    como escrever: é dela que sai a janela de 24h, e a decisão entre texto
    livre e modelo aprovado acontece antes de qualquer conversa ser criada.
    """
    return await db.conversation_sessions.find_one({
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "whatsapp_connection_id": conn_id,
        "status": {"$in": ["ativa", "aguardando_humano"]},
    })


async def ensure_session(
    db,
    tenant_id: str,
    conn_id: str,
    contact: dict,
    *,
    bot_id: str | None = None,
    departamento_id: str | None = None,
    origem: str = "campanha",
    campanha_id: str | None = None,
    resposta_modo: str = "aguardando",
    atendente_id: str | None = None,
    aguardar_primeira_resposta: bool = True,
) -> tuple[dict, bool]:
    """A conversa em que o envio ativo vai aparecer. Devolve (sessão, criada).

    Conversa aberta do mesmo contato na mesma conexão é **reaproveitada**, e o
    estado dela não é mexido: abrir uma segunda dividiria o histórico do número
    em dois lugares, e mudar o status de uma conversa viva arrancaria ela de
    quem estiver atendendo.
    """
    session = await sessao_aberta(db, tenant_id, conn_id, contact["id"])
    if session:
        marcas = {"updated_at": _now()}
        if campanha_id:
            marcas["campanha_id"] = campanha_id
        await db.conversation_sessions.update_one({"id": session["id"]}, {"$set": marcas})
        session.update(marcas)
        return session, False

    # Com dono, a conversa já nasce em atendimento humano: o `status`
    # "aguardando_humano" é o que impede o motor de fluxos de tentar responder
    # por cima quando o contato retornar (ver handle_incoming_message).
    if atendente_id:
        status, status_atendimento = "aguardando_humano", "em_atendimento"
    else:
        status, status_atendimento = "ativa", "bot"

    session = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "contact_id": contact["id"],
        "bot_id": bot_id,
        "flow_id": None,
        "whatsapp_connection_id": conn_id,
        "departamento_id": departamento_id,
        "atendente_id": atendente_id,
        "status_atendimento": status_atendimento,
        "aguardando_desde": None,
        "assumido_em": _now() if atendente_id else None,
        "finalizado_em": None,
        "node_atual_id": None,
        "variables": {
            "nome_contato": contact.get("nome") or contact.get("numero_whatsapp"),
            "numero": contact.get("numero_whatsapp"),
        },
        "status": status,
        "awaiting": None,
        "last_user_message": None,
        "origem": origem,
        "campanha_id": campanha_id,
        "resposta_modo": resposta_modo,
        # O sinal que faz a resposta funcionar quando ninguém assumiu: a
        # conversa foi aberta por nós, então não há fluxo em andamento nem menu
        # esperando. Sem ele, o caminho de entrada acharia uma sessão "ativa"
        # sem `awaiting`, não faria nada, e a resposta ficaria no histórico sem
        # bot e sem atendente. Com dono não faz sentido: já tem quem responda.
        "aguardando_primeira_resposta": bool(aguardar_primeira_resposta and not atendente_id),
        "unread_count": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.conversation_sessions.insert_one(dict(session))
    session.pop("_id", None)
    return session, True


async def send_direct(db, tenant_id: str, contact: dict, conn: dict, texto: str,
                      autor_id: str, template: dict | None = None) -> dict:
    """Mensagem 1:1 para um contato, a partir da ficha dele.

    O envio em si é `flow_runtime.send_human_message`, o mesmo do painel de
    atendimento — não uma segunda implementação. É o que garante que a
    mensagem saia com o nome de quem enviou, entre no histórico pelo
    `log_message` (prévia da conversa junto) e que uma falha de entrega não
    apareça como enviada na tela.

    **A janela de 24h decide qual dos dois caminhos vale.** Escrever para quem
    não falou com a empresa nas últimas 24 horas é exatamente o caso em que o
    WhatsApp exige modelo aprovado, e é o caso mais comum aqui: a ficha existe
    justamente para começar uma conversa. Com `template`, sai o modelo; sem
    ele, sai texto livre e a janela fechada recusa com `JanelaFechada`, para a
    tela dizer o que fazer em vez de mostrar "falha ao enviar".

    O texto continua indo para o histórico nos dois casos: com modelo, ele é o
    corpo já preenchido, senão o atendente abriria a conversa sem saber o que
    foi dito ao contato.

    `opt_out` **não** bloqueia aqui: ele é recusa de campanha, e isto é uma
    pessoa escrevendo deliberadamente para outra. Quem chama mostra o aviso.
    """
    # A janela é conferida **antes** de a conversa existir. Na ordem inversa,
    # um envio recusado deixaria para trás uma conversa vazia na Central, em
    # que ninguém disse nada: o atendente abriria um card sem mensagem
    # nenhuma e sem entender de onde ele veio.
    atual = await sessao_aberta(db, tenant_id, conn["id"], contact["id"])
    if not template and not flow_runtime.janela_aberta(atual):
        raise flow_runtime.JanelaFechada(flow_runtime.MSG_JANELA_FECHADA)

    session, criada = await ensure_session(
        db, tenant_id, conn["id"], contact,
        departamento_id=conn.get("departamento_padrao_id"),
        origem="direta",
        atendente_id=autor_id,
        aguardar_primeira_resposta=False,
    )
    if template and not flow_runtime.janela_aberta(session):
        await flow_runtime.send_template_message(
            tenant_id, session["id"], template["nome"],
            template.get("idioma") or "pt_BR", template.get("valores") or [], texto)
    else:
        await flow_runtime.send_human_message(tenant_id, session["id"], texto)
    return {"session_id": session["id"], "criada": criada}
