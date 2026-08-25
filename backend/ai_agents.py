"""O agente de IA que atende a conversa: configuração, prompt e handoff.

O prompt não é escrito pelo cliente num campo em branco — ninguém sabe escrever
um bom prompt de sistema, e um textarea vazio produz agente ruim. O que a
empresa escolhe são **peças** (tipo de agente, tom, tamanho da resposta, o que
não fazer), e `montar_instrucoes` costura tudo. Uma clínica e uma loja de peças
precisam de agentes diferentes, mas as duas sabem responder "é vendas ou é
suporte?".

**Vários agentes por empresa**, cada um amarrado a conexões de WhatsApp. Um
número de vendas e um de suporte precisam de agentes diferentes, e o schema já
suportava múltiplas conexões muito antes disto.

**Modo de atuação** decide o quanto o agente manda:

  - `desligado` — nunca responde.
  - `fallback` — responde só onde **nenhum bot** atenderia. É o padrão ao
    criar: encaixa nos dois pontos em que hoje a mensagem cai direto na fila
    humana, e por isso ligar um agente não muda o comportamento de nenhum
    fluxo já publicado.
  - `primeiro` — é a linha de frente das conversas novas; os fluxos continuam
    valendo quando o contato dispara um por palavra-chave.

**O handoff sai por sentinela, não por tool calling.** O agente é instruído a
responder exatamente `[HUMANO]` quando não deve resolver sozinho. Tool calling
seria mais robusto, mas tem formato diferente em cada provedor e dobraria o
`ai_client` para uma decisão binária. A sentinela funciona igual nos dois e é
conferida sobre o texto, que é o que sempre volta.

**Nada de silêncio.** Qualquer caminho de falha — provedor fora do ar, chave
sem saldo, teto do plano, agente confuso — termina com a conversa na fila
humana e a explicação no histórico. Mensagem de contato que não vira nem
resposta nem fila é venda perdida sem ninguém saber.
"""
import logging
import re
import unicodedata

from fastapi import HTTPException

import ai_runtime

logger = logging.getLogger("zappzen.ia")

MODO_DESLIGADO = "desligado"
MODO_FALLBACK = "fallback"
MODO_PRIMEIRO = "primeiro"
MODOS = (MODO_DESLIGADO, MODO_FALLBACK, MODO_PRIMEIRO)

# Resultado de `tentar_responder`, para quem chama saber o que aconteceu sem
# reinspecionar a sessão.
RESPONDEU = "respondeu"
ESCALOU = "escalou"

SENTINELA = "[HUMANO]"

# Quantas mensagens da conversa vão como contexto. Não é o histórico inteiro:
# a conversa cresce sem teto e cada turno reenviado é token pago de novo. 20
# cobre com folga o assunto corrente de um atendimento.
JANELA_HISTORICO = 20

# Teto de respostas do agente numa mesma conversa antes de entregar para
# alguém. É o freio de mão: um contato confuso e um agente prestativo
# conversam indefinidamente, e cada volta custa. Dúvida de atendimento que
# sobrevive a 10 respostas precisa de gente.
MAX_RESPOSTAS_PADRAO = 10


# ---------------------------------------------------------------------------
# Catálogo de escolhas — é o que a tela oferece e o que o prompt consome
# ---------------------------------------------------------------------------

# O tipo é a estratégia de base: define o que o agente está tentando fazer na
# conversa. Tudo o mais (tom, tamanho, restrições) é ajuste por cima disto.
TIPOS: dict[str, dict] = {
    "vendas": {
        "rotulo": "Vendas / Comercial",
        "descricao": "Apresenta produtos e serviços, qualifica o interesse e conduz até o fechamento.",
        "estrategia": (
            "Seu objetivo é vender. Entenda o que a pessoa procura, apresente o produto "
            "ou serviço adequado e conduza para o próximo passo concreto (orçamento, "
            "proposta ou fechamento). Faça uma pergunta de cada vez. Não seja insistente: "
            "se a pessoa disser que não tem interesse, agradeça e encerre com cordialidade."
        ),
    },
    "sdr": {
        "rotulo": "SDR / Prospecção",
        "descricao": "Faz o primeiro contato, qualifica o interesse e agenda com o time comercial.",
        "estrategia": (
            "Seu objetivo é qualificar e agendar, não vender. Descubra se a pessoa tem o "
            "perfil, a necessidade e o momento certo. Se tiver, conduza para agendar uma "
            "conversa com o time comercial. Se não tiver, agradeça e encerre sem insistir. "
            "Não discuta preço nem condição comercial — isso é da equipe."
        ),
    },
    "suporte": {
        "rotulo": "Suporte ao Cliente",
        "descricao": "Responde dúvidas, resolve problemas e escala para uma pessoa quando precisa.",
        "estrategia": (
            "Seu objetivo é resolver o problema da pessoa. Entenda primeiro o que está "
            "acontecendo antes de propor solução, e proponha uma coisa por vez. Se o "
            "problema não estiver coberto pela base de conhecimento, ou se a pessoa já "
            "estiver irritada, transfira em vez de tentar de novo."
        ),
    },
    "geral": {
        "rotulo": "Atendimento Geral",
        "descricao": "Recepciona, tira dúvidas simples e direciona o contato para o setor certo.",
        "estrategia": (
            "Seu objetivo é receber bem e direcionar. Descubra o que a pessoa precisa, "
            "responda o que for simples e direto, e encaminhe para o setor certo quando "
            "o assunto exigir. Não tente resolver o que é de outra área."
        ),
    },
    "agendamento": {
        "rotulo": "Agendamento",
        "descricao": "Coleta os dados para marcar reunião, consulta ou visita.",
        "estrategia": (
            "Seu objetivo é agendar. Colete o que for necessário para marcar (o que a "
            "pessoa precisa, preferência de dia e horário, e os dados de contato que "
            "faltarem), confirme tudo numa mensagem só ao final e transfira para a "
            "confirmação. Você não tem acesso à agenda: nunca confirme um horário como "
            "reservado, apenas registre a preferência."
        ),
    },
    "personalizado": {
        "rotulo": "Personalizado",
        "descricao": "Você define o objetivo do agente por escrito.",
        "estrategia": "",  # vem inteiro de `objetivo`
    },
}

# Tom é multi-seleção: "Profissional + Amigável" é uma combinação legítima e
# comum. Cada chave vira uma frase — o modelo responde melhor a descrição de
# comportamento do que a um adjetivo solto.
TONS: dict[str, dict] = {
    "profissional": {"rotulo": "Profissional", "frase": "profissional e competente, sem gírias"},
    "amigavel": {"rotulo": "Amigável", "frase": "caloroso e acolhedor, como quem gosta de ajudar"},
    "casual": {"rotulo": "Casual", "frase": "descontraído e informal, como uma conversa entre conhecidos"},
    "formal": {"rotulo": "Formal", "frase": "formal e cerimonioso, tratando por senhor ou senhora"},
    "consultivo": {"rotulo": "Consultivo", "frase": "consultivo: entenda antes de sugerir, e explique o porquê"},
    "empatico": {"rotulo": "Empático", "frase": "empático: reconheça o incômodo da pessoa antes de resolver"},
    "direto": {"rotulo": "Direto", "frase": "direto ao ponto, sem rodeio nem enrolação"},
}

# O tamanho vira instrução, e **não** um teto de tokens menor. Nos modelos
# GPT-5 o `max_output_tokens` inclui o raciocínio invisível: apertá-lo para
# forçar resposta curta faria o raciocínio consumir a cota inteira e devolver
# vazio. Quem encurta é o prompt.
TAMANHOS: dict[str, dict] = {
    "curtas": {"rotulo": "Curtas", "palavras": 15, "nota": "Respostas rápidas e objetivas"},
    "normais": {"rotulo": "Normais", "palavras": 25, "nota": "Equilibradas e informativas"},
    "detalhadas": {"rotulo": "Detalhadas", "palavras": 40, "nota": "Completas e explicativas"},
}

SEGMENTOS = [
    "Alimentação", "Automotivo", "Beleza e estética", "Construção e reforma",
    "Consultoria", "Educação", "E-commerce", "Eventos", "Financeiro",
    "Imobiliário", "Indústria", "Jurídico", "Moda e vestuário", "Pet",
    "Saúde", "Serviços em geral", "Tecnologia", "Turismo", "Outro",
]


def catalogo_publico() -> dict:
    """As escolhas como a tela precisa delas."""
    return {
        "tipos": [{"id": k, **{c: v[c] for c in ("rotulo", "descricao")}} for k, v in TIPOS.items()],
        "tons": [{"id": k, "rotulo": v["rotulo"]} for k, v in TONS.items()],
        "tamanhos": [{"id": k, **{c: v[c] for c in ("rotulo", "palavras", "nota")}}
                     for k, v in TAMANHOS.items()],
        "segmentos": SEGMENTOS,
        "modos": [
            {"id": MODO_FALLBACK, "rotulo": "Quando nenhum robô atender",
             "nota": "Mais seguro: não muda nenhum fluxo que já existe."},
            {"id": MODO_PRIMEIRO, "rotulo": "Na frente, em toda conversa nova",
             "nota": "O agente recebe primeiro; os robôs continuam valendo por palavra-chave."},
            {"id": MODO_DESLIGADO, "rotulo": "Desligado", "nota": "Não responde nada."},
        ],
    }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def montar_instrucoes(agente: dict) -> str:
    """O bloco estável que vai para o cache de prompt.

    Estável é requisito, não estilo: é o prefixo idêntico entre chamadas que o
    cache reconhece, e ele responde por ~80% dos tokens de entrada. Nada que
    varie por contato ou por horário entra aqui — isso vai no histórico, que
    varia de qualquer forma.
    """
    nome = (agente.get("nome") or "Assistente").strip()
    empresa = (agente.get("empresa_nome") or "").strip()
    partes = []

    cabecalho = f"Você é {nome}"
    if empresa:
        cabecalho += f", atendente virtual da {empresa}"
    cabecalho += ". Você conversa por WhatsApp com clientes e interessados."
    if agente.get("empresa_segmento"):
        cabecalho += f" A empresa atua em: {agente['empresa_segmento']}."
    partes.append(cabecalho)

    tipo = TIPOS.get(agente.get("tipo") or "geral", TIPOS["geral"])
    estrategia = tipo["estrategia"]
    if agente.get("tipo") == "personalizado":
        estrategia = (agente.get("objetivo") or "").strip()
    elif agente.get("objetivo"):
        # Objetivo escrito por cima de um tipo pronto complementa, não substitui.
        estrategia = f"{estrategia}\n{agente['objetivo'].strip()}"
    if estrategia:
        partes.append("Seu objetivo:\n" + estrategia)

    tons = [TONS[t]["frase"] for t in (agente.get("tom") or []) if t in TONS]
    tamanho = TAMANHOS.get(agente.get("tamanho") or "normais", TAMANHOS["normais"])
    estilo = [f"Escreva em português do Brasil, com cerca de {tamanho['palavras']} palavras por resposta."]
    if tons:
        estilo.append("Seu tom é " + ", ".join(tons) + ".")
    estilo.append(
        "É WhatsApp, não e-mail: sem saudação longa, sem assinatura, sem despedida "
        "a cada mensagem. Não use markdown, títulos nem listas numeradas — "
        "escreva como uma pessoa digitando no celular."
    )
    partes.append("Como escrever:\n" + " ".join(estilo))

    regras = [
        "Não invente informação. Se não estiver na base de conhecimento abaixo, você não sabe.",
        "Nunca prometa preço, prazo, desconto ou condição que não esteja escrito abaixo.",
        "Nunca peça senha, número de cartão ou dado bancário.",
        "Não repita o que a pessoa acabou de dizer antes de responder.",
    ]
    if agente.get("nao_fazer"):
        regras += [l.strip(" -•\t") for l in agente["nao_fazer"].strip().splitlines() if l.strip()]
    partes.append("Regras:\n" + "\n".join(f"- {r}" for r in regras))

    conhecimento = "\n\n".join(
        bloco.strip() for bloco in (
            agente.get("empresa_descricao"),
            agente.get("base_conhecimento"),
        ) if bloco and bloco.strip()
    )
    if conhecimento:
        partes.append(
            "Base de conhecimento — é a sua única fonte de fatos sobre a empresa:\n"
            + conhecimento
        )
    else:
        # Sem base, o modelo preenche a lacuna sozinho. Dizer isso explicitamente
        # é o que o impede de inventar horário de funcionamento e preço.
        partes.append(
            "Você não recebeu base de conhecimento sobre a empresa. Portanto você "
            "não sabe preço, horário, endereço, prazo nem detalhe de produto: "
            "transfira sempre que perguntarem qualquer um desses."
        )

    escalar = [
        "o contato pedir para falar com uma pessoa",
        "o assunto envolver reclamação, cancelamento ou cobrança",
        "a informação pedida não estiver na base de conhecimento",
        "o contato repetir a pergunta porque não foi entendido",
        "a pessoa demonstrar irritação",
    ]
    if agente.get("escalar_quando"):
        escalar += [l.strip(" -•\t") for l in agente["escalar_quando"].strip().splitlines() if l.strip()]
    partes.append(
        "Quando transferir para um atendente humano:\n"
        + "\n".join(f"- {e}" for e in escalar)
        + f"\n\nPara transferir, responda exatamente {SENTINELA} e mais nada. "
        f"Não se despeça e não avise que vai transferir: apenas {SENTINELA}. "
        "O sistema cuida de avisar o contato e chamar a pessoa certa."
    )
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# Seleção e histórico
# ---------------------------------------------------------------------------

async def agente_da_conexao(db, tenant_id: str, conexao_id: str | None) -> dict | None:
    """O agente que atende esta conexão, se houver um ligado.

    `conexoes` vazio significa "todas" — é o padrão, e evita que criar uma
    conexão nova de WhatsApp a deixe silenciosamente sem agente. Entre um
    agente específico daquela conexão e um genérico, ganha o específico: quem
    se deu ao trabalho de amarrar quis aquilo.
    """
    candidatos = await db.ai_agents.find(
        {"tenant_id": tenant_id, "ativo": True, "modo": {"$ne": MODO_DESLIGADO}}, {"_id": 0}
    ).sort("created_at", 1).to_list(50)
    generico = None
    for a in candidatos:
        conexoes = a.get("conexoes") or []
        if conexoes:
            if conexao_id in conexoes:
                return a
        elif generico is None:
            generico = a
    return generico


async def montar_historico(db, session_id: str, tenant_id: str,
                           contato: dict | None = None) -> list[dict]:
    """A conversa recente, no formato que os dois provedores aceitam.

    Ordena por `timestamp` **e `_id`** pelo mesmo motivo que todo histórico
    deste sistema: mensagens de uma mesma rajada nascem com timestamp idêntico,
    e sem o desempate a ordem fica indefinida — o que aqui trocaria a pergunta
    de lugar com a resposta.
    """
    docs = await db.messages_log.find(
        {"session_id": session_id, "tenant_id": tenant_id,
         "direction": {"$in": ["recebida", "enviada"]}},
        {"_id": 0, "direction": 1, "content": 1, "timestamp": 1},
    ).sort([("timestamp", -1), ("_id", -1)]).to_list(JANELA_HISTORICO)
    docs.reverse()

    historico: list[dict] = []
    for d in docs:
        conteudo = (d.get("content") or "").strip()
        if not conteudo:
            continue
        papel = "user" if d["direction"] == "recebida" else "assistant"
        # Turnos consecutivos do mesmo lado são unidos: no WhatsApp o contato
        # manda três mensagens seguidas o tempo todo, e os dois provedores
        # esperam papéis alternados.
        if historico and historico[-1]["role"] == papel:
            historico[-1]["content"] += "\n" + conteudo
        else:
            historico.append({"role": papel, "content": conteudo})

    # O contexto do contato entra grudado no primeiro turno da janela, e não
    # nas instruções, justamente para não quebrar o cache: as instruções
    # precisam ser idênticas entre contatos; o histórico varia de qualquer jeito.
    if historico and contato:
        rotulo = (contato.get("nome") or "").strip()
        if rotulo and historico[0]["role"] == "user":
            historico[0]["content"] = f"(nome do contato: {rotulo})\n{historico[0]['content']}"

    # A janela pode começar numa resposta nossa, se o corte caiu ali. Os dois
    # provedores exigem que o primeiro turno seja do usuário.
    while historico and historico[0]["role"] != "user":
        historico.pop(0)
    return historico


# ---------------------------------------------------------------------------
# Pedido explícito de gente
# ---------------------------------------------------------------------------

def _normaliza(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", texto.lower())


# Conferido antes de chamar o provedor: se o contato já disse que quer uma
# pessoa, gastar uma chamada para o modelo concluir o mesmo é desperdício — e
# devolver mais uma resposta automática a quem acabou de pedir um humano é o
# jeito mais rápido de irritar um cliente.
PEDIDOS_DE_HUMANO = (
    "atendente", "humano", "pessoa de verdade", "falar com alguem",
    "falar com uma pessoa", "quero uma pessoa", "me transfere", "me transfira",
    "quero falar com o vendedor", "chama alguem",
)


def pediu_humano(texto: str) -> bool:
    n = _normaliza(texto)
    return bool(n.strip()) and any(_normaliza(p) in n for p in PEDIDOS_DE_HUMANO)


# ---------------------------------------------------------------------------
# Atendimento
# ---------------------------------------------------------------------------

async def tentar_responder(db, agente: dict, session: dict, contato: dict,
                           texto: str, tem_midia: bool, outputs: list) -> str:
    """Responde a mensagem atual, ou decide que é caso de gente.

    Não levanta: devolve `ESCALOU` em qualquer falha, tendo deixado a
    explicação no histórico. Quem chama só precisa saber se deve mandar para a
    fila.

    Acrescenta a resposta em `outputs`, no mesmo formato dos nós de fluxo — o
    envio e o log já existentes cuidam do resto, e é isso que mantém a prévia
    da conversa correta sem um segundo caminho de escrita.
    """
    from flow_runtime import log_message  # tardio: flow_runtime importa este módulo

    tenant_id = session["tenant_id"]
    session_id = session["id"]

    async def escalar(motivo: str) -> str:
        await log_message(db, session_id, tenant_id, "sistema", motivo, mtype="system")
        return ESCALOU

    if texto and pediu_humano(texto):
        return await escalar("Contato pediu atendimento humano — encaminhado para a fila")

    # Anexo sem legenda: o agente é de texto e não recebe a imagem. Fingir que
    # entendeu é pior do que passar para alguém que consegue ver.
    if tem_midia and not (texto or "").strip():
        return await escalar("Anexo recebido sem texto — o agente de IA não analisa "
                             "arquivos, encaminhado para atendimento humano")
    if not (texto or "").strip():
        return await escalar("Mensagem sem texto — encaminhada para atendimento humano")

    teto = agente.get("max_respostas") or MAX_RESPOSTAS_PADRAO
    if session.get("ia_respostas", 0) >= teto:
        return await escalar(f"Agente de IA respondeu {teto} vezes sem resolver — "
                             "encaminhado para atendimento humano")

    historico = await montar_historico(db, session_id, tenant_id, contato)
    if not historico:
        return await escalar("Sem histórico utilizável para o agente de IA — "
                             "encaminhado para atendimento humano")

    try:
        resposta = await ai_runtime.responder_por_tenant(
            db, tenant_id, montar_instrucoes(agente), historico
        )
    except HTTPException as e:
        # Teto do plano ou nenhuma conta conectada. O detalhe já é texto para
        # leitura humana — é o que explica ao admin por que o agente parou.
        return await escalar(f"Agente de IA indisponível: {e.detail}")
    except Exception as e:
        logger.warning("Falha do agente de IA no tenant %s: %s", tenant_id, e)
        return await escalar(f"Agente de IA falhou ({e}) — encaminhado para atendimento humano")

    texto_resposta = (resposta.texto or "").strip()

    # Sentinela conferida por conteúdo, não por igualdade: o modelo às vezes
    # acrescenta pontuação ou uma linha em volta, e tratar isso como resposta
    # normal mandaria "[HUMANO]" para o contato.
    if SENTINELA.lower() in texto_resposta.lower():
        return await escalar("Agente de IA transferiu para atendimento humano")
    if not texto_resposta:
        return await escalar("Agente de IA respondeu vazio — encaminhado para atendimento humano")

    outputs.append({"type": "text", "content": texto_resposta})
    session["ia_respostas"] = session.get("ia_respostas", 0) + 1
    return RESPONDEU
