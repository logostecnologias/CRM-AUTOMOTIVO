"""O agente de IA conduzindo o lead pelo funil.

Até aqui o negócio só existia se alguém da equipe o criasse à mão, e a etapa
só andava quando alguém arrastava o cartão. Numa operação em que o agente
conversa com todo mundo primeiro, o funil ficava vazio justamente na parte que
o agente conhece melhor: quem chegou, quem recebeu preço, quem está decidindo.

Decisões:

  - **Um negócio aberto por contato, no funil escolhido.** O agente cria o
    negócio na primeira vez que registra algo e depois só o atualiza. É a mesma
    regra do formulário de site: dois cartões para a mesma pessoa dividiriam o
    histórico e contariam o lead em dobro.

  - **Só etapas em aberto, e só para a frente.** Ganho e Perdido fecham o
    negócio e entram na receita do relatório: quem decide isso é a equipe, que
    sabe se o dinheiro entrou. E o agente nunca volta etapa: se um vendedor já
    levou o cartão para "Negociação", uma resposta do agente não pode puxá-lo
    de volta para "Contato feito". Voltar é decisão de gente.

  - **As etapas são uma lista fechada (`enum`) na ferramenta**, pelo nome.
    O modelo escolhe entre os nomes que existem em vez de escrever um parecido,
    e o nome é o que ele já raciocina. Mesmo motivo dos nomes de serviço em
    `ai_tools`, em vez de ids.

  - **Os dados do contato só preenchem o que está vazio.** O contato diz o
    e-mail na conversa, e é bom que ele vá para a ficha; mas o que a equipe
    escreveu ali vale mais do que o que o modelo entendeu.

  - **Quando mover é a empresa que ensina**, pela tela de treino. As etapas
    variam de cliente para cliente e os nomes já dizem quase tudo; o que não
    disserem ("mova para Proposta quando mandar a tabela") é ensinamento.

  - **Desligado por padrão**, como a agenda e o finalizar: é o agente
    escrevendo no sistema.
"""
import logging
import re
import uuid
from datetime import datetime, timezone

import ai_client
import deals

logger = logging.getLogger("zappzen.ai_funil")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Campos da ficha que o agente pode preencher. Só texto curto que o contato
# diz na conversa; responsável, etiquetas e origem são da equipe.
CAMPOS_CONTATO = ("nome", "email", "empresa", "cargo")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def funil_do_agente(db, tenant_id: str, agente: dict) -> dict | None:
    """O funil escolhido no agente, ou o primeiro da empresa.

    Funil apagado depois de escolhido cai no primeiro em vez de desligar o
    poder em silêncio: o cliente ligou "mover no funil", e é isso que ele espera
    ver acontecendo.
    """
    funis = await deals.funis_da_empresa(db, tenant_id)
    escolhido = agente.get("funil_id")
    for f in funis:
        if f["id"] == escolhido:
            return f
    return funis[0] if funis else None


def etapas_abertas(funil: dict) -> list[dict]:
    return [e for e in deals.etapas_em_ordem(funil) if e.get("tipo", "aberta") == "aberta"]


def bloco_de_instrucoes(funil: dict) -> str:
    """Vai no prompt (prefixo cacheado): igual para todo contato do agente."""
    abertas = etapas_abertas(funil)
    linhas = "\n".join(f"{i + 1}. {e['nome']}" for i, e in enumerate(abertas))
    return (
        f"Funil de vendas: cada contato tem um negócio no funil \"{funil['nome']}\", "
        "que mostra à equipe em que ponto a conversa está. As etapas, na ordem:\n"
        f"{linhas}\n\n"
        "Use atualizar_negocio para registrar o avanço:\n"
        "- Mova para a etapa que descreve onde a conversa está agora, assim que ela "
        "chegar lá, sem esperar o fim do atendimento. Siga o que a empresa ensinou "
        "sobre quando mover.\n"
        "- Só avance. Você nunca volta etapa, nunca marca venda ganha nem perdida: "
        "isso é da equipe.\n"
        "- Quando o contato disser o que quer, registre um título curto (o produto "
        "ou serviço de interesse) e, se o preço for conhecido, o valor.\n"
        "- Quando o contato disser o nome, o e-mail, a empresa ou o cargo, registre "
        "também.\n"
        "- Chame só quando algo mudar, não a cada mensagem. Nunca fale com o contato "
        "sobre funil, etapa ou negócio: isso é interno."
    )


def _ferramentas(funil: dict) -> list:
    nomes = [e["nome"] for e in etapas_abertas(funil)]
    return [
        ai_client.Ferramenta(
            nome="atualizar_negocio",
            descricao=(
                "Registra no funil de vendas o ponto em que a conversa com este contato "
                "está, e os dados que ele informou. Cria o negócio se ainda não existir. "
                "Todos os campos são opcionais: mande só o que mudou."
            ),
            parametros={
                "type": "object",
                "properties": {
                    "etapa": {"type": "string", "enum": nomes,
                              "description": "A etapa em que a conversa está agora."},
                    "titulo": {"type": "string",
                               "description": "O que o contato quer, em poucas palavras."},
                    "valor": {"type": "number",
                              "description": "Valor estimado do negócio em reais, se conhecido."},
                    "nome": {"type": "string", "description": "Nome do contato, se ele disse."},
                    "email": {"type": "string", "description": "E-mail do contato, se ele disse."},
                    "empresa": {"type": "string", "description": "Empresa do contato, se ele disse."},
                    "cargo": {"type": "string", "description": "Cargo do contato, se ele disse."},
                },
            },
        ),
    ]


async def negocio_aberto(db, tenant_id: str, funil: dict, contato_id: str) -> dict | None:
    achados = await db.deals.find(
        {"tenant_id": tenant_id, "pipeline_id": funil["id"],
         "contact_id": contato_id, "status": "aberto"}, {"_id": 0},
    ).sort([("created_at", -1), ("_id", -1)]).limit(1).to_list(1)
    return achados[0] if achados else None


async def contexto(db, tenant_id: str, funil: dict, contato: dict) -> str:
    """Onde o negócio deste contato está, para ir no histórico (não no prompt).

    Sem isto o modelo só saberia a etapa atual gastando uma volta de
    ferramenta, e moveria às cegas o cartão que um vendedor já avançou.
    """
    deal = await negocio_aberto(db, tenant_id, funil, contato["id"])
    if not deal:
        return "(funil: este contato ainda não tem negócio aberto)"
    etapa = deals.achar_etapa(funil, deal.get("etapa_id")) or {}
    return f"(funil: negócio na etapa \"{etapa.get('nome', '?')}\")"


def _limpa(valor, teto: int = 200) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:teto]


async def _preenche_contato(db, tenant_id: str, contato: dict, args: dict) -> list[str]:
    """Grava na ficha só o que está vazio. Devolve o que entrou."""
    mudanca = {}
    numero = re.sub(r"\D", "", contato.get("numero_whatsapp") or "")
    for campo in CAMPOS_CONTATO:
        novo = _limpa(args.get(campo), 120)
        if not novo:
            continue
        if campo == "email":
            novo = novo.lower()
            if not _EMAIL_RE.match(novo):
                continue
        atual = (contato.get(campo) or "").strip()
        # Contato que chega sem nome de perfil é gravado com o próprio número.
        if campo == "nome" and atual and re.sub(r"\D", "", atual) == numero and numero:
            atual = ""
        if atual:
            continue
        mudanca[campo] = novo
    if mudanca:
        await db.contacts.update_one({"id": contato["id"], "tenant_id": tenant_id},
                                     {"$set": {**mudanca, "updated_at": _now()}})
        contato.update(mudanca)
    return list(mudanca)


def executor(db, tenant_id: str, agente: dict, funil: dict, contato: dict,
             session: dict = None, simulado: bool = False):
    autor = {"id": None, "name": f"Agente de IA {agente.get('nome') or ''}".strip()}

    async def atualizar(args: dict) -> str:
        abertas = etapas_abertas(funil)
        pedida = None
        if args.get("etapa"):
            alvo = _limpa(args["etapa"]).lower()
            pedida = next((e for e in abertas if e["nome"].strip().lower() == alvo), None)
            if not pedida:
                return ("ERRO: etapa desconhecida. As que você pode usar são: "
                        + ", ".join(e["nome"] for e in abertas) + ".")
        titulo = _limpa(args.get("titulo"))
        valor = args.get("valor")
        try:
            valor = float(valor) if valor not in (None, "") else None
        except (TypeError, ValueError):
            valor = None
        if valor is not None and valor < 0:
            valor = None

        if simulado or not contato or contato.get("id") == "teste":
            partes = [f"etapa \"{pedida['nome']}\"" if pedida else None,
                      f"título \"{titulo}\"" if titulo else None,
                      f"valor R$ {valor:.2f}" if valor is not None else None]
            dados = [c for c in CAMPOS_CONTATO if _limpa(args.get(c))]
            if dados:
                partes.append("ficha: " + ", ".join(dados))
            feito = ", ".join(p for p in partes if p) or "nada"
            return f"Teste: nada foi gravado. Numa conversa real o negócio ficaria com {feito}."

        preenchidos = await _preenche_contato(db, tenant_id, contato, args)
        deal = await negocio_aberto(db, tenant_id, funil, contato["id"])
        relato = []

        if not deal:
            if not (pedida or titulo or valor is not None):
                return ("Ficha atualizada." if preenchidos
                        else "Nada a registrar: informe a etapa, o título ou o valor.")
            etapa = pedida or (abertas[0] if abertas else None)
            if not etapa:
                return "ERRO: o funil não tem etapa em aberto."
            origem = await deals.atribuir_origem(
                db, tenant_id, contato["id"], (session or {}).get("id"), None)
            ultimo = await db.deals.find(
                {"tenant_id": tenant_id, "pipeline_id": funil["id"], "etapa_id": etapa["id"]},
                {"_id": 0, "ordem": 1},
            ).sort([("ordem", -1)]).limit(1).to_list(1)
            deal = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "pipeline_id": funil["id"],
                "titulo": titulo or f"Negócio — {contato.get('nome') or contato.get('numero_whatsapp')}",
                "contact_id": contato["id"],
                "valor": valor or 0.0,
                "responsavel_id": None,
                "previsao_fechamento": None,
                "origem": "Agente de IA",
                "campanha_id": origem["campanha_id"],
                "session_id": origem["session_id"],
                "motivo_perda": None,
                "fechado_em": None,
                "ciclo_dias": None,
                "ordem": ((ultimo[0].get("ordem") or 0) + 1) if ultimo else 0,
                "criado_por": None,
                "ia_agente_id": agente.get("id"),
                "created_at": _now(),
                "updated_at": _now(),
            }
            deals.aplicar_etapa(deal, etapa)
            await db.deals.insert_one(dict(deal))
            deal.pop("_id", None)
            await deals.registrar_evento(db, deal, "criado", autor,
                                         para=etapa["nome"], valor_para=deal["valor"])
            relato.append(f"negócio criado na etapa \"{etapa['nome']}\"")
        else:
            campos, eventos = {}, []
            if pedida and pedida["id"] != deal.get("etapa_id"):
                ordem = [e["id"] for e in deals.etapas_em_ordem(funil)]
                atual = deals.achar_etapa(funil, deal.get("etapa_id")) or {}
                if atual.get("id") in ordem and ordem.index(pedida["id"]) < ordem.index(atual["id"]):
                    relato.append(f"a etapa continua \"{atual.get('nome')}\" (você não volta etapa)")
                else:
                    deals.aplicar_etapa(campos, pedida)
                    ultimo = await db.deals.find(
                        {"tenant_id": tenant_id, "pipeline_id": funil["id"],
                         "etapa_id": pedida["id"]}, {"_id": 0, "ordem": 1},
                    ).sort([("ordem", -1)]).limit(1).to_list(1)
                    campos["ordem"] = ((ultimo[0].get("ordem") or 0) + 1) if ultimo else 0
                    eventos.append(("etapa", {"de": atual.get("nome"), "para": pedida["nome"]}))
                    relato.append(f"movido de \"{atual.get('nome')}\" para \"{pedida['nome']}\"")
            if titulo and titulo != deal.get("titulo"):
                campos["titulo"] = titulo
                relato.append("título atualizado")
            if valor is not None and valor != float(deal.get("valor") or 0):
                campos["valor"] = valor
                eventos.append(("valor", {"valor_de": deal.get("valor"), "valor_para": valor}))
                relato.append(f"valor R$ {valor:.2f}")
            if campos:
                campos["updated_at"] = _now()
                await db.deals.update_one({"id": deal["id"], "tenant_id": tenant_id},
                                          {"$set": campos})
                for tipo, extra in eventos:
                    await deals.registrar_evento(db, deal, tipo, autor, **extra)

        if preenchidos:
            relato.append("ficha: " + ", ".join(preenchidos))
        if not relato:
            return "Nada mudou: o negócio já estava assim."
        texto = "; ".join(relato)
        if session and session.get("id"):
            from flow_runtime import log_message  # tardio: flow_runtime importa ai_agents
            try:
                await log_message(db, session["id"], tenant_id, "sistema",
                                  f"Agente de IA no funil: {texto}", mtype="system")
            except Exception as e:  # o registro na conversa é aviso, não a ação
                logger.warning("Falha ao registrar movimento de funil na conversa: %s", e)
        return f"Registrado: {texto}. Continue a conversa normalmente."

    async def executar(nome: str, argumentos: dict) -> str:
        if nome != "atualizar_negocio":
            return f"ERRO: ferramenta desconhecida ({nome})."
        return await atualizar(argumentos or {})

    return executar


async def preparar(db, tenant_id: str, agente: dict, contato: dict = None,
                   session: dict = None, simulado: bool = False):
    """Bloco do prompt, ferramentas e executor. `("", None, None)` desligado."""
    if not agente.get("funil_ativo"):
        return "", None, None
    funil = await funil_do_agente(db, tenant_id, agente)
    if not funil or not etapas_abertas(funil):
        return "", None, None
    bloco = bloco_de_instrucoes(funil)
    if contato is None:
        return bloco, None, None
    return bloco, _ferramentas(funil), executor(db, tenant_id, agente, funil, contato,
                                                session, simulado=simulado)
