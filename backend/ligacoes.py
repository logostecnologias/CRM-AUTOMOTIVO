"""Ligação não atendida que vira conversa de WhatsApp.

O problema que isto resolve não é técnico: é o cliente que vive de serviço
(refrigeração, oficina, clínica) recebendo mais ligação do que consegue
atender. Cada ligação perdida é um orçamento que foi para o concorrente. O
número dele desvia para um número do Twilio quando ele não atende, uma
gravação oferece "aperte 1 para receber nossa mensagem no WhatsApp", e a
tecla 1 abre a conversa por aqui, onde o bot, o agente de IA e a agenda já
trabalham sozinhos.

Decisões, e o motivo de cada uma:

  - **A tecla é o pedido.** Mandar modelo para todo mundo que ligou seria
    escrever primeiro para quem não pediu, que é o que a política de opt-in da
    Meta proíbe. Quem aperta 1 pediu a mensagem, e é só para ele que ela sai.

  - **Sem transferência e sem IA de voz, de propósito.** A ligação dura os
    segundos da gravação e custa um minuto do Twilio. Tudo o que vem depois é
    conversa de WhatsApp aberta pelo contato, que a Meta não cobra.

  - **A conversa sai de `outbound.ensure_session`, nunca montada aqui.** É a
    regra do projeto, e é ela que faz a resposta do contato cair numa conversa
    com contexto. Quem atende a resposta é escolha da empresa (`resposta_modo`):
    o agente de IA, um robô do editor ou direto a fila humana.

  - **Texto livre quando a janela está aberta, modelo quando não está.** Mesma
    regra do lembrete da agenda: quem falou com a empresa hoje recebe texto,
    que é mais natural e não custa nada; quem não falou só recebe modelo
    aprovado, que é o que o WhatsApp entrega fora da janela.

  - **Uma mensagem por pessoa, mesmo que ela ligue três vezes.** Quem não é
    atendido liga de novo em seguida, e cada tecla 1 viraria uma mensagem paga
    e repetida na conversa. Ligação do mesmo número dentro de
    `JANELA_REPETICAO_MIN` depois de uma mensagem que saiu não manda outra.

  - **O número de quem ligou não é "corrigido".** O `From` do Twilio já vem
    com o código do país, então ele é usado como chegou, só em dígitos. Passar
    por `normaliza_numero` seria pior que inútil: um número estrangeiro de 11
    dígitos ganharia um 55 na frente e a mensagem iria para outra pessoa.
"""
import aquecimento
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import contatos_csv
import twilio_voz

logger = logging.getLogger("zappzen.ligacoes")

# Quem atende quando o contato responder a mensagem.
#   agente  o agente de IA da conexão (e, sem agente, a fila humana)
#   bot     um robô do editor, do nó Início
#   fila    direto para a fila da Central, sem automação
MODOS = ("agente", "bot", "fila")

# Ligou de novo dentro deste prazo depois de uma mensagem que saiu: não manda
# outra. Meia hora cobre o "liguei, não atenderam, liguei de novo" sem impedir
# que alguém que ligou de manhã e de tarde receba a mensagem de novo.
JANELA_REPETICAO_MIN = 30

# Estados da ligação, na ordem em que acontecem.
RECEBIDA = "recebida"          # tocou a gravação
PEDIU = "pediu_whatsapp"       # apertou 1, envio ainda não terminou
ENVIANDO = "enviando"          # claim do envio (ver enviar_whatsapp)
ENVIADA = "enviada"            # a mensagem saiu
REPETIDA = "repetida"          # apertou 1, mas já tinha recebido há pouco
SEM_MODELO = "sem_modelo"      # janela fechada e nenhum modelo configurado
FALHA = "falha"                # a Meta (ou a configuração) recusou

TEXTOS_PADRAO = {
    "texto_pergunta": (
        "Olá! Agora não conseguimos atender. Para orçamento e agendamento, a "
        "gente te atende agora pelo WhatsApp. Aperte 1 para receber nossa mensagem."),
    "texto_confirmacao": "Pronto, já te mandamos mensagem no WhatsApp. Até já!",
    # Sem número não há para quem mandar: a gravação só diz onde achar a empresa.
    "texto_sem_numero": (
        "Olá! Agora não conseguimos atender. Nosso atendimento é pelo WhatsApp, "
        "neste mesmo número. Mande uma mensagem que a gente responde."),
    "mensagem": (
        "Olá! Recebemos sua ligação na {empresa}. Por aqui atendemos mais rápido: "
        "conte o que você precisa que já te ajudamos."),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def montar(texto: str, valores: dict) -> str:
    """Preenche `{empresa}` e `{numero}`.

    Placeholder desconhecido fica como está, em vez de derrubar o envio: mesma
    regra do `agenda_worker.montar`, pelo mesmo motivo.
    """
    return re.sub(r"\{([a-zA-Z0-9_]+)\}",
                  lambda m: str(valores.get(m.group(1), m.group(0))), texto or "")


def texto(config: dict, chave: str) -> str:
    return (config.get(chave) or "").strip() or TEXTOS_PADRAO[chave]


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

async def registrar(db, config: dict, call_sid: str, de: str, para: str) -> dict:
    """A ligação, criada na primeira passada e reaproveitada nas seguintes.

    A mesma ligação passa por aqui mais de uma vez (a segunda tentativa da
    pergunta volta ao mesmo endereço), então a chave é o `CallSid`, e só a
    primeira passada cria.
    """
    tenant_id = config["tenant_id"]
    atual = await db.ligacoes.find_one(
        {"tenant_id": tenant_id, "call_sid": call_sid}, {"_id": 0})
    if atual:
        return atual
    oculto = twilio_voz.numero_oculto(de)
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "call_sid": call_sid,
        "numero_chamado": twilio_voz.e164(para),
        # Só dígitos, exatamente os que vieram. Ver o docstring do módulo.
        "numero": None if oculto else re.sub(r"\D", "", de or "") or None,
        "oculto": oculto,
        "tecla": None,
        "status": RECEBIDA,
        "mensagem_tipo": None,
        "erro": None,
        "contact_id": None,
        "session_id": None,
        "respondeu_em": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.ligacoes.insert_one(dict(doc))
    return doc


async def marcar_tecla(db, tenant_id: str, ligacao_id: str, digito: str) -> None:
    mudanca = {"tecla": digito, "updated_at": _now()}
    if digito == "1":
        mudanca["status"] = PEDIU
    await db.ligacoes.update_one(
        # A tecla só avança o estado de quem ainda estava em `recebida`: um
        # segundo POST de tecla para a mesma ligação não pode tirar do
        # `enviada` uma mensagem que já saiu.
        {"id": ligacao_id, "tenant_id": tenant_id,
         **({"status": RECEBIDA} if digito == "1" else {})},
        {"$set": mudanca})


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------

async def _conexao(db, config: dict) -> dict | None:
    """Por qual número de WhatsApp a mensagem sai.

    O escolhido na tela; sem escolha, a primeira conexão conectada da empresa,
    que é o caso de quem tem um número só e não precisa pensar nisso.
    """
    tenant_id = config["tenant_id"]
    if config.get("whatsapp_connection_id"):
        conn = await db.whatsapp_connections.find_one(
            {"id": config["whatsapp_connection_id"], "tenant_id": tenant_id}, {"_id": 0})
        if conn:
            return conn
    return await db.whatsapp_connections.find_one(
        {"tenant_id": tenant_id, "status": "conectado"}, {"_id": 0}) \
        or await db.whatsapp_connections.find_one({"tenant_id": tenant_id}, {"_id": 0})


async def _contato(db, tenant_id: str, numero: str) -> dict:
    """A ficha de quem ligou, criada se ainda não existir.

    A busca cobre as duas grafias do celular brasileiro (`variantes_br`): o
    número que liga vem com o nono dígito, e o contato que já escreveu antes
    pode estar gravado sem ele, como o `wa_id` da Meta chegou. Procurar só pela
    forma exata criaria uma segunda ficha para a mesma pessoa.
    """
    contato = await db.contacts.find_one(
        {"tenant_id": tenant_id,
         "numero_whatsapp": {"$in": contatos_csv.variantes_br(numero)}}, {"_id": 0})
    if contato:
        return contato
    contato = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "numero_whatsapp": numero,
        "nome": numero,
        "email": None,
        "empresa": None,
        "cargo": None,
        # A origem só pode ser preenchida aqui: depois não há como saber que a
        # pessoa chegou por uma ligação.
        "origem": "ligação",
        "responsavel_id": None,
        "tags": [],
        "campos": {},
        "opt_out": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.contacts.insert_one(dict(contato))
    return contato


async def _repetida(db, ligacao: dict) -> bool:
    desde = (datetime.now(timezone.utc)
             - timedelta(minutes=JANELA_REPETICAO_MIN)).isoformat()
    return bool(await db.ligacoes.find_one({
        "tenant_id": ligacao["tenant_id"],
        "numero": ligacao["numero"],
        "status": ENVIADA,
        "id": {"$ne": ligacao["id"]},
        "created_at": {"$gte": desde},
    }, {"_id": 0, "id": 1}))


async def enviar_whatsapp(db, tenant_id: str, ligacao_id: str) -> str:
    """Manda a mensagem para quem apertou 1. Devolve o estado final.

    Roda depois de a resposta da ligação já ter saído (o Twilio espera no
    máximo 15 segundos pela resposta do webhook, e a pessoa não pode ficar
    muda na linha enquanto a Meta responde). Por isso nunca levanta: não há
    ninguém para receber a exceção, e o que aconteceu fica gravado na própria
    ligação.
    """
    # Tardios: `outbound` puxa `flow_runtime`, que importa este módulo para
    # marcar a resposta do contato. No topo, o ciclo fecharia.
    import flow_runtime
    import outbound

    # Claim atômico, como o destinatário de campanha: um segundo POST de tecla
    # (retry do Twilio, dedo nervoso) não pode mandar a mensagem duas vezes.
    ligacao = await db.ligacoes.find_one_and_update(
        {"id": ligacao_id, "tenant_id": tenant_id, "status": PEDIU},
        {"$set": {"status": ENVIANDO, "updated_at": _now()}},
    )
    if not ligacao:
        return "ignorada"

    async def fim(status: str, **extra) -> str:
        await db.ligacoes.update_one(
            {"id": ligacao_id, "tenant_id": tenant_id},
            {"$set": {"status": status, "updated_at": _now(), **extra}})
        return status

    try:
        if not ligacao.get("numero"):
            return await fim(FALHA, erro="Ligação sem número identificado")
        if await _repetida(db, ligacao):
            return await fim(REPETIDA)

        config = await db.voz_config.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
        conn = await _conexao(db, {**config, "tenant_id": tenant_id})
        if not conn:
            return await fim(FALHA, erro="Empresa sem conexão de WhatsApp")

        contato = await _contato(db, tenant_id, ligacao["numero"])
        modo = config.get("resposta_modo") if config.get("resposta_modo") in MODOS else "agente"
        session, _ = await outbound.ensure_session(
            db, tenant_id, conn["id"], contato,
            bot_id=config.get("bot_id") if modo == "bot" else None,
            departamento_id=conn.get("departamento_padrao_id"),
            origem="ligacao",
            resposta_modo="bot" if modo == "bot" else "aguardando",
            # A marca de primeira resposta é o que faz o robô escolhido dar a
            # partida, e o que segura a conversa na fila no modo `fila`. No modo
            # `agente` ela fica desligada: com ela, o caminho de entrada trataria
            # a resposta como resposta de disparo e não deixaria o agente atender.
            aguardar_primeira_resposta=modo in ("bot", "fila"),
        )
        # Liga a conversa à ligação, inclusive quando a conversa já existia: é
        # por esta marca que o caminho de entrada sabe que a próxima mensagem do
        # contato é a resposta a esta ligação (ver `marcar_resposta`).
        await db.conversation_sessions.update_one(
            {"id": session["id"], "tenant_id": tenant_id},
            {"$set": {"ligacao_id": ligacao_id, "updated_at": _now()}})
        await db.ligacoes.update_one(
            {"id": ligacao_id, "tenant_id": tenant_id},
            {"$set": {"contact_id": contato["id"], "session_id": session["id"]}})

        empresa = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1}) or {}
        valores = {"empresa": empresa.get("name") or "nossa empresa",
                   "numero": ligacao["numero"]}
        corpo = montar(texto(config, "mensagem"), valores)
        modelo = config.get("template") or {}

        # No canal não oficial, envios ativos da mesma conexão saem espaçados:
        # uma rajada de leads (ou de ligações) não vira uma rajada de mensagens.
        await aquecimento.espacar(conn)
        if flow_runtime.janela_aberta(session, conn.get("canal")):
            await flow_runtime.send_human_message(tenant_id, session["id"], corpo)
            return await fim(ENVIADA, mensagem_tipo="texto")
        if modelo.get("nome"):
            await flow_runtime.send_template_message(
                tenant_id, session["id"], modelo["nome"], modelo.get("idioma") or "pt_BR",
                [montar(v or "", valores).strip() or " " for v in (modelo.get("variaveis") or [])],
                corpo)
            return await fim(ENVIADA, mensagem_tipo="modelo")

        # Sem modelo a mensagem não chega a quem não falou com a empresa hoje.
        # O motivo fica no histórico da conversa, em vez de o contato que pediu
        # a mensagem simplesmente não receber nada sem explicação.
        await flow_runtime.log_message(
            db, session["id"], tenant_id, "sistema",
            "Mensagem da ligação não enviada: a janela de 24h desta conversa está "
            "fechada e não há modelo aprovado configurado em Configuração > Telefone.",
            mtype="system")
        return await fim(SEM_MODELO)
    except Exception as e:
        logger.warning("Ligação %s: falha ao mandar o WhatsApp: %s", ligacao_id, e)
        return await fim(FALHA, erro=str(e)[:300])


# ---------------------------------------------------------------------------
# Resposta do contato
# ---------------------------------------------------------------------------

async def marcar_resposta(db, tenant_id: str, session: dict) -> None:
    """A primeira mensagem do contato depois da ligação.

    É o número que diz se o recurso funciona: quantas ligações viraram
    conversa. A marca sai da conversa depois de usada, senão toda mensagem
    seguinte regravaria a resposta.
    """
    ligacao_id = session.get("ligacao_id")
    if not ligacao_id:
        return
    await db.ligacoes.update_one(
        {"id": ligacao_id, "tenant_id": tenant_id, "respondeu_em": None},
        {"$set": {"respondeu_em": _now(), "updated_at": _now()}})
    await db.conversation_sessions.update_one(
        {"id": session["id"], "tenant_id": tenant_id}, {"$set": {"ligacao_id": None}})
    session["ligacao_id"] = None


# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

# Teto de ligações lidas para o resumo. Um cliente com 300 ligações por mês
# fica três ordens de grandeza abaixo; acima disto a resposta diz que cortou.
MAX_RESUMO = 20000


async def resumo(db, tenant_id: str, de: str | None, ate: str | None) -> dict:
    """O funil da ligação: recebidas, pediram, receberam, responderam, agendaram.

    O corte do período vem do navegador (`de`/`ate`), como em atividades e
    relatórios: "este mês" depende do fuso de quem olha.
    """
    filtro: dict = {"tenant_id": tenant_id}
    if de or ate:
        filtro["created_at"] = {k: v for k, v in (("$gte", de), ("$lt", ate)) if v}
    docs = await db.ligacoes.find(
        filtro, {"_id": 0, "status": 1, "oculto": 1, "respondeu_em": 1,
                 "contact_id": 1, "created_at": 1},
    ).to_list(MAX_RESUMO)

    pediram = [d for d in docs if d.get("status") not in (RECEBIDA,)]
    enviadas = [d for d in docs if d.get("status") == ENVIADA]

    # Agendou = tem agendamento criado depois da ligação. Uma consulta só para
    # todos os contatos do período, não uma por ligação.
    primeira: dict[str, str] = {}
    for d in enviadas:
        cid = d.get("contact_id")
        if cid and (cid not in primeira or d["created_at"] < primeira[cid]):
            primeira[cid] = d["created_at"]
    agendaram = 0
    if primeira:
        async for a in db.appointments.find(
                {"tenant_id": tenant_id, "contact_id": {"$in": list(primeira)}},
                {"_id": 0, "contact_id": 1, "created_at": 1}):
            cid = a.get("contact_id")
            if cid in primeira and (a.get("created_at") or "") >= primeira[cid]:
                agendaram += 1
                primeira.pop(cid)  # um por contato

    return {
        "recebidas": len(docs),
        "ocultas": sum(1 for d in docs if d.get("oculto")),
        "pediram": len(pediram),
        "enviadas": len(enviadas),
        "repetidas": sum(1 for d in docs if d.get("status") == REPETIDA),
        "falhas": sum(1 for d in docs if d.get("status") in (FALHA, SEM_MODELO)),
        "responderam": sum(1 for d in enviadas if d.get("respondeu_em")),
        "agendaram": agendaram,
        "truncado": len(docs) >= MAX_RESUMO,
    }
