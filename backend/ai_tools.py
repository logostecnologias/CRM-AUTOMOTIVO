"""As ferramentas de agenda do agente de IA: consultar horários, marcar, cancelar.

Até aqui o agente só conversava. Ele podia descrever o serviço, o preço e o
horário de funcionamento, mas na hora de marcar transferia para uma pessoa: e
é justamente a marcação que o cliente queria automatizar. Com estas três
ferramentas ele fecha o ciclo sozinho.

Decisões:

  - **Os argumentos são nomes e horas de parede, não ids nem ISO.** No catálogo
    de fotos o identificador é um índice curto (`[FOTO:3]`) porque a etiqueta
    aparece **no meio do texto** que o modelo escreve, onde cada caractere é
    token pago e um uuid errado no meio de uma frase é fácil. Aqui é diferente:
    o argumento vai num campo estruturado, o modelo já tem o nome exato do
    serviço nas instruções, e `dia="2026-09-01", hora="14:00"` é o que ele já
    raciocina ("sexta às duas"). Pedir `2026-09-01T14:00:00-03:00` seria pedir
    para ele acertar um deslocamento de fuso que nem precisa conhecer: o fuso é
    da empresa e está gravado.

  - **Nome não encontrado devolve a lista dos que existem.** O modelo se
    recupera de "não achei 'corte simples'; temos: Corte masculino, Corte
    feminino" perguntando ao contato; devolver só "erro" o faria transferir.

  - **A ferramenta nunca levanta para o provedor.** `ai_client._rodar_ferramenta`
    já converte exceção em texto, mas os erros previsíveis (horário ocupado,
    antecedência) são formulados aqui, em português e com o que fazer a seguir
    porque é esse texto que vira a fala do agente.

  - **Marcar exige que o horário tenha sido consultado?** Não. O modelo pode
    chamar `agendar` direto quando o contato disse "quero sexta às 14h", e a
    checagem de disponibilidade acontece na gravação de qualquer jeito
    (`agenda.agendar` valida grade, antecedência e conflito). Exigir a consulta
    antes seria uma regra que o modelo esqueceria, trocando um agendamento por
    uma transferência.

  - **Cancelar age sobre os agendamentos futuros daquele contato**, nunca sobre
    um id que o modelo tenha escrito. Um id inventado num campo de ferramenta
    cancelaria a consulta de outra pessoa: este é o único lugar do módulo em
    que o modelo poderia causar dano fora da conversa dele.
"""
import logging
import re
import unicodedata

import agenda
import ai_client
from fastapi import HTTPException

logger = logging.getLogger("zappzen.ia")

FERRAMENTAS = [
    ai_client.Ferramenta(
        nome="consultar_horarios",
        descricao=(
            "Consulta os horários livres da agenda da empresa. Use SEMPRE antes de "
            "prometer qualquer horário: você não sabe o que está livre sem chamar "
            "isto. Sem o parâmetro 'dia', devolve os próximos dias que têm vaga."
        ),
        parametros={
            "type": "object",
            "properties": {
                "servico": {"type": "string",
                            "description": "Nome do serviço, exatamente como está na lista de serviços."},
                "dia": {"type": "string",
                        "description": "Dia no formato AAAA-MM-DD. Omita para ver os próximos dias com vaga."},
                "profissional": {"type": "string",
                                 "description": "Nome do profissional, se o contato pediu alguém específico."},
            },
            "required": ["servico"],
        },
    ),
    ai_client.Ferramenta(
        nome="agendar",
        descricao=(
            "Marca o horário na agenda de verdade. Só chame depois que o contato "
            "confirmou o dia e a hora. Depois de marcar, confirme ao contato o que "
            "a ferramenta devolveu."
        ),
        parametros={
            "type": "object",
            "properties": {
                "servico": {"type": "string", "description": "Nome do serviço."},
                "dia": {"type": "string", "description": "Dia no formato AAAA-MM-DD."},
                "hora": {"type": "string", "description": "Hora no formato HH:MM (horário local da empresa)."},
                "profissional": {"type": "string",
                                 "description": "Nome do profissional. Omita para a empresa escolher quem estiver livre."},
                "observacao": {"type": "string",
                               "description": "Algo relevante que o contato disse sobre o atendimento."},
            },
            "required": ["servico", "dia", "hora"],
        },
    ),
    ai_client.Ferramenta(
        nome="cancelar_agendamento",
        descricao=(
            "Cancela um horário já marcado deste contato. Chame quando ele pedir "
            "para desmarcar. Se ele tiver mais de um horário futuro, a ferramenta "
            "devolve a lista para você perguntar qual."
        ),
        parametros={
            "type": "object",
            "properties": {
                "dia": {"type": "string",
                        "description": "AAAA-MM-DD do horário a cancelar. Só é necessário se o contato tiver mais de um."},
                "motivo": {"type": "string", "description": "Motivo, se o contato disser."},
            },
            "required": [],
        },
    ),
]


# ---------------------------------------------------------------------------
# Casamento de nome
# ---------------------------------------------------------------------------

def _normaliza(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", texto.lower())).strip()


def _casar(nome: str, itens: list) -> dict:
    """Acha o item pelo nome. Igualdade normalizada primeiro, depois contido.

    O "contido" cobre o caso real: as instruções dizem "Corte masculino" e o
    modelo escreve "corte". Não cobre o inverso de forma perigosa, porque a lista
    é curta e do próprio cliente, e um empate devolve o primeiro, que numa lista
    ordenada por nome é estável.
    """
    alvo = _normaliza(nome)
    if not alvo:
        return None
    for i in itens:
        if _normaliza(i.get("nome")) == alvo:
            return i
    for i in itens:
        n = _normaliza(i.get("nome"))
        if n and (alvo in n or n in alvo):
            return i
    return None


def _lista(itens: list) -> str:
    return ", ".join(i.get("nome") or "?" for i in itens) or "(nenhum)"


# ---------------------------------------------------------------------------
# Catálogo para as instruções
# ---------------------------------------------------------------------------

def bloco_de_instrucoes(servicos: list, recursos: list, config: dict) -> str:
    """O que o modelo precisa saber da agenda, no bloco estável do prompt.

    Vai nas instruções, que são o prefixo cacheado, e não numa ferramenta
    `listar_servicos`, pelo mesmo motivo do catálogo de fotos: é informação
    curta, idêntica em toda chamada, e uma volta de ferramenta para buscá-la
    custaria uma chamada inteira ao provedor por conversa.

    Nada aqui varia por contato, que é a condição para o cache pegar.
    """
    linhas = ["Agenda: você pode consultar horários e marcar de verdade."]

    if servicos:
        linhas.append("\nServiços que a empresa agenda (use o nome exato):")
        for s in servicos:
            detalhe = f"{s.get('duracao_min')} min"
            if s.get("preco"):
                detalhe += f", R$ {float(s['preco']):.2f}".replace(".", ",")
            linha = f"- {s['nome']} ({detalhe})"
            if s.get("descricao"):
                linha += f": {s['descricao']}"
            linhas.append(linha)
    else:
        linhas.append("\nNenhum serviço cadastrado, não prometa agendamento.")

    if recursos:
        linhas.append("\nProfissionais: " + ", ".join(r["nome"] for r in recursos))
        linhas.append("Se o contato não pedir ninguém específico, não pergunte: "
                      "omita o profissional e a empresa escolhe quem estiver livre.")

    linhas.append(
        f"\nO fuso da empresa é {config.get('fuso')}; use sempre a hora local dela. "
        f"É preciso marcar com pelo menos {config.get('antecedencia_min_horas')}h de "
        "antecedência.\n"
        "Nunca invente horário: chame consultar_horarios antes de oferecer qualquer "
        "hora, e ofereça no máximo três de uma vez. Nunca diga que marcou sem que a "
        "ferramenta agendar tenha confirmado."
    )
    # A ferramenta devolve quantos horários sobraram porque isso ajuda o modelo a
    # escolher um dia folgado. Repetir o número ao contato é outra coisa: conta a
    # ele o quanto a agenda está vazia, que é informação de dentro da casa.
    linhas.append(
        "A quantidade de horários livres é para você se orientar, não para contar "
        "ao contato: ofereça as horas, nunca quantas sobraram."
    )
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def executor(db, tenant_id: str, contato: dict, session: dict, simulado: bool = False):
    """Devolve o `async (nome, argumentos) -> str` que o `ai_client` chama.

    Fechado sobre a conversa: o contato e a conexão saem daqui, nunca de um
    argumento do modelo. É o que impede uma ferramenta de marcar ou cancelar
    para outra pessoa.

    `simulado` é o chat de teste da tela de agentes, e segue a mesma regra do
    `session["simulado"]` do editor de fluxos: a **consulta** roda de verdade
    (é ela que prova que a grade e os serviços estão certos) e a **escrita**
    não acontece. Testar um agente não pode ocupar o horário de um cliente nem
    cancelar o de outro.
    """

    async def _catalogo(nome_servico: str):
        """O serviço pedido, ou o texto que o modelo mostra ao contato.

        Não busca os profissionais: quem precisa deles é `_recursos_de`, que
        roda logo em seguida em todas as chamadas: buscar aqui também custaria
        uma consulta a mais por ferramenta executada, sem ninguém usar.
        """
        servicos = await agenda.servicos_ativos(db, tenant_id)
        if not servicos:
            return None, "A empresa ainda não cadastrou serviços agendáveis."
        servico = _casar(nome_servico, servicos)
        if not servico:
            return None, (f"Não existe serviço com esse nome. Os serviços são: "
                          f"{_lista(servicos)}.")
        return servico, None

    async def _recursos_de(servico, nome_profissional):
        todos = await agenda.recursos_ativos(db, tenant_id, servico)
        if not todos:
            return None, f"Nenhum profissional atende {servico['nome']} no momento."
        if not (nome_profissional or "").strip():
            return todos, None
        escolhido = _casar(nome_profissional, todos)
        if not escolhido:
            return None, (f"Não temos ninguém com esse nome atendendo {servico['nome']}. "
                          f"Quem atende: {_lista(todos)}.")
        return [escolhido], None

    async def consultar_horarios(args):
        servico, erro = await _catalogo(args.get("servico"))
        if erro:
            return erro
        recursos, erro = await _recursos_de(servico, args.get("profissional"))
        if erro:
            return erro
        config = await agenda.configuracao(db, tenant_id)
        tz = agenda.fuso_de(config)

        dia = (args.get("dia") or "").strip()
        if not dia:
            dias = await agenda.proximos_dias(db, tenant_id, recursos=recursos,
                                              servico=servico, config=config,
                                              limite_dias=5)
            if not dias:
                return (f"Não há nenhum horário livre para {servico['nome']} nos "
                        "próximos dias. Ofereça avisar quando abrir vaga, ou "
                        "transfira para um atendente.")
            return ("Próximos dias com vaga para " + servico["nome"] + ": "
                    + "; ".join(f"{d['dia']} ({d['rotulo']}, {d['vagas']} horários)"
                                for d in dias)
                    + ". Chame de novo com o dia escolhido para ver as horas.")

        try:
            horarios = await agenda.horarios_do_dia(db, tenant_id, recursos=recursos,
                                                    servico=servico, dia=dia, config=config)
        except HTTPException as e:
            return f"ERRO: {e.detail}"
        if not horarios:
            proximos = await agenda.proximos_dias(
                db, tenant_id, recursos=recursos, servico=servico, config=config,
                a_partir_de=dia, limite_dias=3)
            if not proximos:
                return f"Não há horário livre em {dia} nem nos dias seguintes."
            return (f"Nada livre em {dia}. Os próximos dias com vaga são: "
                    + "; ".join(f"{d['dia']} ({d['rotulo']})" for d in proximos) + ".")
        return (f"Horários livres em {dia} para {servico['nome']} "
                f"({servico.get('duracao_min')} min): "
                + ", ".join(f"{h['hora']} com {h['resource_nome']}" for h in horarios)
                + f". Fuso: {tz}.")

    async def agendar_tool(args):
        servico, erro = await _catalogo(args.get("servico"))
        if erro:
            return erro
        recursos, erro = await _recursos_de(servico, args.get("profissional"))
        if erro:
            return erro
        config = await agenda.configuracao(db, tenant_id)
        tz = agenda.fuso_de(config)

        dia, hora = (args.get("dia") or "").strip(), (args.get("hora") or "").strip()
        if not dia or not hora:
            return "ERRO: informe dia (AAAA-MM-DD) e hora (HH:MM)."
        try:
            inicio = agenda._combina(agenda._dia(dia), agenda._hhmm(hora), tz)
        except HTTPException as e:
            return f"ERRO: {e.detail}"

        # Quem atende: entre os candidatos, o primeiro que tiver aquela hora
        # livre. Com profissional pedido pelo contato a lista tem um só, então a
        # regra é a mesma nos dois casos.
        alvo = agenda._iso(inicio)
        livres = await agenda.horarios_do_dia(db, tenant_id, recursos=recursos,
                                              servico=servico, dia=dia, config=config)
        escolhido = next((h for h in livres if h["inicio"] == alvo), None)
        if not escolhido:
            if not livres:
                return (f"{hora} de {dia} não está disponível e o dia não tem mais "
                        "nenhum horário. Consulte outro dia.")
            return (f"{hora} não está disponível em {dia}. O que resta nesse dia: "
                    + ", ".join(h["hora"] for h in livres[:8])
                    + ". Ofereça um destes ao contato.")

        recurso = next((r for r in recursos if r["id"] == escolhido["resource_id"]), None)
        if simulado:
            return ("MARCADO (simulação: nada foi gravado). Confirme ao contato: "
                    f"{servico['nome']}, "
                    f"{agenda.rotulo_completo(escolhido['inicio'], tz)}, "
                    f"com {escolhido['resource_nome']}.")
        try:
            doc = await agenda.agendar(
                db, tenant_id, recurso=recurso, servico=servico, contato=contato,
                inicio=escolhido["inicio"], config=config, origem="ia",
                session_id=(session or {}).get("id"),
                connection_id=(session or {}).get("whatsapp_connection_id"),
                observacoes=args.get("observacao"),
            )
        except HTTPException as e:
            return f"NÃO FOI MARCADO: {e.detail}"

        return ("MARCADO com sucesso. Confirme ao contato: "
                f"{servico['nome']}, {agenda.rotulo_completo(doc['inicio'], tz)}, "
                f"com {doc['resource_nome']}.")

    async def cancelar_tool(args):
        futuros = await agenda.agendamentos_do_contato(db, tenant_id, contato["id"])
        if not futuros:
            return "Este contato não tem nenhum horário marcado para cancelar."
        config = await agenda.configuracao(db, tenant_id)
        tz = agenda.fuso_de(config)

        alvo = futuros[0]
        dia = (args.get("dia") or "").strip()
        if len(futuros) > 1:
            candidatos = [a for a in futuros if a["inicio"][:10] == dia] if dia else []
            if len(candidatos) != 1:
                return ("Este contato tem mais de um horário marcado: "
                        + "; ".join(f"{a['service_nome']} em "
                                    f"{agenda.rotulo_completo(a['inicio'], tz)} "
                                    f"(dia {a['inicio'][:10]})" for a in futuros)
                        + ". Pergunte qual ele quer cancelar e chame de novo com o dia.")
            alvo = candidatos[0]
        elif dia and futuros[0]["inicio"][:10] != dia:
            return (f"O único horário marcado é em {futuros[0]['inicio'][:10]}, não em "
                    f"{dia}. Confirme com o contato.")

        if simulado:
            return ("CANCELADO (simulação: nada foi gravado). O horário seria o de "
                    f"{agenda.rotulo_completo(alvo['inicio'], tz)}.")
        try:
            await agenda.cancelar(db, tenant_id, alvo["id"], por="ia",
                                  motivo=args.get("motivo") or "Cancelado pelo contato")
        except HTTPException as e:
            return f"NÃO FOI CANCELADO: {e.detail}"
        return ("CANCELADO. Confirme ao contato que o horário de "
                f"{agenda.rotulo_completo(alvo['inicio'], tz)} foi desmarcado.")

    acoes = {
        "consultar_horarios": consultar_horarios,
        "agendar": agendar_tool,
        "cancelar_agendamento": cancelar_tool,
    }

    async def executar(nome: str, argumentos: dict) -> str:
        acao = acoes.get(nome)
        if not acao:
            return f"ERRO: ferramenta desconhecida ({nome})."
        return await acao(argumentos or {})

    return executar
