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

RE_CARRO = re.compile(r"\[\s*CARRO\s*:\s*([A-Za-z0-9]{4,12})\s*\]", re.IGNORECASE)
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
    "resposta; o sistema troca o código pelas fotos DESSE carro. Use só códigos que a "
    "consulta devolveu nesta conversa, do carro de que você está falando. Se a consulta "
    "disser 'sem foto', diga que ainda não tem foto daquele carro. Mande fotos quando o "
    "cliente pedir ou quando mostrar for o passo natural, não a cada mensagem. Nunca "
    "explique o código ao cliente."
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

    async def executar(nome: str, argumentos: dict) -> str:
        if nome != "consultar_estoque":
            return f"ERRO: ferramenta desconhecida ({nome})."
        return await consultar(argumentos or {})

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
        c = achado.group(1).upper()
        if c not in codigos:
            codigos.append(c)
    limpo = RE_CARRO.sub("", texto)
    limpo = re.sub(r"[ \t]{2,}", " ", limpo)
    limpo = re.sub(r" +([,.;:!?])", r"\1", limpo)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo).strip()
    if not codigos:
        return limpo, []

    por_codigo = {codigo(v): v for v in await _a_venda(db, tenant_id)}
    carros = [por_codigo[c] for c in codigos if c in por_codigo and por_codigo[c].get("fotos")]
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


async def fotos_por_midia(db, tenant_id: str) -> dict[str, str]:
    """media_id -> código do carro, para o histórico mostrar à IA quais fotos
    ela já mandou (`ai_agents.montar_historico`)."""
    mapa = {}
    async for v in db.veiculos.find({"tenant_id": tenant_id}, {"_id": 0, "id": 1, "fotos": 1}):
        for m in v.get("fotos") or []:
            mapa[m] = codigo(v)
    return mapa
