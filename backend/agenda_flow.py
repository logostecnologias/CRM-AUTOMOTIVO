"""O nó de Agendamento do editor de fluxos: uma conversa inteira dentro de um nó.

Marcar um horário são quatro perguntas (serviço, profissional, dia, hora) e uma
gravação. Montar isso com os nós que já existiam era impossível: o Menu precisa
das opções escritas à mão no editor, e aqui **as opções só existem no momento
do envio**: dependem do que está livre naquele minuto.

Decisões:

  - **Um nó, não quatro.** A alternativa seria um nó por pergunta, encadeados. O
    cliente teria de ligar as saídas de "que dia?" nas de "que hora?" sem saber
    quantas seriam, e um dia sem vaga deixaria o fluxo com uma ponta solta. As
    etapas vivem dentro do nó, em `awaiting`, e para quem monta o fluxo há só
    duas saídas: **agendou** e **não agendou**.

  - **As perguntas saem como Menu, pelo mesmo caminho de envio.** Cada etapa
    produz um output `{"type": "menu"}`: o mesmo que o nó de Menu produz, e é
    `flow_runtime._enviar_menu` que decide botões, lista ou texto numerado, com
    a mesma degradação. Um segundo caminho de envio significaria uma segunda
    chance de perder a pergunta.

  - **A escolha é resolvida por `flow_engine.resolver_escolha_menu`**, a mesma
    função do nó de Menu: id do botão primeiro, depois número e rótulo digitados.
    Duas regras de correspondência diferentes fariam o contato que digita "2"
    funcionar num menu e não no outro.

  - **Os rótulos são cortados na montagem, não deixados para a validação.** No
    nó de Menu o rótulo é digitado num campo com contador na tela e
    `validar_menu` recusa a publicação se passar do teto. Aqui o rótulo é o nome
    de um serviço cadastrado em outra tela; um "Corte + barba + hidratação" faria
    **todo** menu de agenda degradar para texto numerado. O nome inteiro vai na
    descrição da linha, que aceita 72 caracteres.

  - **Nada é gravado no chat de teste do editor.** O teste consulta a agenda de
    verdade (é o que prova que a grade está certa), mas `session["simulado"]`
    impede a marcação: testar um fluxo não pode ocupar o horário de um cliente.
"""
import logging

import agenda
import wuzapi_client as wuzapi
from db import get_db
from fastapi import HTTPException

logger = logging.getLogger("zappzen.agenda")

# Saídas do nó, como aparecem no editor.
SAIDA_OK = "agendado"
SAIDA_FALHA = "nao_agendado"

ETAPAS = ("servico", "profissional", "dia", "hora")

# Quantas vezes o contato pode responder qualquer coisa antes de o fluxo
# desistir e sair pela saída "não agendou". Sem teto, quem não entendeu a
# pergunta fica preso no nó para sempre, e ninguém na empresa fica sabendo.
MAX_TENTATIVAS = 3

# Quantas vezes tentar de novo quando o horário escolhido foi ocupado entre a
# pergunta e a resposta. Uma volta basta: a segunda lista já é recente.
MAX_CORRIDAS = 2

# Teto de opções no formato de texto numerado. O limite não é do WhatsApp, é de
# leitura: um dia cheio devolve até 40 horários, e quarenta linhas numeradas no
# celular fazem o contato desistir antes de escolher.
MAX_ITENS_TEXTO = 15

PADROES_TEXTO = {
    "texto_servico": "O que você gostaria de agendar?",
    "texto_profissional": "Com quem você prefere ser atendido?",
    "texto_dia": "Para qual dia?",
    "texto_hora": "E qual horário fica melhor?",
    "texto_sem_horario": ("No momento não encontrei horários disponíveis. "
                          "Vou passar você para um atendente."),
    "texto_confirmado": ("Prontinho! ✅\n\n*{servico}*\n🗓 {data_completa}\n👤 {profissional}"),
    "texto_invalido": "Não entendi. Escolha uma das opções abaixo:",
}


def texto_do_no(data: dict, chave: str) -> str:
    return (data.get(chave) or "").strip() or PADROES_TEXTO[chave]


# ---------------------------------------------------------------------------
# Montagem das perguntas
# ---------------------------------------------------------------------------

def _corta(texto: str, limite: int) -> str:
    """Corta e apara: o corte cai no meio de uma palavra quase sempre, e sobraria
    um espaço no fim do botão. É o mesmo detalhe do rótulo em `wuzapi_client`."""
    return (texto or "")[:limite].rstrip()


def _hora(iso: str, config: dict) -> str:
    """A hora de um instante, no fuso da empresa. "14:30"."""
    d = agenda.local(iso, agenda.fuso_de(config))
    return f"{d.hour:02d}:{d.minute:02d}"


def _menu(data: dict, session: dict, node_id: str, etapa: str, pergunta: str,
          itens: list, dados: dict, prefixo: str = "") -> dict:
    """A pergunta desta etapa, no formato de output do nó de Menu.

    Guarda em `awaiting` tudo que a resposta vai precisar: as opções (para
    `resolver_escolha_menu`), os rótulos (para a mensagem recebida ter texto
    quando o contato toca num botão, que volta sem rótulo) e o que já foi
    escolhido nas etapas anteriores.
    """
    formato = data.get("formato") or "lista"
    # O corte é por formato, e o de `texto` não vem do WhatsApp, e sim da
    # legibilidade.
    # Um dia cheio devolve até `agenda.MAX_HORARIOS_DIA` (40) horários, e uma
    # mensagem com quarenta linhas numeradas no celular não é uma pergunta, é um
    # muro. Oferecer os primeiros é melhor: o contato que quer outro horário
    # responde e o atendimento humano resolve.
    itens = itens[:{"lista": wuzapi.MAX_ITENS_LISTA,
                    "botoes": wuzapi.MAX_BOTOES}.get(formato, MAX_ITENS_TEXTO)]

    session["awaiting"] = {
        "node_id": node_id,
        "tipo": "agenda",
        "etapa": etapa,
        "opcoes": [{"id": i["id"], "label": i["label"]} for i in itens],
        "rotulos": {i["id"]: i["label"] for i in itens},
        "dados": dados,
        "tentativas": (session.get("awaiting") or {}).get("tentativas", 0),
    }
    corpo = f"{prefixo}\n\n{pergunta}".strip() if prefixo else pergunta
    return {
        "type": "menu",
        "content": corpo,
        "formato": formato,
        "titulo": "",
        "rodape": "",
        "botao_texto": (data.get("botao_texto") or "").strip() or "Ver opções",
        "titulo_secao": "",
        "options": [i["label"] for i in itens],
        "itens": itens,
        # Vazio sempre: os rótulos já foram cortados na montagem, e é justamente
        # o que impede a degradação para texto por causa de um nome comprido.
        "problemas": [],
    }


def _item_servico(s: dict) -> dict:
    partes = []
    if s.get("duracao_min"):
        partes.append(f"{s['duracao_min']} min")
    if s.get("preco"):
        partes.append(f"R$ {float(s['preco']):.2f}".replace(".", ","))
    descricao = " · ".join(partes)
    if s.get("descricao"):
        descricao = f"{descricao} · {s['descricao']}" if descricao else s["descricao"]
    return {"id": s["id"], "label": _corta(s["nome"], wuzapi.LIMITE_ROTULO_ITEM),
            "descricao": _corta(descricao, wuzapi.LIMITE_DESC_ITEM)}


# ---------------------------------------------------------------------------
# Motor do nó
# ---------------------------------------------------------------------------

async def avancar(node: dict, session: dict, outputs: list, *,
                  resposta: str = None, escolha_id: str = None) -> str:
    """Roda o nó a partir do ponto em que ele está. Devolve a saída, ou None
    quando ficou esperando resposta do contato.

    `resposta`/`escolha_id` chegam quando o contato respondeu a uma das
    perguntas; na primeira entrada no nó vêm vazios.
    """
    from flow_engine import resolver_escolha_menu  # tardio: flow_engine importa este módulo

    db = get_db()
    tenant_id = session.get("tenant_id")
    data = node.get("data") or {}
    if not tenant_id:
        return _falhar(session, outputs, data, "conversa sem empresa vinculada")

    config = await agenda.configuracao(db, tenant_id)
    estado = session.get("awaiting") or {}
    dados = dict(estado.get("dados") or {}) if estado.get("tipo") == "agenda" else {}
    etapa = estado.get("etapa") if estado.get("tipo") == "agenda" else None

    prefixo = ""
    # `escolha_id` sozinho também é resposta: quando o contato toca num botão, o
    # payload do WhatsApp chega com o id e **sem** texto. Exigir `resposta` faria
    # o nó reapresentar a mesma pergunta a cada toque, para sempre.
    if etapa and (resposta is not None or escolha_id is not None):
        escolhido = resolver_escolha_menu(estado.get("opcoes") or [],
                                          resposta or "", escolha_id)
        if escolhido is None:
            tentativas = int(estado.get("tentativas") or 0) + 1
            if tentativas >= MAX_TENTATIVAS:
                return _falhar(session, outputs, data,
                               "o contato não escolheu nenhuma das opções")
            session["awaiting"] = {**estado, "tentativas": tentativas}
            estado = session["awaiting"]
            prefixo = texto_do_no(data, "texto_invalido")
            # Repete a mesma etapa: `dados` não avança e o laço abaixo remonta a
            # pergunta com a lista recalculada: a agenda pode ter mudado desde
            # a primeira vez que ela saiu.
        else:
            dados[etapa] = escolhido
            session["awaiting"] = None

    # A partir daqui é sempre "qual a próxima pergunta que falta", nunca "qual
    # era a etapa anterior": o estado é o conjunto de escolhas já feitas, e cada
    # passagem preenche o que dá sozinha (serviço fixo no nó, profissional
    # único) sem gastar uma pergunta.
    return await _proxima_pergunta(db, tenant_id, node, session, outputs, data,
                                   config, dados, prefixo)


async def _proxima_pergunta(db, tenant_id, node, session, outputs, data, config,
                            dados, prefixo="") -> str:
    node_id = node["id"]

    # --- serviço ---------------------------------------------------------
    servico = None
    servico_id = dados.get("servico") or (data.get("service_id") or "").strip()
    servicos = await agenda.servicos_ativos(db, tenant_id)
    if not servicos:
        return _falhar(session, outputs, data, "nenhum serviço cadastrado na agenda")
    if servico_id:
        servico = next((s for s in servicos if s["id"] == servico_id), None)
        if not servico:
            # Serviço desativado ou apagado depois de o fluxo ser publicado.
            # Perguntar de novo é melhor que travar: as opções atuais existem.
            servico_id = None
    if not servico:
        if len(servicos) == 1:
            servico = servicos[0]
        else:
            outputs.append(_menu(data, session, node_id, "servico",
                                 texto_do_no(data, "texto_servico"),
                                 [_item_servico(s) for s in servicos], dados, prefixo))
            return None
    dados["servico"] = servico["id"]

    # --- profissional ----------------------------------------------------
    recursos = await agenda.recursos_ativos(db, tenant_id, servico)
    if not recursos:
        return _falhar(session, outputs, data,
                       f"nenhum profissional disponível para {servico['nome']}")

    modo = data.get("modo_profissional") or "qualquer"
    recurso = None
    recurso_id = dados.get("profissional") or (
        (data.get("resource_id") or "").strip() if modo == "fixo" else "")
    if recurso_id:
        recurso = next((r for r in recursos if r["id"] == recurso_id), None)
    if not recurso and modo == "perguntar" and len(recursos) > 1:
        itens = [{"id": r["id"], "label": _corta(r["nome"], wuzapi.LIMITE_ROTULO_ITEM),
                  "descricao": _corta(r.get("descricao") or "", wuzapi.LIMITE_DESC_ITEM)}
                 for r in recursos]
        outputs.append(_menu(data, session, node_id, "profissional",
                             texto_do_no(data, "texto_profissional"), itens, dados, prefixo))
        return None
    if not recurso and (modo == "perguntar" or modo == "fixo"):
        # "Perguntar" com um profissional só, ou "fixo" cujo profissional saiu
        # do ar: não vale gastar uma pergunta com uma opção única.
        recurso = recursos[0]
    if recurso:
        dados["profissional"] = recurso["id"]
    # No modo `qualquer` o profissional sai do próprio horário escolhido
    # `horarios_do_dia` já devolve quem atende cada hora.
    candidatos = [recurso] if recurso else recursos

    # --- dia -------------------------------------------------------------
    dia = dados.get("dia")
    if not dia:
        limite = max(1, min(int(data.get("dias_oferecidos") or 5), wuzapi.MAX_ITENS_LISTA))
        dias = await agenda.proximos_dias(db, tenant_id, recursos=candidatos,
                                          servico=servico, config=config,
                                          limite_dias=limite)
        if not dias:
            return _falhar(session, outputs, data, "sem horários livres na agenda")
        # A descrição diz a primeira hora do dia, e **não** quantas vagas
        # sobraram. O WhatsApp repete a linha escolhida como se o contato a
        # tivesse dito, então "5 horários livres" vira uma mensagem dele
        # contando à empresa o quanto a agenda está vazia. Fora ser ruído, é
        # informação de dentro da casa: numa agenda cheia some, numa vazia
        # denuncia. "A partir das 14:30" ajuda a escolher e não conta nada.
        itens = [{"id": d["dia"], "label": _corta(d["rotulo"], wuzapi.LIMITE_ROTULO_ITEM),
                  "descricao": f"a partir das {_hora(d['primeiro'], config)}"}
                 for d in dias]
        outputs.append(_menu(data, session, node_id, "dia",
                             texto_do_no(data, "texto_dia"), itens, dados, prefixo))
        return None

    # --- hora ------------------------------------------------------------
    horarios = await agenda.horarios_do_dia(db, tenant_id, recursos=candidatos,
                                            servico=servico, dia=dia, config=config)
    hora = dados.get("hora")
    if hora:
        escolhido = next((h for h in horarios if h["inicio"] == hora), None)
        if escolhido:
            return await _marcar(db, tenant_id, node, session, outputs, data, config,
                                 servico, escolhido, dados)
        # O horário sumiu entre a pergunta e a resposta: outra conversa marcou
        # primeiro. Recomeça pelo mesmo dia com a lista nova, uma vez.
        dados.pop("hora", None)
        corridas = int(dados.get("corridas") or 0) + 1
        dados["corridas"] = corridas
        if corridas > MAX_CORRIDAS:
            return _falhar(session, outputs, data, "o horário escolhido foi ocupado")
        prefixo = "Esse horário acabou de ser ocupado."

    if not horarios:
        # Dia esvaziou depois de escolhido: volta a perguntar o dia em vez de
        # desistir: a agenda tem outros dias, e o contato já disse o que quer.
        dados.pop("dia", None)
        return await _proxima_pergunta(db, tenant_id, node, session, outputs, data,
                                       config, dados,
                                       prefixo or "Esse dia acabou de lotar.")

    # O nome de quem atende só entra quando há mais de um: com um profissional
    # só, repetir o mesmo nome embaixo de cada hora é ruído, e o contato ainda
    # o vê repetido na mensagem que o WhatsApp devolve por ele.
    varios = len({h.get("resource_id") for h in horarios}) > 1
    itens = [{"id": h["inicio"], "label": h["hora"],
              "descricao": _corta(h.get("resource_nome") or "", wuzapi.LIMITE_DESC_ITEM)
                           if varios else ""}
             for h in horarios]
    outputs.append(_menu(data, session, node_id, "hora",
                         texto_do_no(data, "texto_hora"), itens, dados, prefixo))
    return None


async def _marcar(db, tenant_id, node, session, outputs, data, config, servico,
                  horario, dados) -> str:
    """Grava o agendamento e devolve a saída de sucesso.

    Recebe o `node` inteiro (e não só `data`) porque o caminho de corrida perdida
    volta a perguntar, e a pergunta grava `awaiting.node_id`. Remontar o nó a
    partir da sessão não serviria: `node_atual_id` ainda aponta para o nó
    anterior enquanto este está sendo processado, e a resposta do contato voltaria
    para o lugar errado do fluxo.
    """
    import agenda_worker

    recurso = await db.resources.find_one(
        {"id": horario["resource_id"], "tenant_id": tenant_id}, {"_id": 0})
    if not recurso:
        return _falhar(session, outputs, data, "profissional indisponível")

    if session.get("simulado"):
        # Chat de teste do editor: a agenda foi consultada de verdade (é o que
        # prova a grade), mas nada é gravado: um teste não pode ocupar o
        # horário de um cliente real.
        doc = {"id": "teste", "service_nome": servico["nome"],
               "resource_nome": recurso["nome"], "inicio": horario["inicio"],
               "fim": horario["fim"], "duracao_min": servico.get("duracao_min"),
               "contact_nome": session.get("variables", {}).get("nome_contato")}
        outputs.append({"type": "system", "content":
                        "(simulação: nada foi gravado na agenda)"})
    else:
        contato = await db.contacts.find_one(
            {"id": session.get("contact_id"), "tenant_id": tenant_id}, {"_id": 0})
        if not contato:
            return _falhar(session, outputs, data, "contato não encontrado")
        try:
            doc = await agenda.agendar(
                db, tenant_id, recurso=recurso, servico=servico, contato=contato,
                inicio=horario["inicio"], config=config, origem="bot",
                session_id=session.get("id"),
                connection_id=session.get("whatsapp_connection_id"),
            )
        except HTTPException as e:
            # Perdeu a corrida na gravação (ver `agenda.agendar`). Volta para a
            # lista de horários daquele dia em vez de derrubar a conversa.
            dados.pop("hora", None)
            dados["corridas"] = int(dados.get("corridas") or 0) + 1
            if dados["corridas"] > MAX_CORRIDAS:
                return _falhar(session, outputs, data, str(e.detail))
            return await _proxima_pergunta(db, tenant_id, node, session, outputs,
                                           data, config, dados, str(e.detail))

    session["awaiting"] = None
    _variaveis(session, doc, config)
    outputs.append({"type": "text",
                    "content": agenda_worker.montar(
                        texto_do_no(data, "texto_confirmado"), doc, config)})
    return SAIDA_OK


def _variaveis(session: dict, doc: dict, config: dict):
    """Deixa o agendamento acessível aos nós seguintes do fluxo.

    É o que permite um nó de Mensagem depois do agendamento dizer "te espero
    {agendamento_data}" sem que o cliente precise reescrever o texto de
    confirmação dentro do nó.
    """
    tz = agenda.fuso_de(config)
    session.setdefault("variables", {}).update({
        "agendamento_id": doc.get("id"),
        "agendamento_servico": doc.get("service_nome"),
        "agendamento_profissional": doc.get("resource_nome"),
        "agendamento_data": agenda.rotulo_completo(doc["inicio"], tz),
        "agendamento_hora": agenda.rotulo(doc["inicio"], tz),
    })


def _falhar(session: dict, outputs: list, data: dict, motivo: str) -> str:
    """Sai pela saída "não agendou", com o motivo à vista.

    O motivo vai para o histórico como mensagem de sistema, não para o contato:
    "nenhum serviço cadastrado na agenda" é um recado para a empresa. O contato
    recebe o texto configurado no nó, que fala a língua dele.
    """
    session["awaiting"] = None
    session.setdefault("variables", {})["agendamento_falha"] = motivo
    outputs.append({"type": "text", "content": texto_do_no(data, "texto_sem_horario")})
    outputs.append({"type": "system", "content": f"Agendamento não concluído: {motivo}"})
    return SAIDA_FALHA


# ---------------------------------------------------------------------------
# Validação na publicação
# ---------------------------------------------------------------------------

def validar(data: dict) -> list:
    """Problemas que impediriam o nó de funcionar num fluxo publicado.

    Não confere se existe serviço cadastrado: o fluxo é publicado uma vez e a
    agenda muda todo dia, então isso viraria uma barreira que reprova hoje o que
    aprovou ontem. A falta de serviço é tratada em tempo de execução, pela saída
    "não agendou", que é o caminho que a empresa configura para esse caso.
    """
    problemas = []
    modo = data.get("modo_profissional") or "qualquer"
    if modo not in ("qualquer", "perguntar", "fixo"):
        problemas.append(f"modo de escolha de profissional desconhecido: {modo}")
    if modo == "fixo" and not (data.get("resource_id") or "").strip():
        problemas.append("o modo \"profissional fixo\" exige escolher qual profissional")
    dias = data.get("dias_oferecidos")
    if dias is not None and not (1 <= int(dias or 0) <= wuzapi.MAX_ITENS_LISTA):
        problemas.append(f"o nó pode oferecer de 1 a {wuzapi.MAX_ITENS_LISTA} dias")
    formato = data.get("formato") or "lista"
    if formato not in ("lista", "botoes", "texto"):
        problemas.append(f"formato de apresentação desconhecido: {formato}")
    if formato == "botoes":
        # Três botões não comportam uma lista de horários, e a degradação para
        # texto aconteceria em quase toda pergunta: o cliente veria o formato
        # configurado nunca sair.
        problemas.append("agendamento não cabe em botões (no máximo 3): "
                         "use Lista de opções ou Texto numerado")
    return problemas
