"""O estoque de veículos (tela de Estoque) como a única fonte da IA sobre carros.

Substitui, para a empresa que tem veículos cadastrados, as duas fontes antigas
que o agente usava: a planilha subida na tela de treino (`ai_estoque`) e o
catálogo de fotos com descrição (`agente.midias`). As duas erravam pelo mesmo
motivo: o vínculo entre o carro e o que se dizia dele era texto solto.

  - **Preço, ano, km e situação vêm de uma consulta por ferramenta**
    (`consultar_estoque`), feita na hora sobre `veiculos`. Vendido não aparece;
    reservado aparece marcado como tal. Mudou na tela de Estoque, a IA já
    responde com o valor novo, sem subir planilha.

  - **A foto é pedida pelo carro, não por número de foto.** Cada carro da
    consulta vem com um código (`[CARRO:AB12CD]`), e a etiqueta manda as fotos
    DAQUELE carro. Antes a foto era escolhida por um número numa lista de
    descrições ("Argo drive 2025" ×4, para três Argos): errar um dígito ou
    pegar a descrição parecida mandava foto de outro carro.

  - **A placa não vai para a IA.** É dado da loja, não do anúncio; o código do
    carro é um pedaço do id, que não diz nada a ninguém.

Quando a empresa não tem nenhum veículo cadastrado, nada muda: valem a
planilha e o catálogo de fotos, como antes.
"""
import re
import unicodedata

import ai_client

# Aceita qualquer coisa dentro da etiqueta: o modelo que não chamou a consulta
# inventa o código a partir do nome ("[CARRO:STRADA_FREEDOM]"), e um padrão só
# de código válido deixava a etiqueta escrita na bolha do contato.
RE_CARRO = re.compile(r"\[\s*CARRO\s*:\s*([^\]\n]{1,60}?)\s*\]", re.IGNORECASE)
MAX_FOTOS_POR_RESPOSTA = 5
LIMITE_BUSCA = 8

ROTULOS = {
    "cambio": {"manual": "manual", "automatico": "automático", "cvt": "CVT", "automatizado": "automatizado"},
    "combustivel": {"flex": "flex", "gasolina": "gasolina", "etanol": "etanol", "diesel": "diesel",
                    "hibrido": "híbrido", "eletrico": "elétrico", "gnv": "GNV"},
    "categoria": {"hatch": "hatch", "sedan": "sedã", "suv": "SUV", "picape": "picape", "minivan": "minivan",
                  "esportivo": "esportivo", "utilitario": "utilitário", "moto": "moto"},
}


def codigo(v: dict) -> str:
    """O código que a IA usa para pedir as fotos de um carro."""
    return (v.get("id") or "").replace("-", "")[:6].upper()


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                   if unicodedata.category(c) != "Mn").lower()


def _reais(n) -> str:
    return "R$ " + f"{float(n):,.0f}".replace(",", ".")


def descreve(v: dict) -> str:
    """Uma linha por carro, só com o que o vendedor pode dizer ao cliente."""
    partes = [" ".join(p for p in (v.get("marca"), v.get("modelo"), v.get("versao")) if p)]
    ano = v.get("ano_modelo") or v.get("ano_fabricacao")
    if v.get("ano_fabricacao") and v.get("ano_modelo") and v["ano_fabricacao"] != v["ano_modelo"]:
        ano = f"{v['ano_fabricacao']}/{v['ano_modelo']}"
    if ano:
        partes.append(f"ano {ano}")
    if v.get("km") is not None:
        partes.append(f"{v['km']:,} km".replace(",", "."))
    if v.get("cor"):
        partes.append(f"cor {v['cor'].lower()}")
    for campo in ("cambio", "combustivel", "categoria"):
        if v.get(campo):
            partes.append(ROTULOS[campo].get(v[campo], v[campo]))
    if v.get("preco"):
        preco = f"preço {_reais(v['preco'])}"
        if v.get("preco_anterior") and v["preco_anterior"] > v["preco"]:
            preco += f" (promoção: era {_reais(v['preco_anterior'])})"
        partes.append(preco)
    else:
        partes.append("preço: sob consulta (não informe valor; transfira se insistirem)")
    f = v.get("fipe") or {}
    if f.get("valor"):
        partes.append(f"tabela FIPE {_reais(f['valor'])}"
                      + (f" (referência {f['referencia']})" if f.get("referencia") else ""))
    if v.get("opcionais"):
        partes.append("opcionais: " + ", ".join(v["opcionais"]))
    if v.get("observacoes"):
        partes.append("observações: " + " ".join(v["observacoes"].split()))
    situacao = "RESERVADO para outro cliente (não ofereça como disponível)" if v.get("status") == "reservado" \
        else "disponível"
    partes.append(situacao)
    n = len(v.get("fotos") or [])
    partes.append(f"{n} foto{'s' if n != 1 else ''}" if n else "sem foto")
    return f"[CARRO:{codigo(v)}] " + "; ".join(partes)


async def ativo(db, tenant_id: str) -> bool:
    """A empresa usa a tela de Estoque? Basta um veículo cadastrado."""
    return bool(await db.veiculos.find_one({"tenant_id": tenant_id}, {"_id": 0, "id": 1}))


async def _a_venda(db, tenant_id: str) -> list[dict]:
    return await db.veiculos.find(
        {"tenant_id": tenant_id, "status": {"$in": ["disponivel", "reservado"]}}, {"_id": 0}).to_list(5000)


async def buscar(db, tenant_id: str, busca: str = "", preco_max=None, limite: int = LIMITE_BUSCA):
    veiculos = await _a_venda(db, tenant_id)
    termos = [t for t in _sem_acento(busca).split() if t]
    if preco_max:
        veiculos = [v for v in veiculos if v.get("preco") and v["preco"] <= float(preco_max)]

    def alvo(v):
        extras = [ROTULOS[c].get(v.get(c) or "", "") for c in ROTULOS]
        return _sem_acento(" ".join(str(v.get(c) or "") for c in
                                    ("marca", "modelo", "versao", "cor", "ano_modelo", "ano_fabricacao"))
                           + " " + " ".join(extras))

    if termos:
        # Todas as palavras primeiro; se nenhum carro tiver todas, os que têm
        # mais delas ("onix prata" acha o Onix prata; sem Onix prata, os Onix).
        pontuados = [(sum(t in alvo(v) for t in termos), v) for v in veiculos]
        completos = [v for p, v in pontuados if p == len(termos)]
        if completos:
            veiculos = completos
        else:
            melhor = max((p for p, _ in pontuados), default=0)
            veiculos = [v for p, v in pontuados if p == melhor and p > 0]
    # Disponível antes de reservado; dentro disso, destaque e depois o mais barato.
    veiculos.sort(key=lambda v: (v.get("status") != "disponivel", not v.get("destaque"), v.get("preco") or 0))
    return veiculos[:limite], len(veiculos)


FERRAMENTAS = [
    ai_client.Ferramenta(
        nome="consultar_estoque",
        descricao=(
            "Procura os carros à venda no estoque da loja. Use SEMPRE antes de dizer que um "
            "carro existe, está disponível, quanto custa, o ano, a km ou qualquer detalhe "
            "dele: você não sabe o estoque sem chamar isto. Passe as palavras que o cliente "
            "usou (modelo, marca, ano, cor, câmbio, tipo como 'suv' ou 'picape'). Para 'até "
            "tal valor', passe preco_max. Sem nada, devolve os primeiros carros."
        ),
        parametros={
            "type": "object",
            "properties": {
                "busca": {"type": "string",
                          "description": "Palavras do carro procurado, ex.: 'argo branco 2025', 'suv automático', 'hilux'."},
                "preco_max": {"type": "number",
                              "description": "Preço máximo em reais, ex.: 80000. Só quando o cliente der um teto."},
            },
            "required": [],
        },
    ),
    ai_client.Ferramenta(
        nome="consultar_fipe",
        descricao=(
            "Consulta o valor de referência da tabela FIPE de um veículo, normalmente o "
            "carro que o cliente quer dar na troca. Passe a marca, o modelo (com motor ou "
            "versão quando souber, ex.: 'onix 1.0 lt') e o ano do modelo. Se voltar uma "
            "lista de versões, pergunte ao cliente qual é a dele."
        ),
        parametros={
            "type": "object",
            "properties": {
                "marca": {"type": "string", "description": "Ex.: 'chevrolet', 'fiat', 'vw'."},
                "modelo": {"type": "string", "description": "Ex.: 'onix 1.0 lt', 'strada freedom 1.3'."},
                "ano": {"type": "integer", "description": "Ano do modelo, ex.: 2019. Omita para zero km."},
                "tipo": {"type": "string", "enum": ["carro", "moto", "caminhao"],
                         "description": "Padrão: carro."},
            },
            "required": ["marca", "modelo"],
        },
    ),
]


INSTRUCOES = (
    "Estoque de carros: a loja tem um estoque cadastrado, e ele é a sua ÚNICA fonte sobre "
    "os carros. Consulte com a ferramenta consultar_estoque sempre que a conversa envolver "
    "um carro: se existe, preço, ano, km, cor, câmbio, opcionais, situação. Fale de cada "
    "carro só o que a consulta devolveu, com os números exatamente como vieram. Se em "
    "qualquer outro lugar destas instruções (base de conhecimento, ensinamentos, "
    "documentos) houver preço, ano ou disponibilidade de carro, ignore: pode estar "
    "desatualizado, e o que vale é a consulta de agora. Carro que a consulta não "
    "encontrar, a loja não tem: diga isso e ofereça o mais parecido que ela devolver. "
    "Carro marcado RESERVADO não está disponível: diga que está reservado e ofereça "
    "outro. Nunca diga quantos carros existem no estoque nem leia a lista inteira.\n"
    "Fotos: cada carro da consulta começa com um código, como [CARRO:AB12CD]. Para "
    "mandar as fotos de um carro, escreva o código dele exatamente assim dentro da sua "
    "resposta; o sistema troca o código pelas fotos DESSE carro. O código são 6 letras e "
    "números que só a consulta informa: nunca o monte com o nome do carro (como "
    "[CARRO:STRADA_FREEDOM]). Sem ter chamado consultar_estoque nesta resposta ou antes "
    "nesta conversa, você não tem código: chame a consulta primeiro. Use só códigos que a "
    "consulta devolveu, do carro de que você está falando. Se a consulta "
    "disser 'sem foto', diga que ainda não tem foto daquele carro. Mande fotos quando o "
    "cliente pedir ou quando mostrar for o passo natural, não a cada mensagem. Nunca "
    "explique o código ao cliente.\n"
    "Tabela FIPE: a consulta do estoque traz a FIPE dos carros que a loja ligou a ela; use "
    "para mostrar vantagem (ex.: abaixo da FIPE), com o valor exatamente como veio. Para o "
    "carro que o cliente quer dar na troca, use consultar_fipe. A FIPE é só referência de "
    "mercado: NUNCA diga que a loja paga esse valor nem faça proposta pelo carro do "
    "cliente; diga que a avaliação é feita pela equipe, ao ver o carro."
)


def executor(db, tenant_id: str):
    async def consultar(args: dict) -> str:
        preco_max = args.get("preco_max")
        try:
            preco_max = float(preco_max) if preco_max not in (None, "") else None
        except (TypeError, ValueError):
            preco_max = None
        veiculos, total = await buscar(db, tenant_id, args.get("busca") or "", preco_max)
        if not veiculos:
            return ("Nenhum carro à venda corresponde a essa busca. Tente outras palavras "
                    "ou pergunte ao cliente o que exatamente ele procura.")
        texto = "\n".join(f"- {descreve(v)}" for v in veiculos)
        if total > len(veiculos):
            texto += (f"\n(Mostrando {len(veiculos)} de {total}. Se precisar, peça ao cliente "
                      "mais detalhes para refinar a busca.)")
        return texto

    async def consultar_tabela(args: dict) -> str:
        import fipe
        tipo = args.get("tipo") if args.get("tipo") in fipe.TIPOS else "carro"
        try:
            ano = int(args["ano"]) if args.get("ano") not in (None, "") else None
        except (TypeError, ValueError):
            ano = None
        try:
            r = await fipe.buscar(tipo, args.get("marca") or "", args.get("modelo") or "", ano)
        except fipe.FipeError as e:
            return f"A tabela FIPE não respondeu agora ({e}). Diga que a equipe confirma o valor."
        if not r["marca"]:
            return "Marca não encontrada na tabela FIPE. Pergunte a marca ao cliente."
        if r["versoes"]:
            return (f"Há {r['total']} versões de {r['marca']} que casam com isso. Pergunte ao "
                    "cliente motor e versão. Algumas: " + "; ".join(r["versoes"]) + ".")
        if not r["itens"]:
            return ("Nada na tabela FIPE para esse modelo" + (f" no ano {ano}" if ano else "")
                    + ". Confirme com o cliente o modelo, a versão e o ano.")
        linhas = [f"- {i['marca']} {i['modelo']} {i['ano']} ({i['combustivel']}): "
                  f"FIPE {_reais(i['valor'])}, referência {i['referencia']}" for i in r["itens"]]
        return "\n".join(linhas)

    async def executar(nome: str, argumentos: dict) -> str:
        if nome == "consultar_estoque":
            return await consultar(argumentos or {})
        if nome == "consultar_fipe":
            return await consultar_tabela(argumentos or {})
        return f"ERRO: ferramenta desconhecida ({nome})."

    return executar


async def extrair_fotos(db, tenant_id: str, texto: str) -> tuple[str, list[dict]]:
    """Troca as etiquetas `[CARRO:código]` pelas fotos daquele carro.

    Devolve o texto limpo e os documentos de mídia a enviar, na ordem do
    carro (a capa primeiro). Vários carros na mesma resposta dividem o teto de
    fotos. Código que não é de nenhum carro à venda some em silêncio: é melhor
    a frase sem foto do que a etiqueta escrita na bolha, ou a foto de um carro
    vendido.
    """
    if not texto:
        return texto, []
    codigos = []
    for achado in RE_CARRO.finditer(texto):
        c = achado.group(1).strip()
        if c not in codigos:
            codigos.append(c)
    limpo = RE_CARRO.sub("", texto)
    limpo = re.sub(r"[ \t]{2,}", " ", limpo)
    limpo = re.sub(r" +([,.;:!?])", r"\1", limpo)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo).strip()
    if not codigos:
        return limpo, []

    a_venda = await _a_venda(db, tenant_id)
    por_codigo = {codigo(v): v for v in a_venda}
    carros = []
    for c in codigos:
        v = por_codigo.get(c.upper())
        if v is None:
            # Código inventado a partir do nome: procura pelo nome, e só aceita
            # se ele apontar para um carro só. Dois Strada possíveis = nenhuma
            # foto, que é melhor que a foto do carro errado.
            achados, total = await buscar(db, tenant_id, re.sub(r"[_\-]+", " ", c), limite=2)
            termos = [t for t in _sem_acento(c.replace("_", " ")).split() if t]
            if total == 1 and termos and all(
                    t in _sem_acento(f"{achados[0].get('modelo')} {achados[0].get('versao')} "
                                     f"{achados[0].get('marca')}") for t in termos):
                v = achados[0]
        if v and v.get("fotos") and v not in carros:
            carros.append(v)
    if not carros:
        return limpo, []
    cota = max(1, MAX_FOTOS_POR_RESPOSTA // len(carros))
    docs = []
    for v in carros:
        for media_id in v["fotos"][:cota]:
            if len(docs) >= MAX_FOTOS_POR_RESPOSTA:
                break
            doc = await db.media_files.find_one({"id": media_id, "tenant_id": tenant_id}, {"_id": 0})
            if doc and not doc.get("purged_at"):
                docs.append(doc)
    return limpo, docs


# ---------------------------------------------------------------------------
# Trava de preço: a resposta só sai com preço que a consulta devolveu
# ---------------------------------------------------------------------------
#
# Caso real (Atalaia, 24/11/2026, Haiku): o agente respondeu sem chamar
# `consultar_estoque`, com preço de uma planilha antiga que estava no treino, e
# inventou o código da foto. A instrução no prompt já dizia para consultar; o
# modelo ignorou. Por isso a conferência é no código, como `confirmou_sem_agenda`.
#
# Só valores a partir de `PRECO_MINIMO_CARRO` são conferidos: abaixo disso é
# parcela, documentação, taxa, que não são preço de carro e não estão no
# estoque. Entrada alta ("entrada de R$ 20 mil") cai na conferência e é
# segurada: é o erro aceito, porque o outro é prometer um carro por um preço
# que a loja não pratica.

PRECO_MINIMO_CARRO = 15000
TOLERANCIA = 0.01  # "79,9 mil" para R$ 79.900; arredondamento, não outro preço
NOME_FERRAMENTA = "consultar_estoque"

AVISO_PRECO = ("Deixa eu confirmar os valores certinhos com a equipe e já te "
               "retorno por aqui, tudo bem?")

_RE_VALOR = re.compile(
    r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(?:\s*(mil)\b)?"
    r"|\b(\d{1,3}(?:[.,]\d{1,3})?)\s*mil\b",
    re.IGNORECASE)


def valores_citados(texto: str) -> list[float]:
    """Os valores em reais que o texto cita ("R$ 79.900", "R$ 79,9 mil", "80 mil")."""
    valores = []
    for m in _RE_VALOR.finditer(texto or ""):
        try:
            if m.group(1):
                inteiro = float(m.group(1).replace(".", ""))
                decimal = m.group(2)
                if m.group(3):  # "R$ 79,9 mil"
                    v = float(f"{m.group(1).replace('.', '')}.{decimal or 0}") * 1000
                else:
                    v = inteiro + (float(f"0.{decimal}") if decimal else 0)
            else:
                bruto = m.group(4)
                # "79,9 mil" e "79.9 mil" são decimais; "1.200 mil" não existe aqui.
                v = float(bruto.replace(",", ".")) * 1000
        except ValueError:
            continue
        valores.append(v)
    return valores


def registrar_consultas(executar):
    """Embrulha o executor para guardar os códigos que `consultar_estoque`
    devolveu nesta resposta. Mesmo desenho de `ai_agents.registrar_marcacao`:
    o laço de ferramentas roda dentro do `ai_client`, então o registro é uma
    lista mutável."""
    vistos: list[str] = []
    if executar is None:
        return None, vistos

    async def embrulhado(nome: str, argumentos: dict) -> str:
        resultado = await executar(nome, argumentos)
        if nome == NOME_FERRAMENTA:
            vistos.extend(m.group(1).upper() for m in RE_CARRO.finditer(str(resultado)))
            vistos.append("")  # marca que houve consulta, mesmo sem carro achado
        elif nome == "consultar_fipe":
            # Os valores FIPE que a consulta devolveu também podem ser citados.
            vistos.extend(f"R$:{v}" for v in valores_citados(str(resultado)))
        return resultado

    return embrulhado, vistos


async def conferir(db, tenant_id: str, texto: str, vistos: list[str]) -> str | None:
    """Por que a resposta não pode sair, ou None se está de acordo com o estoque.

    - preço de carro citado sem consulta nesta resposta;
    - preço que não é o de nenhum carro devolvido pela consulta;
    - etiqueta de foto com código que não é de carro nenhum à venda.
    """
    consultou = bool(vistos)
    a_venda = None

    codigos = [m.group(1).strip().upper() for m in RE_CARRO.finditer(texto or "")]
    if codigos:
        a_venda = await _a_venda(db, tenant_id)
        validos = {codigo(v) for v in a_venda}
        invalidos = [c for c in codigos if c not in validos]
        if invalidos:
            return f"etiqueta de foto com código que não existe no estoque ({', '.join(invalidos)})"

    precos = [v for v in valores_citados(texto) if v >= PRECO_MINIMO_CARRO]
    if not precos:
        return None
    if not consultou:
        return "citou preço de carro sem consultar o estoque"
    if a_venda is None:
        a_venda = await _a_venda(db, tenant_id)
    por_codigo = {codigo(v): v for v in a_venda}
    permitidos = [float(c[3:]) for c in vistos if c.startswith("R$:")]
    for c in vistos:
        v = por_codigo.get(c)
        if v:
            permitidos += [p for p in (v.get("preco"), v.get("preco_anterior"),
                                       (v.get("fipe") or {}).get("valor")) if p]
    errados = [p for p in precos
               if not any(abs(p - q) <= q * TOLERANCIA for q in permitidos)]
    if errados:
        return ("citou preço que não é o de nenhum carro consultado ("
                + ", ".join(_reais(p) for p in errados) + ")")
    return None


async def fotos_por_midia(db, tenant_id: str) -> dict[str, str]:
    """media_id -> código do carro, para o histórico mostrar à IA quais fotos
    ela já mandou (`ai_agents.montar_historico`)."""
    mapa = {}
    async for v in db.veiculos.find({"tenant_id": tenant_id}, {"_id": 0, "id": 1, "fotos": 1}):
        for m in v.get("fotos") or []:
            mapa[m] = codigo(v)
    return mapa
