"""Tabela FIPE: o valor de referência de um veículo.

Pedido do Atalaia (24/11/2026). Dois usos:

  - **Na ficha do carro do estoque**: a loja liga o carro ao modelo FIPE uma
    vez (marca → modelo → ano), e a ficha mostra o valor de referência e a
    diferença para o preço ("R$ 6 mil abaixo da FIPE").
  - **Pela IA, para o carro do cliente na troca**: "quanto vale meu Onix 2019?".
    A IA consulta e responde com a referência, e o prompt diz que a avaliação
    de verdade é presencial: FIPE não é proposta de compra.

A FIPE não tem API oficial. Esta é a da Parallelum (`fipe.parallelum.com.br`,
v2), que espelha a tabela todo mês. Sem token ela dá **500 consultas por dia
para o servidor inteiro**; com `FIPE_TOKEN` (cadastro gratuito em fipe.online)
o teto sobe. Por isso tudo é guardado em memória: marcas, modelos e anos por
uma semana (só mudam quando entra modelo novo), preço por um dia (a tabela
muda uma vez por mês). Um processo só (ver deploy), então cache em memória
basta.

O ano `32000` é o código da FIPE para **zero km**.
"""
import logging
import os
import re
import time
import unicodedata

import httpx

logger = logging.getLogger(__name__)

BASE = "https://fipe.parallelum.com.br/api/v2"
TIPOS = {"carro": "cars", "moto": "motorcycles", "caminhao": "trucks"}
ZERO_KM = "32000"
TTL_LISTA = 7 * 24 * 3600
TTL_PRECO = 24 * 3600
MAX_CANDIDATOS = 4
# Acima disto a busca não consulta preço: devolve as versões para perguntar.
MAX_VERSOES = 8

_cache: dict[str, tuple[float, object]] = {}
_client: httpx.AsyncClient | None = None


class FipeError(Exception):
    pass


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0))
    return _client


async def close_client():
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _get(caminho: str, ttl: int):
    agora = time.monotonic()
    guardado = _cache.get(caminho)
    if guardado and guardado[0] > agora:
        return guardado[1]
    headers = {}
    token = (os.environ.get("FIPE_TOKEN") or "").strip()
    if token:
        headers["X-Subscription-Token"] = token
    try:
        r = await _get_client().get(f"{BASE}{caminho}", headers=headers)
    except httpx.HTTPError as e:
        raise FipeError(f"A consulta à tabela FIPE não respondeu ({e.__class__.__name__})")
    if r.status_code == 429:
        raise FipeError("Limite diário de consultas à tabela FIPE atingido. Tente amanhã "
                        "ou configure FIPE_TOKEN no servidor.")
    if r.status_code == 404:
        dados = None
    elif r.status_code >= 400:
        raise FipeError(f"A tabela FIPE recusou a consulta ({r.status_code})")
    else:
        dados = r.json()
        if isinstance(dados, dict) and dados.get("error"):
            dados = None
    _cache[caminho] = (agora + ttl, dados)
    return dados


def _tipo(tipo: str) -> str:
    if tipo not in TIPOS:
        raise FipeError("Tipo de veículo inválido")
    return TIPOS[tipo]


def _id(valor) -> str:
    v = str(valor or "")
    if not re.fullmatch(r"[0-9A-Za-z-]{1,20}", v):
        raise FipeError("Código FIPE inválido")
    return v


async def marcas(tipo: str = "carro") -> list[dict]:
    dados = await _get(f"/{_tipo(tipo)}/brands", TTL_LISTA) or []
    return [{"id": d["code"], "nome": d["name"]} for d in dados]


async def modelos(tipo: str, marca_id) -> list[dict]:
    dados = await _get(f"/{_tipo(tipo)}/brands/{_id(marca_id)}/models", TTL_LISTA) or []
    return [{"id": d["code"], "nome": d["name"]} for d in dados]


def _nome_ano(d: dict) -> str:
    nome = d.get("name") or d["code"]
    return nome.replace(ZERO_KM, "Zero km", 1) if str(d["code"]).startswith(ZERO_KM) else nome


async def anos(tipo: str, marca_id, modelo_id) -> list[dict]:
    dados = await _get(f"/{_tipo(tipo)}/brands/{_id(marca_id)}/models/{_id(modelo_id)}/years",
                       TTL_LISTA) or []
    # Mais novo primeiro, zero km no topo: é o que se procura quase sempre.
    dados = sorted(dados, key=lambda d: str(d["code"]), reverse=True)
    return [{"id": d["code"], "nome": _nome_ano(d)} for d in dados]


def _reais(texto: str) -> float | None:
    d = re.sub(r"[^\d,]", "", texto or "").replace(",", ".")
    try:
        return float(d) if d else None
    except ValueError:
        return None


async def preco(tipo: str, marca_id, modelo_id, ano_id) -> dict | None:
    dados = await _get(f"/{_tipo(tipo)}/brands/{_id(marca_id)}/models/{_id(modelo_id)}"
                       f"/years/{_id(ano_id)}", TTL_PRECO)
    if not dados:
        return None
    ano = dados.get("modelYear")
    return {
        "valor": _reais(dados.get("price")),
        "codigo": dados.get("codeFipe"),
        "referencia": dados.get("referenceMonth"),
        "marca": dados.get("brand"),
        "modelo": dados.get("model"),
        "ano": "Zero km" if str(ano) == ZERO_KM else ano,
        "combustivel": dados.get("fuel"),
        "tipo": tipo, "marca_id": str(marca_id), "modelo_id": str(modelo_id), "ano_id": str(ano_id),
    }


# ---------------------------------------------------------------------------
# Busca por texto: o caminho da IA, que tem "onix 2019", não códigos
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9.]+", " ", s).strip()


APELIDOS = {"vw": "volkswagen", "volks": "volkswagen", "gm": "chevrolet", "chevy": "chevrolet",
            "mercedes": "mercedes-benz", "mb": "mercedes-benz", "citroen": "citroen"}


async def achar_marca(tipo: str, texto: str) -> dict | None:
    alvo = _norm(APELIDOS.get(_norm(texto), texto))
    if not alvo:
        return None
    lista = await marcas(tipo)
    exata = [m for m in lista if _norm(m["nome"]) == alvo]
    if exata:
        return exata[0]
    contem = [m for m in lista if alvo in _norm(m["nome"]).split() or _norm(m["nome"]).startswith(alvo)]
    return contem[0] if len(contem) == 1 else None


async def buscar(tipo: str, marca: str, modelo: str, ano: int | None = None,
                 combustivel: str | None = None) -> dict:
    """Os modelos FIPE que casam com o texto, com o preço do ano pedido.

    Devolve {"marca", "itens": [...], "total": n}. `total` é quantos modelos
    casaram; só os `MAX_CANDIDATOS` primeiros são consultados, porque cada um
    custa duas idas à API e o teto diário é do servidor inteiro.
    """
    m = await achar_marca(tipo, marca)
    if not m:
        return {"marca": None, "itens": [], "total": 0, "versoes": []}
    termos = _norm(modelo).split()
    lista = await modelos(tipo, m["id"])
    casados = [x for x in lista if termos and all(t in _norm(x["nome"]).split()
                                                  or t in _norm(x["nome"]) for t in termos)]
    if combustivel:
        c = _norm(combustivel)
        filtrados = [x for x in casados if c in _norm(x["nome"])]
        casados = filtrados or casados
    if len(casados) > MAX_VERSOES:
        # Versões demais para consultar uma a uma (o Onix tem dezenas): quem
        # chamou mostra os nomes e pergunta motor ou versão.
        return {"marca": m["nome"], "itens": [], "total": len(casados),
                "versoes": [x["nome"] for x in casados[:12]]}
    itens = []
    for x in casados:
        if len(itens) >= MAX_CANDIDATOS:
            break
        anos_x = await anos(tipo, m["id"], x["id"])
        if ano:
            escolhidos = [a for a in anos_x if str(a["id"]).startswith(f"{ano}-")]
        else:
            escolhidos = [a for a in anos_x if not str(a["id"]).startswith(ZERO_KM)][:1]
        for a in escolhidos[:1]:
            p = await preco(tipo, m["id"], x["id"], a["id"])
            if p and p["valor"]:
                itens.append(p)
    return {"marca": m["nome"], "itens": itens, "total": len(casados), "versoes": []}


def formatar(n: float | None) -> str:
    if n is None:
        return "—"
    return "R$ " + f"{n:,.0f}".replace(",", ".")
