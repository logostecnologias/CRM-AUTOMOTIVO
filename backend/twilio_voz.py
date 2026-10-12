"""Camada única de conversa com o Twilio, mesmo papel do `whatsapp_client.py`.

O Twilio entra no sistema por um motivo só: atender a ligação que o cliente
não atendeu e transformá-la numa conversa de WhatsApp. Ele não fala com o
contato por voz além de uma gravação e uma tecla, não transfere ligação e não
manda SMS. Por isso a camada é pequena, e é bom que continue: tudo que diz
respeito à conversa depois da tecla é do ZappZen, não do Twilio.

Três partes, e só elas falam o idioma do Twilio:

  - **A assinatura** (`X-Twilio-Signature`). É o que prova que o POST veio do
    Twilio. Sem ela, qualquer pessoa que descobrisse o endereço faria o sistema
    mandar WhatsApp, em nome da empresa, para números escolhidos por ela: a
    tecla 1 é exatamente "mande mensagem para este número".

  - **As instruções da ligação** (TwiML). A resposta ao webhook é um XML que
    diz ao Twilio o que fazer: tocar, esperar tecla, desligar.

  - **A configuração do número**, feita uma vez, quando a empresa cadastra a
    conta. Mesma lição do `assinar_webhook` da Meta: deixar o cliente apontar
    o número à mão no painel do Twilio é como nasce o "configurei tudo e não
    acontece nada".
"""
import base64
import hashlib
import hmac
import logging
import re
from xml.sax.saxutils import escape, quoteattr

import httpx

logger = logging.getLogger("zappzen.twilio")

API = "https://api.twilio.com/2010-04-01"
TIMEOUT = 15.0

# O que o Twilio põe em `From` quando quem ligou escondeu o número. Variam por
# operadora: "anonymous" e "restricted" são os comuns, e o +266696687 é o
# número de fachada que algumas rotas internacionais usam ("ANONYMOUS" no
# teclado do telefone).
_OCULTOS = {"", "anonymous", "restricted", "unknown", "unavailable", "private",
            "+266696687", "266696687"}


class TwilioError(Exception):
    """Falha falando com a API do Twilio, com a mensagem que ele devolveu."""


# ---------------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------------

def e164(numero: str | None) -> str:
    """`+5585999998888`, a forma em que o Twilio escreve `To` e `From`.

    É a chave de roteamento do webhook: o número chamado diz de qual empresa é
    a ligação. Gravar e comparar sempre nesta forma evita que "+55 85 9…" na
    tela e "+55859…" no webhook virem dois números diferentes.
    """
    digitos = re.sub(r"\D", "", numero or "")
    return f"+{digitos}" if digitos else ""


def numero_oculto(numero: str | None) -> bool:
    return (numero or "").strip().lower() in _OCULTOS


# ---------------------------------------------------------------------------
# Assinatura
# ---------------------------------------------------------------------------

def assinatura(token: str, url: str, params: list[tuple[str, str]]) -> str:
    """A assinatura que o Twilio calcula para este POST.

    Algoritmo do Twilio: a URL exata que ele chamou (com a query string),
    seguida de cada parâmetro do formulário como `nome` + `valor`, em ordem
    alfabética de nome; HMAC-SHA1 com o Auth Token da conta; base64.
    Parâmetro repetido entra uma vez por valor, com os valores ordenados.
    """
    dados = url + "".join(f"{k}{v}" for k, v in sorted(params))
    mac = hmac.new(token.encode("utf-8"), dados.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("ascii")


def assinatura_valida(token: str, url: str, params: list[tuple[str, str]],
                      recebida: str | None) -> bool:
    """Confere a assinatura em tempo constante.

    A URL é a que o Twilio chamou, que é a pública (`PUBLIC_BASE_URL`), não a
    que o FastAPI enxerga atrás do Caddy: lá dentro ela é `http://127.0.0.1…`,
    e a assinatura nunca bateria.
    """
    if not token or not recebida:
        return False
    return hmac.compare_digest(assinatura(token, url, params), recebida)


# ---------------------------------------------------------------------------
# Instruções da ligação (TwiML)
# ---------------------------------------------------------------------------

def tocar(url: str) -> str:
    return f"<Play>{escape(url)}</Play>"


def falar(texto: str) -> str:
    """Voz sintética em português, para quando a empresa não subiu áudio.

    O áudio gravado pelo dono segura mais gente na linha, mas a ligação não
    pode ficar muda só porque ninguém gravou nada ainda.
    """
    return f'<Say language="pt-BR">{escape(texto)}</Say>'


def coletar(action: str, conteudo: str, timeout: int = 6) -> str:
    """Toca `conteudo` e espera **uma** tecla, mandando-a para `action`.

    Uma tecla só (`numDigits="1"`): sem isso o Twilio espera o `#` ou o tempo
    acabar, e a pessoa que apertou 1 fica alguns segundos sem resposta achando
    que não funcionou.
    """
    return (f'<Gather numDigits="1" timeout="{int(timeout)}" method="POST" '
            f'action={quoteattr(action)}>{conteudo}</Gather>')


def redirecionar(url: str) -> str:
    return f'<Redirect method="POST">{escape(url)}</Redirect>'


def desligar() -> str:
    return "<Hangup/>"


def resposta(*verbos: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            + "".join(verbos) + "</Response>")


# ---------------------------------------------------------------------------
# API REST (só na configuração)
# ---------------------------------------------------------------------------

async def _request(metodo: str, caminho: str, sid: str, token: str,
                   data: dict | None = None, params: dict | None = None) -> dict:
    """Uma chamada à API do Twilio, com a conta do cliente.

    Client por chamada, como no `ai_client` e pelo mesmo motivo: a credencial é
    de cada empresa e estas chamadas são raras (só quando alguém salva a tela),
    então um pool compartilhado só manteria credencial de cliente viva num
    objeto de módulo.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.request(metodo, f"{API}{caminho}", auth=(sid, token),
                                     data=data, params=params)
    except httpx.HTTPError as e:
        raise TwilioError(f"Sem resposta do Twilio: {e}")
    if r.status_code == 401:
        raise TwilioError("Account SID ou Auth Token incorretos")
    if r.status_code >= 400:
        try:
            msg = r.json().get("message") or r.text
        except Exception:
            msg = r.text
        raise TwilioError(f"Twilio respondeu {r.status_code}: {msg}")
    try:
        return r.json()
    except Exception:
        return {}


async def validar_conta(sid: str, token: str) -> dict:
    """Confere se o par (Account SID, Auth Token) abre a conta."""
    conta = await _request("GET", f"/Accounts/{sid}.json", sid, token)
    if (conta.get("status") or "active") != "active":
        raise TwilioError(f"A conta Twilio está {conta.get('status')}: reative-a no painel")
    return conta


async def achar_numero(sid: str, token: str, numero: str) -> dict:
    """O número comprado nesta conta, ou erro dizendo que ele não está nela."""
    dados = await _request("GET", f"/Accounts/{sid}/IncomingPhoneNumbers.json",
                           sid, token, params={"PhoneNumber": numero})
    lista = dados.get("incoming_phone_numbers") or []
    if not lista:
        raise TwilioError(
            f"O número {numero} não foi encontrado nesta conta Twilio. Confira se "
            "ele foi comprado nesta conta (ou subconta) e se foi digitado com o "
            "código do país")
    return lista[0]


async def apontar_numero(sid: str, token: str, numero_sid: str, voice_url: str) -> dict:
    """Faz o número chamar o ZappZen quando tocar."""
    return await _request(
        "POST", f"/Accounts/{sid}/IncomingPhoneNumbers/{numero_sid}.json", sid, token,
        data={"VoiceUrl": voice_url, "VoiceMethod": "POST"})
