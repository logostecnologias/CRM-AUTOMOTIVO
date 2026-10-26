"""Formulário de site: quem preencheu a landing page vira contato aqui.

Nasceu da R3, que tinha uma landing page com formulário gravando os leads num
banco à parte. O lead ficava lá, sem conversa, sem funil e sem dono, e a
pergunta que importa ("quanto vendeu a campanha do Instagram?") não tinha
resposta em lugar nenhum. É genérico de propósito: serve para qualquer empresa,
qualquer site e qualquer construtor de página, porque o que chega é um POST com
os campos do formulário, e só.

Decisões, e o motivo de cada uma:

  - **Uma chave por formulário, e ela é pública.** Ela fica no código da página,
    à vista de quem abrir o "inspecionar", exatamente como a chave anon do
    Supabase. Por isso o único poder dela é **criar uma resposta neste
    formulário**: não lê nada, não lista nada, não mexe em configuração. O que
    a protege de abuso é o freio por IP, o tamanho máximo, o campo-isca, a
    trava opcional de domínio e a troca da chave na tela.

  - **Quem envia é anônimo, então nunca sobrescreve.** Contato que já existe só
    ganha o que estava **vazio** na ficha, e as etiquetas são somadas. Sem isso,
    qualquer pessoa com a chave trocaria o nome e o e-mail de qualquer cliente
    da empresa só sabendo o telefone dele. É o oposto do "atualizar" da
    importação de CSV, e pelo motivo oposto: lá quem manda é o admin.

  - **Aceita qualquer campo e não perde nenhum.** Nome, telefone, e-mail,
    empresa e cargo são reconhecidos pelos mesmos sinônimos da importação de
    CSV; campo com o nome de um campo personalizado vai para a ficha; o resto
    fica guardado na resposta e na anotação. Exigir que o site use os nossos
    nomes de campo travaria quem monta a página num construtor que não deixa
    escolher.

  - **Cada envio é uma resposta própria** (`formulario_respostas`), mesmo de
    quem já é contato. É dela que sai a origem (UTM, página, clique de anúncio)
    e é por ela que o negócio fechado volta para a campanha que trouxe o lead.
    Gravar a origem só no contato perderia a segunda conversão de quem volta
    por outro anúncio.

  - **Sem número válido, a resposta é guardada como recusada**, com o motivo.
    O número é a identidade do contato no sistema inteiro, então não há ficha a
    criar; mas sumir com o envio esconderia um formulário mal configurado, que
    é exatamente o que a tela precisa mostrar.

  - **A mesma pessoa no mesmo formulário é uma resposta só.** Outro envio do
    mesmo número dentro de `JANELA_COMPLEMENTO_MIN` **completa** a resposta
    anterior (campos novos entram, a anotação na ficha é reescrita com tudo),
    sem segundo negócio, tarefa ou mensagem. Cobre o clique duplo e o
    formulário em etapas que envia a primeira (nome e telefone, para não
    perder quem desiste) e depois o resto. Descartar o segundo envio, como
    era, perdia justamente as respostas completas.

  - **O WhatsApp sai depois da resposta ao site**, como na ligação: o
    formulário não pode ficar girando enquanto a Meta (ou a WuzAPI) responde. E
    a mensagem é o pedido que a pessoa fez ao preencher, o mesmo raciocínio da
    tecla 1 do telefone.
"""
import aquecimento
import asyncio
import json
import logging
import re
import secrets
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import atividades
import contatos_csv
import deals

logger = logging.getLogger("zappzen.formularios")

PREFIXO_CHAVE = "zzf_"

# Tetos do que um envio pode trazer. Um formulário de verdade tem uma dezena de
# campos curtos; isto existe para um POST forjado não gravar um megabyte por
# resposta a cada chamada.
MAX_BYTES = 64 * 1024
MAX_CAMPOS = 60
MAX_CHAVE = 80
MAX_VALOR = 2000

# Mesmo número, mesmo formulário, dentro deste prazo: é a mesma resposta
# (clique duplo, ou a etapa seguinte de um formulário em etapas), não um
# segundo pedido. Depois dele, a pessoa voltou, e é uma conversão nova.
JANELA_COMPLEMENTO_MIN = 60
# Mensagem de WhatsApp: uma por pessoa nesta janela, mesmo que ela preencha de
# novo (ou preencha dois formulários da mesma empresa). Mesmo prazo do
# telefone, pelo mesmo motivo.
JANELA_WHATSAPP_MIN = 30

# Quem atende quando o lead responder a mensagem. Os mesmos três do telefone.
MODOS = ("agente", "bot", "fila")

# Estados da resposta.
RECEBIDA = "recebida"
# Não é mais gravado (o envio repetido completa a resposta anterior); fica
# para as respostas antigas que já o têm.
REPETIDA = "repetida"
RECUSADA = "recusada"

# Estados da mensagem de WhatsApp de cada resposta.
WPP_PENDENTE = "pendente"
WPP_ENVIANDO = "enviando"
WPP_ENVIADA = "enviada"
WPP_REPETIDA = "repetida"
WPP_SEM_MODELO = "sem_modelo"
WPP_FALHA = "falha"

# O que a pessoa pode preencher na ficha a partir do formulário. `origem`,
# `tags` e `responsavel` ficam de fora de propósito: são decididos pela
# configuração do formulário, nunca por quem envia.
_ALVOS = ("nome", "numero_whatsapp", "email", "empresa", "cargo")
_SOBRENOME = {"sobrenome", "ultimonome", "lastname", "surname"}
_PRIMEIRO_NOME = {"primeironome", "firstname", "prenome"}
_UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
# Identificador do clique no anúncio, que cada rede põe na URL. Guardado para a
# empresa poder devolver a conversão à rede depois (API de conversões).
_CLIQUE = ("gclid", "gbraid", "wbraid", "fbclid", "ttclid", "msclkid")
_PAGINA = {"pagina", "page", "pageurl", "url", "paginaurl", "landingpage"}
_REFERRER = {"referrer", "referer", "origemurl"}
# Campo-isca: invisível para gente, preenchido por robô que preenche tudo.
HONEYPOT = "_hp"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TEXTOS_PADRAO = {
    "mensagem": (
        "Olá, {primeiro_nome}! Recebemos seu cadastro na {empresa}. "
        "Como podemos te ajudar?"),
    "tarefa_titulo": "Retornar lead do formulário {formulario}",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def nova_chave() -> str:
    return PREFIXO_CHAVE + secrets.token_urlsafe(18)


def montar(texto: str, valores: dict) -> str:
    """Preenche `{nome}`, `{primeiro_nome}`, `{empresa}`, `{formulario}`.

    Placeholder desconhecido fica como está, mesma regra do telefone e do
    lembrete da agenda: um texto com chave errada sai estranho, mas sai.
    """
    return re.sub(r"\{([a-zA-Z0-9_]+)\}",
                  lambda m: str(valores.get(m.group(1), m.group(0))), texto or "")


# ---------------------------------------------------------------------------
# Freio de abuso
# ---------------------------------------------------------------------------

# Janela deslizante em memória, como o `login_guard`, e com o mesmo limite de
# escopo: vale dentro de um processo. Dois freios:
#   - por IP: uma pessoa não preenche 20 formulários em 10 minutos;
#   - por formulário: teto de vazão que segura um ataque distribuído antes de
#     ele encher a base de contatos falsos.
JANELA_IP = 600
MAX_POR_IP = 20
JANELA_FORM = 3600
MAX_POR_FORM = 1000

_envios: dict[str, list[float]] = defaultdict(list)


def _podar(chave: str, janela: int, agora: float) -> list[float]:
    recentes = [t for t in _envios.get(chave, ()) if agora - t < janela]
    if recentes:
        _envios[chave] = recentes
    else:
        _envios.pop(chave, None)
    return recentes


def freio(ip: str, formulario_id: str) -> bool:
    """True se este envio pode passar; já conta o envio quando passa."""
    agora = time.monotonic()
    chaves = ((f"ip:{ip}", JANELA_IP, MAX_POR_IP),
              (f"form:{formulario_id}", JANELA_FORM, MAX_POR_FORM))
    for chave, janela, teto in chaves:
        if len(_podar(chave, janela, agora)) >= teto:
            return False
    for chave, _, _ in chaves:
        _envios[chave].append(agora)
    return True


def _reset_para_testes():
    _envios.clear()


# ---------------------------------------------------------------------------
# Domínio
# ---------------------------------------------------------------------------

def normaliza_dominio(valor: str) -> str:
    """`https://www.R3.com.br/lp?x=1` → `r3.com.br`."""
    d = (valor or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0]
    return d[4:] if d.startswith("www.") else d


def dominio_permitido(dominios: list[str], origem: str | None) -> bool:
    """O envio veio de uma página de um domínio liberado?

    Sem domínio configurado, tudo passa: é o caso de quem manda pelo n8n, por
    Zapier ou do próprio servidor, que não tem `Origin`. Com domínio, exige que
    `Origin` (ou `Referer`) seja ele ou um subdomínio dele. Não é segurança
    forte (um robô forja o cabeçalho), é o que impede a chave copiada de uma
    página ser usada de dentro de outra.
    """
    if not dominios:
        return True
    host = normaliza_dominio(origem or "")
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in dominios)


# ---------------------------------------------------------------------------
# Leitura do envio
# ---------------------------------------------------------------------------

def _texto(valor) -> str:
    """Valor de campo como texto. Lista (checkbox múltiplo) vira "a, b"."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, (list, tuple)):
        return ", ".join(_texto(v) for v in valor if _texto(v))
    if isinstance(valor, dict):
        return json.dumps(valor, ensure_ascii=False)
    return str(valor).strip()


def limpar(payload: dict) -> dict:
    """O envio cru, aparado: chaves e valores com teto, no máximo `MAX_CAMPOS`.

    É isto que fica guardado na resposta. O corte é aqui, antes de qualquer
    leitura, para nenhum caminho adiante trabalhar com o que chegou sem teto.
    """
    limpo: dict[str, str] = {}
    for chave, valor in (payload or {}).items():
        if len(limpo) >= MAX_CAMPOS:
            break
        k = str(chave).strip()[:MAX_CHAVE]
        if not k:
            continue
        limpo[k] = _texto(valor)[:MAX_VALOR]
    return limpo


def separar(dados: dict, campos_defs: list[dict]) -> dict:
    """Divide o envio no que vai para a ficha, para a origem e o resto.

    Os nomes de campo são cotejados pelo texto normalizado (sem acento, sem
    espaço, sem caixa), com os sinônimos da importação de CSV: "Celular",
    "WhatsApp" e "telefone" são o mesmo campo, e o site não precisa saber como
    o ZappZen chama cada coisa.
    """
    sinonimos = {
        contatos_csv.normaliza_texto(s): alvo
        for alvo, lista in contatos_csv.CAMPOS_PADRAO.items() if alvo in _ALVOS
        for s in lista
    }
    por_campo = {contatos_csv.normaliza_texto(d["nome"]): d["id"] for d in campos_defs}
    utm_norm = {contatos_csv.normaliza_texto(u): u for u in _UTM}
    clique_norm = {contatos_csv.normaliza_texto(c): c for c in _CLIQUE}

    contato: dict[str, str] = {}
    campos: dict[str, str] = {}
    utm: dict[str, str] = {}
    clique: dict[str, str] = {}
    extras: dict[str, str] = {}
    pagina = referrer = ""
    primeiro = sobrenome = ""
    isca = False

    for chave, valor in dados.items():
        if chave == HONEYPOT:
            isca = bool(valor)
            continue
        if not valor:
            continue
        n = contatos_csv.normaliza_texto(chave.lstrip("_"))
        if n in utm_norm:
            utm[utm_norm[n]] = valor[:200]
        elif n in clique_norm:
            clique[clique_norm[n]] = valor[:300]
        elif n in _PAGINA and not pagina:
            pagina = valor[:500]
        elif n in _REFERRER and not referrer:
            referrer = valor[:500]
        elif n in _PRIMEIRO_NOME and not primeiro:
            primeiro = valor
        elif n in _SOBRENOME and not sobrenome:
            sobrenome = valor
        elif n in sinonimos and sinonimos[n] not in contato:
            contato[sinonimos[n]] = valor
        elif n in por_campo and por_campo[n] not in campos:
            campos[por_campo[n]] = valor
        elif not chave.startswith("_"):
            # Campo com sublinhado na frente é do script, não da pessoa.
            extras[chave] = valor

    # "Nome" + "Sobrenome" em campos separados é o desenho de metade dos
    # construtores de página; a ficha tem um campo só.
    if not contato.get("nome") and primeiro:
        contato["nome"] = primeiro
    if sobrenome and contato.get("nome") and sobrenome.lower() not in contato["nome"].lower():
        contato["nome"] = f"{contato['nome']} {sobrenome}"
    if contato.get("nome"):
        contato["nome"] = contato["nome"][:120]

    return {"contato": contato, "campos": campos, "utm": utm, "clique": clique,
            "pagina": pagina or None, "referrer": referrer or None,
            "extras": extras, "isca": isca}


def resumo_origem(utm: dict, pagina: str | None, formulario_nome: str) -> str:
    """O texto curto de origem que vai no negócio: "Formulário LP · instagram / lancamento"."""
    partes = [p for p in (utm.get("utm_source"), utm.get("utm_campaign")) if p]
    base = f"Formulário {formulario_nome}"
    return f"{base} · {' / '.join(partes)}" if partes else base


# ---------------------------------------------------------------------------
# Uma resposta por vez para cada número
# ---------------------------------------------------------------------------

# Dois envios simultâneos do mesmo número (o clique duplo) leriam "não existe
# contato" os dois e criariam duas fichas. Mesma trava por chave do
# `flow_runtime`, com o mesmo limite: vale dentro de um processo.
_travas: dict[str, tuple[asyncio.Lock, int]] = {}


@asynccontextmanager
async def _uma_por_vez(chave: str):
    trava, esperando = _travas.get(chave, (None, 0))
    if trava is None:
        trava = asyncio.Lock()
    _travas[chave] = (trava, esperando + 1)
    try:
        async with trava:
            yield
    finally:
        _trava, quantos = _travas[chave]
        if quantos <= 1:
            _travas.pop(chave, None)
        else:
            _travas[chave] = (_trava, quantos - 1)


# ---------------------------------------------------------------------------
# Recebimento
# ---------------------------------------------------------------------------

async def _campos_validos(db, tenant_id: str, campos: dict) -> tuple[dict, list[str]]:
    """Valores de campo personalizado que passam na validação, e os avisos.

    Um valor inválido derruba **o campo**, não o lead: "abc" num campo numérico
    não pode fazer a empresa perder a pessoa que preencheu o resto certo. O
    valor recusado continua na resposta, que guarda o envio inteiro.
    """
    from fastapi import HTTPException
    from routes.contacts import _valida_campos

    validos: dict = {}
    avisos: list[str] = []
    for cid, valor in campos.items():
        try:
            validos.update(await _valida_campos(db, tenant_id, {cid: valor}))
        except HTTPException as e:
            avisos.append(str(e.detail))
    return validos, avisos


def _nota(formulario: dict, dados: dict, utm: dict, pagina: str | None) -> str:
    """O que a pessoa preencheu, como anotação na ficha.

    É o que o atendente lê quando a conversa chega: "quero orçamento para 3
    salas" está num campo de mensagem que a ficha não tem onde guardar.
    """
    linhas = [f"Preencheu o formulário \"{formulario['nome']}\""]
    for chave, valor in dados.items():
        if valor and not chave.startswith("_"):
            linhas.append(f"{chave}: {valor}")
    origem = ", ".join(f"{k.replace('utm_', '')}={v}" for k, v in utm.items())
    if origem:
        linhas.append(f"Origem: {origem}")
    if pagina:
        linhas.append(f"Página: {pagina}")
    return "\n".join(linhas)[:5000]


async def _gravar_nota(db, formulario: dict, resposta: dict) -> str:
    """A anotação da resposta na ficha: criada, ou reescrita com tudo."""
    texto = _nota(formulario, resposta["dados"], resposta["utm"], resposta["pagina"])
    nota_id = resposta.get("nota_id")
    if nota_id:
        r = await db.contact_notes.update_one(
            {"tenant_id": resposta["tenant_id"], "id": nota_id}, {"$set": {"texto": texto}})
        if r.matched_count:
            return nota_id
    # Resposta sem anotação (anterior a esta versão) ou anotação apagada à mão.
    nota_id = str(uuid.uuid4())
    await db.contact_notes.insert_one({
        "id": nota_id,
        "tenant_id": resposta["tenant_id"],
        "contact_id": resposta["contact_id"],
        "texto": texto,
        "autor_id": None,
        "autor_nome": f"Formulário {formulario['nome']}",
        "created_at": _now(),
    })
    return nota_id


async def _complementar(db, formulario: dict, anterior: dict, nova: dict) -> dict:
    """Junta um envio novo à resposta anterior da mesma pessoa.

    O que veio preenchido agora ganha do que veio antes (a etapa seguinte é a
    resposta mais completa); campo que veio vazio não apaga o anterior. A
    origem do anúncio fica a da primeira chegada, só completada: é ela que
    trouxe a pessoa. Negócio, tarefa e WhatsApp já foram decididos no
    primeiro envio e não se repetem.
    """
    def junta(velho: dict, novo: dict) -> dict:
        return {**(velho or {}), **{k: v for k, v in (novo or {}).items() if v not in ("", None)}}

    def completa(velho: dict, novo: dict) -> dict:
        return {**{k: v for k, v in (novo or {}).items() if v}, **{k: v for k, v in (velho or {}).items() if v}}

    mudou = {
        "dados": junta(anterior.get("dados"), nova["dados"]),
        "nome": nova.get("nome") or anterior.get("nome"),
        "email": nova.get("email") or anterior.get("email"),
        "utm": completa(anterior.get("utm"), nova["utm"]),
        "clique": completa(anterior.get("clique"), nova["clique"]),
        "pagina": anterior.get("pagina") or nova.get("pagina"),
        "referrer": anterior.get("referrer") or nova.get("referrer"),
        "avisos": list(dict.fromkeys((anterior.get("avisos") or []) + nova["avisos"])),
        "envios": int(anterior.get("envios") or 1) + 1,
        "atualizada_em": _now(),
    }
    resposta = {**anterior, **mudou}
    mudou["nota_id"] = await _gravar_nota(db, formulario, resposta)
    resposta["nota_id"] = mudou["nota_id"]
    await db.formulario_respostas.update_one(
        {"tenant_id": anterior["tenant_id"], "id": anterior["id"]}, {"$set": mudou})
    # Quem chama não agenda o WhatsApp de novo: ele é do primeiro envio.
    return {**resposta, "complemento": True}


async def _contato(db, formulario: dict, numero: str, sep: dict,
                   campos: dict) -> tuple[dict, bool]:
    """A ficha de quem preencheu: criada, ou completada sem sobrescrever."""
    tenant_id = formulario["tenant_id"]
    dados = sep["contato"]
    tags = [t for t in (formulario.get("tags") or []) if t]
    agora = _now()

    contato = await db.contacts.find_one(
        {"tenant_id": tenant_id,
         "numero_whatsapp": {"$in": contatos_csv.variantes_br(numero)}}, {"_id": 0})
    if not contato:
        contato = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "bot_id": None,
            "numero_whatsapp": numero,
            "nome": dados.get("nome") or numero,
            "email": dados.get("email"),
            "empresa": dados.get("empresa"),
            "cargo": dados.get("cargo"),
            # Só na criação: a origem de quem já era contato é a de antes.
            "origem": f"formulário: {formulario['nome']}",
            "responsavel_id": formulario.get("responsavel_id"),
            "tags": tags[:20],
            "campos": campos,
            "opt_out": False,
            "created_at": agora,
            "updated_at": agora,
        }
        await db.contacts.insert_one(dict(contato))
        return contato, True

    # Só o que estava vazio. Ver o docstring do módulo: quem envia é anônimo.
    mudanca: dict = {}
    if dados.get("nome") and contato.get("nome") in (None, "", contato.get("numero_whatsapp")):
        mudanca["nome"] = dados["nome"]
    for chave in ("email", "empresa", "cargo"):
        if dados.get(chave) and not contato.get(chave):
            mudanca[chave] = dados[chave]
    if formulario.get("responsavel_id") and not contato.get("responsavel_id"):
        mudanca["responsavel_id"] = formulario["responsavel_id"]
    atuais = contato.get("campos") or {}
    for cid, valor in campos.items():
        if atuais.get(cid) in (None, ""):
            mudanca[f"campos.{cid}"] = valor
    if tags:
        juntas = list(contato.get("tags") or [])
        for t in tags:
            if t.lower() not in {x.lower() for x in juntas}:
                juntas.append(t)
        if juntas != (contato.get("tags") or []):
            mudanca["tags"] = juntas[:20]
    if mudanca:
        mudanca["updated_at"] = agora
        await db.contacts.update_one({"id": contato["id"], "tenant_id": tenant_id},
                                     {"$set": mudanca})
        for k, v in mudanca.items():
            if k.startswith("campos."):
                contato.setdefault("campos", {})[k.split(".", 1)[1]] = v
            else:
                contato[k] = v
    return contato, False


async def _negocio(db, formulario: dict, contato: dict, resposta: dict) -> str | None:
    """O negócio do lead no funil escolhido. Devolve o id.

    Quem já tem negócio **aberto** nesse funil não ganha outro: preencher o
    formulário de novo é a mesma venda, e dois cartões para a mesma pessoa
    dividiriam o histórico e contariam o lead em dobro no relatório. O negócio
    existente ganha um evento dizendo que a pessoa voltou.
    """
    cfg = formulario.get("negocio") or {}
    if not cfg.get("ativo") or not cfg.get("pipeline_id"):
        return None
    tenant_id = formulario["tenant_id"]
    autor = {"id": None, "name": f"Formulário {formulario['nome']}"}

    pipeline = await db.pipelines.find_one(
        {"id": cfg["pipeline_id"], "tenant_id": tenant_id}, {"_id": 0})
    if not pipeline:
        logger.warning("Formulário %s aponta para funil inexistente", formulario["id"])
        return None

    aberto = await db.deals.find_one(
        {"tenant_id": tenant_id, "pipeline_id": pipeline["id"],
         "contact_id": contato["id"], "status": "aberto"}, {"_id": 0})
    if aberto:
        await deals.registrar_evento(db, aberto, "formulario", autor,
                                     formulario_id=formulario["id"],
                                     resposta_id=resposta["id"])
        return aberto["id"]

    etapas = sorted(pipeline.get("etapas") or [], key=lambda e: e.get("ordem", 0))
    etapa = deals.achar_etapa(pipeline, cfg.get("etapa_id")) if cfg.get("etapa_id") else None
    etapa = etapa or (etapas[0] if etapas else None)
    if not etapa:
        return None

    ultimo = await db.deals.find(
        {"tenant_id": tenant_id, "pipeline_id": pipeline["id"], "etapa_id": etapa["id"]},
        {"_id": 0, "ordem": 1},
    ).sort([("ordem", -1)]).limit(1).to_list(1)
    valores = {"nome": contato.get("nome") or "", "formulario": formulario["nome"]}
    titulo = montar((cfg.get("titulo") or "").strip(), valores).strip() \
        or f"{formulario['nome']} — {contato.get('nome') or contato['numero_whatsapp']}"
    deal = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "pipeline_id": pipeline["id"],
        "titulo": titulo[:200],
        "contact_id": contato["id"],
        "valor": float(cfg.get("valor") or 0),
        "responsavel_id": formulario.get("responsavel_id"),
        "previsao_fechamento": None,
        "origem": resumo_origem(resposta.get("utm") or {}, resposta.get("pagina"),
                                formulario["nome"]),
        "campanha_id": None,
        "session_id": None,
        # É por estes dois que o negócio ganho volta para o formulário e para a
        # campanha de anúncio que trouxe a pessoa.
        "formulario_id": formulario["id"],
        "formulario_resposta_id": resposta["id"],
        "motivo_perda": None,
        "fechado_em": None,
        "ciclo_dias": None,
        "ordem": ((ultimo[0].get("ordem") or 0) + 1) if ultimo else 0,
        "criado_por": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    deals.aplicar_etapa(deal, etapa)
    await db.deals.insert_one(dict(deal))
    await deals.registrar_evento(db, deal, "criado", autor,
                                 para=etapa["nome"], valor_para=deal["valor"])
    return deal["id"]


async def _tarefa(db, formulario: dict, contato: dict, deal_id: str | None) -> str | None:
    """"Retornar o lead", na agenda do responsável.

    Exige responsável (a configuração recusa sem ele): tarefa sem dono não
    aparece na agenda de ninguém, que é como um lead esfria sem ninguém ver.
    """
    cfg = formulario.get("tarefa") or {}
    responsavel = formulario.get("responsavel_id")
    if not cfg.get("ativo") or not responsavel:
        return None
    prazo = max(0, int(cfg.get("prazo_min") or 0))
    vence = (datetime.now(timezone.utc) + timedelta(minutes=prazo)).isoformat()
    valores = {"nome": contato.get("nome") or "", "formulario": formulario["nome"]}
    titulo = montar((cfg.get("titulo") or "").strip() or TEXTOS_PADRAO["tarefa_titulo"],
                    valores).strip()
    doc = atividades.novo(
        formulario["tenant_id"], {"id": responsavel},
        titulo=titulo[:200], tipo="ligacao", vence_em=vence,
        descricao=f"Lead de {contato.get('nome') or contato['numero_whatsapp']}",
        responsavel_id=responsavel, contact_id=contato["id"], deal_id=deal_id)
    # Quem criou foi o formulário, não o responsável.
    doc["criado_por"] = None
    await db.activities.insert_one(dict(doc))
    return doc["id"]


async def receber(db, formulario: dict, payload: dict) -> dict:
    """Grava a resposta e faz o que o formulário manda. Devolve a resposta.

    A mensagem de WhatsApp não sai daqui: quem chama agenda `enviar_whatsapp`
    para depois da resposta ao site, quando `whatsapp_status` volta pendente.
    """
    tenant_id = formulario["tenant_id"]
    dados = limpar(payload)
    defs = await db.contact_field_defs.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1, "nome": 1}).to_list(500)
    sep = separar(dados, defs)

    resposta = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "formulario_id": formulario["id"],
        "status": RECEBIDA,
        "erro": None,
        "avisos": [],
        "dados": {k: v for k, v in dados.items() if k != HONEYPOT},
        "nome": sep["contato"].get("nome"),
        "numero": None,
        "email": sep["contato"].get("email"),
        "utm": sep["utm"],
        "clique": sep["clique"],
        "pagina": sep["pagina"],
        "referrer": sep["referrer"],
        "contact_id": None,
        "contato_novo": False,
        "deal_id": None,
        "atividade_id": None,
        "whatsapp_status": None,
        "whatsapp_erro": None,
        "session_id": None,
        "respondeu_em": None,
        "nota_id": None,
        "envios": 1,
        "created_at": _now(),
    }

    numero, erro = contatos_csv.normaliza_numero(sep["contato"].get("numero_whatsapp") or "")
    if erro:
        resposta.update(status=RECUSADA,
                        erro=f"Telefone inválido ({erro})" if sep["contato"].get("numero_whatsapp")
                        else "O envio não trouxe telefone")
        await db.formulario_respostas.insert_one(dict(resposta))
        return resposta
    resposta["numero"] = numero

    email = sep["contato"].get("email")
    if email and not _EMAIL_RE.match(email):
        # Um e-mail torto não derruba o lead (o telefone é o que importa), mas
        # também não entra na ficha, onde quebraria qualquer envio futuro.
        sep["contato"].pop("email")
        resposta["avisos"].append(f"E-mail inválido ignorado: {email[:80]}")

    async with _uma_por_vez(f"{tenant_id}:{numero}"):
        campos, avisos = await _campos_validos(db, tenant_id, sep["campos"])
        resposta["avisos"] += avisos
        contato, novo = await _contato(db, formulario, numero, sep, campos)
        resposta["contact_id"] = contato["id"]
        resposta["contato_novo"] = novo

        desde = (datetime.now(timezone.utc)
                 - timedelta(minutes=JANELA_COMPLEMENTO_MIN)).isoformat()
        anteriores = await db.formulario_respostas.find({
            "tenant_id": tenant_id, "formulario_id": formulario["id"],
            "contact_id": contato["id"], "status": RECEBIDA,
            "created_at": {"$gte": desde},
        }, {"_id": 0}).sort([("created_at", -1), ("_id", -1)]).limit(1).to_list(1)
        if anteriores:
            return await _complementar(db, formulario, anteriores[0], resposta)

        resposta["nota_id"] = await _gravar_nota(db, formulario, resposta)
        resposta["deal_id"] = await _negocio(db, formulario, contato, resposta)
        resposta["atividade_id"] = await _tarefa(db, formulario, contato, resposta["deal_id"])
        if (formulario.get("whatsapp") or {}).get("ativo"):
            resposta["whatsapp_status"] = WPP_PENDENTE
        await db.formulario_respostas.insert_one(dict(resposta))
    return resposta


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------

async def _conexao(db, tenant_id: str, connection_id: str | None) -> dict | None:
    """A escolhida; sem escolha, a primeira conectada. Mesma regra do telefone."""
    if connection_id:
        conn = await db.whatsapp_connections.find_one(
            {"id": connection_id, "tenant_id": tenant_id}, {"_id": 0})
        if conn:
            return conn
    return await db.whatsapp_connections.find_one(
        {"tenant_id": tenant_id, "status": "conectado"}, {"_id": 0}) \
        or await db.whatsapp_connections.find_one({"tenant_id": tenant_id}, {"_id": 0})


async def _repetida_wpp(db, resposta: dict) -> bool:
    desde = (datetime.now(timezone.utc) - timedelta(minutes=JANELA_WHATSAPP_MIN)).isoformat()
    return bool(await db.formulario_respostas.find_one({
        "tenant_id": resposta["tenant_id"],
        "contact_id": resposta["contact_id"],
        "whatsapp_status": WPP_ENVIADA,
        "id": {"$ne": resposta["id"]},
        "created_at": {"$gte": desde},
    }, {"_id": 0, "id": 1}))


async def enviar_whatsapp(db, tenant_id: str, resposta_id: str) -> str:
    """Manda a mensagem para quem preencheu. Devolve o estado final.

    Roda depois da resposta ao site, então nunca levanta: o desfecho fica
    gravado na própria resposta, que é onde a tela o mostra.
    """
    # Tardios pelo mesmo ciclo do telefone: `outbound` puxa `flow_runtime`,
    # que importa este módulo para marcar a resposta do contato.
    import flow_runtime
    import outbound

    resposta = await db.formulario_respostas.find_one_and_update(
        {"id": resposta_id, "tenant_id": tenant_id, "whatsapp_status": WPP_PENDENTE},
        {"$set": {"whatsapp_status": WPP_ENVIANDO}},
    )
    if not resposta:
        return "ignorada"

    async def fim(status: str, **extra) -> str:
        await db.formulario_respostas.update_one(
            {"id": resposta_id, "tenant_id": tenant_id},
            {"$set": {"whatsapp_status": status, **extra}})
        return status

    try:
        if await _repetida_wpp(db, resposta):
            return await fim(WPP_REPETIDA)
        formulario = await db.formularios.find_one(
            {"id": resposta["formulario_id"], "tenant_id": tenant_id}, {"_id": 0}) or {}
        cfg = formulario.get("whatsapp") or {}
        conn = await _conexao(db, tenant_id, cfg.get("connection_id"))
        if not conn:
            return await fim(WPP_FALHA, whatsapp_erro="Empresa sem conexão de WhatsApp")
        contato = await db.contacts.find_one(
            {"id": resposta["contact_id"], "tenant_id": tenant_id}, {"_id": 0})
        if not contato:
            return await fim(WPP_FALHA, whatsapp_erro="Contato não encontrado")

        modo = cfg.get("resposta_modo") if cfg.get("resposta_modo") in MODOS else "agente"
        session, _ = await outbound.ensure_session(
            db, tenant_id, conn["id"], contato,
            bot_id=cfg.get("bot_id") if modo == "bot" else None,
            departamento_id=conn.get("departamento_padrao_id"),
            origem="formulario",
            resposta_modo="bot" if modo == "bot" else "aguardando",
            # Mesma regra do telefone: com a marca, o robô dá a partida (modo
            # `bot`) e a fila segura a conversa (modo `fila`); sem ela, o
            # agente de IA atende quem responder.
            aguardar_primeira_resposta=modo in ("bot", "fila"),
        )
        await db.conversation_sessions.update_one(
            {"id": session["id"], "tenant_id": tenant_id},
            {"$set": {"formulario_resposta_id": resposta_id, "updated_at": _now()}})
        await db.formulario_respostas.update_one(
            {"id": resposta_id, "tenant_id": tenant_id}, {"$set": {"session_id": session["id"]}})

        empresa = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1}) or {}
        nome = (contato.get("nome") or "").strip()
        if nome == contato.get("numero_whatsapp"):
            nome = ""
        valores = {"empresa": empresa.get("name") or "nossa empresa",
                   "nome": nome, "primeiro_nome": nome.split(" ")[0] if nome else "",
                   "formulario": formulario.get("nome") or ""}
        corpo = montar((cfg.get("mensagem") or "").strip() or TEXTOS_PADRAO["mensagem"], valores)
        if not nome:
            # "Olá, !" quando o formulário não pede nome.
            corpo = re.sub(r"[ \t]+([,!?.])", r"\1", corpo).replace(",!", "!")
        modelo = cfg.get("template") or {}

        # No canal não oficial, envios ativos da mesma conexão saem espaçados:
        # uma rajada de leads (ou de ligações) não vira uma rajada de mensagens.
        await aquecimento.espacar(conn)
        if flow_runtime.janela_aberta(session, conn.get("canal")):
            await flow_runtime.send_human_message(tenant_id, session["id"], corpo)
            return await fim(WPP_ENVIADA)
        if modelo.get("nome"):
            await flow_runtime.send_template_message(
                tenant_id, session["id"], modelo["nome"], modelo.get("idioma") or "pt_BR",
                [montar(v or "", valores).strip() or " " for v in (modelo.get("variaveis") or [])],
                corpo)
            return await fim(WPP_ENVIADA)

        await flow_runtime.log_message(
            db, session["id"], tenant_id, "sistema",
            "Mensagem do formulário não enviada: a janela de 24h desta conversa está "
            "fechada e não há modelo aprovado configurado no formulário.",
            mtype="system")
        return await fim(WPP_SEM_MODELO)
    except Exception as e:
        logger.warning("Resposta de formulário %s: falha ao mandar o WhatsApp: %s", resposta_id, e)
        return await fim(WPP_FALHA, whatsapp_erro=str(e)[:300])


async def marcar_resposta(db, tenant_id: str, session: dict) -> None:
    """A primeira mensagem do lead depois da nossa. Mesmo papel da ligação."""
    resposta_id = session.get("formulario_resposta_id")
    if not resposta_id:
        return
    await db.formulario_respostas.update_one(
        {"id": resposta_id, "tenant_id": tenant_id, "respondeu_em": None},
        {"$set": {"respondeu_em": _now()}})
    await db.conversation_sessions.update_one(
        {"id": session["id"], "tenant_id": tenant_id},
        {"$set": {"formulario_resposta_id": None}})
    session["formulario_resposta_id"] = None


# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

MAX_RESUMO = 50000


async def resumo(db, tenant_id: str, de: str | None, ate: str | None,
                 formulario_id: str | None = None) -> dict:
    """O caminho do lead: chegou → virou contato → respondeu → negócio → venda.

    Quebrado por origem (`utm_source` / `utm_campaign`), que é a pergunta de
    quem paga o anúncio. A venda é contada pelo negócio que nasceu da resposta,
    esteja fechado quando estiver: o lead de agosto que fechou em setembro
    continua sendo da campanha de agosto.
    """
    filtro: dict = {"tenant_id": tenant_id}
    if formulario_id:
        filtro["formulario_id"] = formulario_id
    if de or ate:
        filtro["created_at"] = {k: v for k, v in (("$gte", de), ("$lt", ate)) if v}
    docs = await db.formulario_respostas.find(
        filtro, {"_id": 0, "status": 1, "utm": 1, "contato_novo": 1, "deal_id": 1,
                 "whatsapp_status": 1, "respondeu_em": 1},
    ).to_list(MAX_RESUMO)

    deal_ids = list({d["deal_id"] for d in docs if d.get("deal_id")})
    negocios: dict[str, dict] = {}
    for i in range(0, len(deal_ids), 1000):
        async for n in db.deals.find(
                {"tenant_id": tenant_id, "id": {"$in": deal_ids[i:i + 1000]}},
                {"_id": 0, "id": 1, "status": 1, "valor": 1}):
            negocios[n["id"]] = n

    def zero():
        return {"respostas": 0, "contatos_novos": 0, "negocios": 0,
                "ganhos": 0, "valor_ganho": 0.0}

    total = {**zero(), "recusadas": 0, "repetidas": 0, "whatsapp_enviados": 0,
             "whatsapp_falhas": 0, "responderam": 0}
    por_origem: dict[tuple, dict] = {}
    contados: set[str] = set()
    for d in docs:
        if d.get("status") == RECUSADA:
            total["recusadas"] += 1
            continue
        if d.get("status") == REPETIDA:
            total["repetidas"] += 1
            continue
        utm = d.get("utm") or {}
        chave = (utm.get("utm_source") or "", utm.get("utm_campaign") or "")
        linha = por_origem.setdefault(chave, zero())
        for alvo in (total, linha):
            alvo["respostas"] += 1
            alvo["contatos_novos"] += 1 if d.get("contato_novo") else 0
        if d.get("whatsapp_status") == WPP_ENVIADA:
            total["whatsapp_enviados"] += 1
        elif d.get("whatsapp_status") in (WPP_FALHA, WPP_SEM_MODELO):
            total["whatsapp_falhas"] += 1
        if d.get("respondeu_em"):
            total["responderam"] += 1
        n = negocios.get(d.get("deal_id"))
        # O mesmo negócio pode estar em duas respostas (a pessoa voltou): conta
        # uma vez, na primeira origem que o trouxe.
        if n and n["id"] not in contados:
            contados.add(n["id"])
            for alvo in (total, linha):
                alvo["negocios"] += 1
                if n.get("status") == "ganho":
                    alvo["ganhos"] += 1
                    alvo["valor_ganho"] += float(n.get("valor") or 0)

    linhas = [{"utm_source": k[0] or None, "utm_campaign": k[1] or None, **v}
              for k, v in por_origem.items()]
    linhas.sort(key=lambda x: (-x["valor_ganho"], -x["respostas"]))
    return {"total": total, "por_origem": linhas, "truncado": len(docs) >= MAX_RESUMO}
