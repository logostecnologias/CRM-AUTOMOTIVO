"""Camada única de chamada aos provedores de IA (Anthropic e OpenAI).

Mesmo papel que `wuzapi_client.py` tem para o WhatsApp: nenhuma outra parte do
backend fala com provedor de IA diretamente. Quem chama passa provedor, modelo
e credencial, e recebe sempre a mesma `Resposta` — com o texto e a contagem de
tokens já normalizada, porque é dela que sai a medição de consumo.

Decisões que valem registro:

  - **SDK oficial de cada provedor, não httpx cru.** O resto do projeto tem
    cliente próprio (WuzAPI não tem SDK), mas aqui os dois têm, e são eles que
    acertam a semântica de cache de prompt, os tipos de erro e o retry. O
    import é preguiçoso para o backend continuar subindo num ambiente onde só
    um dos dois (ou nenhum) esteja instalado.

  - **Um client por chamada, fechado no fim** — o oposto do
    `wuzapi_client._get_client()`. Lá o client é único do processo porque são
    muitas chamadas curtas pelo túnel; aqui a credencial é *de cada empresa*, e
    um pool compartilhado significaria manter chaves de clientes vivas num
    dicionário de módulo. O custo é um handshake TLS por resposta, contra 1-3s
    da própria chamada — irrelevante.

  - **Cache de prompt é parte do desenho, não otimização posterior.** O bloco
    de instruções + base de conhecimento é idêntico em toda chamada e responde
    por ~80% dos tokens de entrada. Sem cache a conta de um cliente de porte
    médio quase dobra. Na Anthropic isso é explícito (`cache_control` no bloco
    de sistema); na OpenAI é automático sobre o prefixo — por isso a instrução
    vai em `instructions`, estável, e o que varia fica no `input`.

  - **A contagem de tokens volta em toda resposta.** É o que permite cobrar por
    faixa de uso e mostrar consumo ao cliente. Ler isso depois, do provedor,
    seria uma segunda integração para reconstruir o que a chamada já disse.
"""
import logging
from dataclasses import dataclass, field

import ai_credentials

logger = logging.getLogger("zappzen.ia")


class IAError(Exception):
    """Falha ao falar com o provedor. A mensagem é exibida ao cliente, então
    não carrega credencial nem corpo bruto de resposta."""


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
#
# Lista curta de propósito. O provedor publica dezenas de modelos, e a maioria
# é cara demais ou lenta demais para responder WhatsApp — oferecer todos só
# transfere para o cliente uma decisão que ele não tem como tomar. Os preços
# ficam aqui (US$ por 1M de tokens) porque é o que permite mostrar o custo
# estimado na tela e medir o consumo real sem uma segunda tabela.

@dataclass(frozen=True)
class Modelo:
    id: str
    rotulo: str
    entrada: float          # US$/1M tokens
    saida: float            # US$/1M tokens
    cache_leitura: float    # US$/1M tokens lidos do cache
    cache_escrita: float    # US$/1M tokens gravados no cache (0 = sem custo extra)
    nota: str = ""


PROVEDORES: dict[str, dict] = {
    "anthropic": {
        "rotulo": "Anthropic (Claude)",
        # Link direto para a página de chaves — é o "abrir console" da tela de
        # conexão. Levar o cliente à home do provedor faria ele se perder.
        "console_url": "https://console.anthropic.com/settings/keys",
        "prefixo_chave": "sk-ant-",
        "modelos": [
            Modelo("claude-haiku-4-5", "Haiku 4.5", 1.00, 5.00, 0.10, 1.25,
                   "Recomendado para atendimento: rápido e barato."),
            Modelo("claude-sonnet-5", "Sonnet 5", 3.00, 15.00, 0.30, 3.75,
                   "Respostas mais elaboradas, ~3x o custo."),
        ],
    },
    "openai": {
        "rotulo": "OpenAI (GPT)",
        "console_url": "https://platform.openai.com/api-keys",
        "prefixo_chave": "sk-",
        "modelos": [
            Modelo("gpt-5-nano", "GPT-5 nano", 0.05, 0.40, 0.005, 0.0,
                   "O mais barato. Bom para triagem e perguntas frequentes."),
            Modelo("gpt-5-mini", "GPT-5 mini", 0.25, 2.00, 0.025, 0.0,
                   "Recomendado para atendimento: equilíbrio de custo e qualidade."),
            Modelo("gpt-5", "GPT-5", 1.25, 10.00, 0.125, 0.0,
                   "Melhor qualidade, ~5x o custo do mini."),
        ],
    },
}


def modelo_de(provedor: str, modelo_id: str) -> Modelo:
    for m in PROVEDORES.get(provedor, {}).get("modelos", []):
        if m.id == modelo_id:
            return m
    raise IAError(f"Modelo desconhecido para {provedor}: {modelo_id}")


def modelo_padrao(provedor: str) -> str:
    """O primeiro da lista é o recomendado — a ordem do catálogo é a
    recomendação, não alfabética."""
    modelos = PROVEDORES.get(provedor, {}).get("modelos", [])
    if not modelos:
        raise IAError(f"Provedor desconhecido: {provedor}")
    return modelos[0].id


def catalogo_publico() -> list[dict]:
    """O catálogo como a tela precisa dele. Sem segredo nenhum — é chamado por
    qualquer admin de empresa."""
    return [
        {
            "id": pid,
            "rotulo": p["rotulo"],
            "console_url": p["console_url"],
            "modelos": [
                {
                    "id": m.id,
                    "rotulo": m.rotulo,
                    "nota": m.nota,
                    "entrada": m.entrada,
                    "saida": m.saida,
                    # A tela projeta o custo mensal e precisa do preço de
                    # cache: assumir "10% da entrada" vale nos modelos atuais
                    # mas não é regra (o cache do gpt-4o custa 50%), e um dia
                    # a projeção mentiria em silêncio.
                    "cache_leitura": m.cache_leitura,
                }
                for m in p["modelos"]
            ],
        }
        for pid, p in PROVEDORES.items()
    ]


# ---------------------------------------------------------------------------
# Resposta
# ---------------------------------------------------------------------------

@dataclass
class Resposta:
    texto: str
    modelo: str
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0
    tokens_cache_escrita: int = 0
    bruto: dict = field(default_factory=dict)

    def custo_usd(self, modelo: Modelo) -> float:
        """Custo desta chamada. Separa cache de entrada normal porque a
        diferença é de 10x — somar tudo como entrada mostraria ao cliente um
        número que não bate com a fatura do provedor."""
        return (
            self.tokens_entrada * modelo.entrada
            + self.tokens_saida * modelo.saida
            + self.tokens_cache_leitura * modelo.cache_leitura
            + self.tokens_cache_escrita * modelo.cache_escrita
        ) / 1_000_000


# ---------------------------------------------------------------------------
# Chamada
# ---------------------------------------------------------------------------

# Teto de saída. Não é o tamanho esperado da resposta (~120 tokens numa
# resposta de atendimento) — é folga. Nos modelos GPT-5 o `max_output_tokens`
# inclui os tokens de raciocínio, que são invisíveis: um teto apertado é
# consumido inteiro pelo raciocínio e devolve resposta vazia com status
# `incomplete`. Sobra não custa nada, porque a cobrança é pelo que sai.
MAX_SAIDA = 2000


async def responder(
    provedor: str,
    chave_api: str,
    modelo_id: str,
    instrucoes: str,
    historico: list[dict],
) -> Resposta:
    """Uma resposta do agente.

    `instrucoes` é o bloco estável (papel do agente, regras, base de
    conhecimento) — é ele que vai para o cache. `historico` é a conversa em
    formato `[{"role": "user"|"assistant", "content": "..."}]`, com a mensagem
    nova do contato por último.
    """
    if not historico:
        raise IAError("Histórico vazio — não há o que responder")
    if provedor == "anthropic":
        return await _responder_anthropic(chave_api, modelo_id, instrucoes, historico)
    if provedor == "openai":
        return await _responder_openai(chave_api, modelo_id, instrucoes, historico)
    raise IAError(f"Provedor desconhecido: {provedor}")


async def _responder_anthropic(chave_api, modelo_id, instrucoes, historico) -> Resposta:
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        raise IAError("SDK da Anthropic não instalado no servidor (pip install anthropic)")

    async with AsyncAnthropic(api_key=chave_api, max_retries=2) as client:
        try:
            r = await client.messages.create(
                model=modelo_id,
                max_tokens=MAX_SAIDA,
                # Lista de blocos, não string, porque `cache_control` só existe
                # no formato de bloco. O prefixo mínimo para o cache pegar é de
                # ~1024 tokens: instrução mais curta que isso simplesmente não
                # é cacheada, sem erro nenhum — só não economiza.
                system=[{
                    "type": "text",
                    "text": instrucoes,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=historico,
            )
        except Exception as e:
            raise IAError(_traduz_erro(e))

    # `content` é uma união de blocos; num modelo sem thinking vem só texto,
    # mas filtrar por tipo é o que impede um KeyError se isso mudar.
    texto = "".join(b.text for b in r.content if getattr(b, "type", None) == "text").strip()
    if not texto:
        raise IAError("O modelo respondeu vazio")

    u = r.usage
    return Resposta(
        texto=texto,
        modelo=modelo_id,
        tokens_entrada=getattr(u, "input_tokens", 0) or 0,
        tokens_saida=getattr(u, "output_tokens", 0) or 0,
        tokens_cache_leitura=getattr(u, "cache_read_input_tokens", 0) or 0,
        tokens_cache_escrita=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


async def _responder_openai(chave_api, modelo_id, instrucoes, historico) -> Resposta:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise IAError("SDK da OpenAI não instalado no servidor (pip install openai)")

    async with AsyncOpenAI(api_key=chave_api, max_retries=2) as client:
        try:
            r = await client.responses.create(
                model=modelo_id,
                # `instructions` fica fora do `input` e é estável entre as
                # chamadas — é assim que o cache automático da OpenAI pega o
                # prefixo. Enfiar as instruções como primeira mensagem do
                # `input` funcionaria, mas embaralharia o prefixo com o
                # histórico, que muda a cada turno.
                instructions=instrucoes,
                input=historico,
                max_output_tokens=MAX_SAIDA,
                # Os GPT-5 são modelos de raciocínio. Para atendimento isso é
                # custo e latência sem retorno: a resposta é curta e a decisão
                # é simples. `low` é o piso útil.
                reasoning={"effort": "low"},
            )
        except Exception as e:
            raise IAError(_traduz_erro(e))

    if getattr(r, "status", None) == "incomplete":
        motivo = getattr(getattr(r, "incomplete_details", None), "reason", "desconhecido")
        raise IAError(f"Resposta truncada pelo provedor ({motivo})")

    texto = (getattr(r, "output_text", "") or "").strip()
    if not texto:
        raise IAError("O modelo respondeu vazio")

    u = getattr(r, "usage", None)
    cacheados = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    entrada = getattr(u, "input_tokens", 0) or 0
    return Resposta(
        texto=texto,
        modelo=modelo_id,
        # A OpenAI reporta `input_tokens` como o total, com os cacheados
        # *dentro* dele. A Anthropic reporta os dois separados. Descontar aqui
        # é o que faz `custo_usd` valer para os dois sem um `if` de provedor.
        tokens_entrada=max(entrada - cacheados, 0),
        tokens_cache_leitura=cacheados,
        tokens_saida=getattr(u, "output_tokens", 0) or 0,
    )


def _traduz_erro(e: Exception) -> str:
    """Mensagem que o cliente entende, a partir do erro do SDK.

    O texto vai direto para a tela dele, então "401 Unauthorized" não serve:
    quem cadastrou a chave precisa saber se o problema é a chave, o saldo ou
    o volume."""
    nome = type(e).__name__
    status = getattr(e, "status_code", None)
    if status == 401 or "Authentication" in nome:
        return "Chave de API recusada pelo provedor. Confira se copiou a chave inteira e se ela não foi revogada."
    if status == 402 or "credit" in str(e).lower() or "quota" in str(e).lower():
        return "A conta no provedor está sem saldo ou sem cota. Adicione créditos e tente de novo."
    if status == 404:
        return "Modelo indisponível para esta conta. Alguns modelos exigem um nível de acesso que a conta ainda não tem."
    if status == 429 or "RateLimit" in nome:
        return "O provedor está limitando as chamadas desta conta no momento. Tente novamente em instantes."
    if status and status >= 500:
        return "O provedor está fora do ar no momento. Tente novamente em instantes."
    logger.warning("Erro não mapeado do provedor de IA: %s: %s", nome, e)
    return f"Falha ao falar com o provedor de IA ({nome})."


# ---------------------------------------------------------------------------
# Validação (o "testar conexão" da tela)
# ---------------------------------------------------------------------------

async def validar(provedor: str, chave_api: str, modelo_id: str) -> Resposta:
    """Chamada mínima só para provar que a credencial funciona *neste* modelo.

    Vale mais que uma checagem de formato: uma chave pode ser válida e mesmo
    assim não ter saldo, não ter acesso ao modelo escolhido ou estar revogada —
    e o cliente precisa descobrir isso agora, com a tela aberta, não na
    primeira mensagem de um contato real.

    Custa fração de centavo: é o menor prompt possível e uma resposta de uma
    palavra.
    """
    return await responder(
        provedor,
        chave_api,
        modelo_id,
        instrucoes="Responda exatamente: ok",
        historico=[{"role": "user", "content": "ok"}],
    )


async def validar_conexao(conexao: dict) -> Resposta:
    """Mesma coisa, a partir do documento guardado (decifrando a chave)."""
    return await validar(
        conexao["provedor"],
        ai_credentials.decifrar(conexao.get("credencial") or {}),
        conexao["modelo"],
    )
