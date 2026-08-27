"""Cloud API oficial da Meta: a única camada do sistema que fala com o WhatsApp.

Mesmo papel que o antigo `wuzapi_client` tinha, e a mesma regra: nenhum outro
módulo monta requisição para o WhatsApp. O que mudou é tudo o que está por
baixo, e as diferenças que importam são estas:

  - **Não existe instância, sessão nem QR.** Cada conexão é um número já
    registrado numa conta WhatsApp Business (WABA) da Meta, identificado por
    `phone_number_id`, e a credencial é um token de acesso. Não há o que
    conectar ou desconectar: ou o token vale e o número está registrado, ou
    não. Por isso `connect`/`disconnect`/`fetch_qr` sumiram do módulo.

  - **A mídia não viaja embutida.** A WuzAPI recebia o arquivo inteiro como
    data URI base64 dentro do JSON. A Cloud API tem duas formas: subir o
    arquivo antes (`POST /{phone_number_id}/media`, multipart) e mandar o
    `id` devolvido, ou passar um `link` público que a **Meta** busca. As duas
    estão aqui, e nenhuma das duas carrega o arquivo na memória.

  - **A resposta de botão vem com id e rótulo.** `interactive.button_reply`
    e `interactive.list_reply` trazem `id` e `title` sempre. O truque de
    guardar os rótulos em `awaiting.rotulos` continua valendo como rede de
    segurança (e para o formato texto), mas aqui ele deixou de ser a única
    fonte, que era o caso na API não oficial.

  - **Existe janela de 24 horas.** Mensagem livre só sai enquanto a janela de
    atendimento estiver aberta, isto é, até 24h depois da última mensagem que
    o contato mandou. Fora dela, só modelo aprovado (template). Quem decide
    isso é quem chama (`janela_aberta`), porque a alternativa, descobrir pelo
    erro 131047 depois de tentar, gasta uma volta e some com a mensagem.

  - **A entrega é assíncrona.** O POST devolve um `wamid` e nada mais: se a
    mensagem foi entregue, lida ou falhou chega depois, por webhook de status.
    É por isso que todo envio devolve o wamid e ele é gravado no `meta` da
    mensagem: é a chave que liga o status recebido à bolha do histórico.

Autenticação: `Authorization: Bearer <token>`. O token é por conexão, cifrado
em repouso (ver `credencial`), com uma chave de plataforma como reserva
(`META_PLATFORM_TOKEN`) para o número de testes da própria ZappZen.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, NamedTuple

import httpx

import cripto

logger = logging.getLogger("zappzen.whatsapp")

# Versão do Graph fixada de propósito. A Cloud API é estável entre versões,
# mas o campo que muda de forma sem aviso é o payload do webhook, e uma versão
# fixa é o que permite dizer contra qual delas este código foi escrito.
VERSAO_PADRAO = "v23.0"

TIMEOUT = 20.0
MAX_TENTATIVAS = 3
BACKOFF_BASE = 0.5
STATUS_RETENTAR = {500, 502, 503, 504, 429}

# Janela de atendimento: 24h a partir da última mensagem do contato. Depois
# disso o WhatsApp só aceita modelo aprovado.
JANELA_HORAS = 24


class WhatsAppError(Exception):
    """Falha de chamada à Cloud API.

    `codigo` é o código de erro da Meta (não o HTTP), porque é por ele que se
    decide o que fazer: 131047 pede modelo, 130429 pede esperar, 190 pede
    token novo. `detalhe` é o `error_data.details`, que é onde mora a frase
    útil, e não o `message`, que a própria Meta documenta como campo que vai
    mudar.
    """

    def __init__(self, mensagem: str, codigo: int | None = None,
                 detalhe: str | None = None, http: int | None = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.detalhe = detalhe
        self.http = http


# Erros que significam "a janela fechou, mande um modelo". Separados por nome
# porque quem chama precisa distinguir isto de uma falha de rede: uma pede
# outro caminho de envio, a outra pede tentar de novo.
CODIGO_FORA_DA_JANELA = 131047
CODIGO_LIMITE = 130429
CODIGOS_TOKEN = {0, 190, 200, 3, 10}


class Credencial(NamedTuple):
    """O que basta para falar por um número.

    `waba_id` só é usado pelas rotas de conta (assinar webhook, listar
    modelos); o envio não precisa dele.
    """
    phone_number_id: str
    token: str
    waba_id: str | None = None


def _versao() -> str:
    return (os.environ.get("META_GRAPH_VERSION") or VERSAO_PADRAO).strip()


def _base() -> str:
    return f"https://graph.facebook.com/{_versao()}"


def credencial(conn: dict | None) -> Credencial | None:
    """A credencial de envio de uma conexão, ou None se ela não tem uma.

    O token fica cifrado no documento (`token_cifrado`), decifrado só aqui e
    só para a chamada em curso: a regra é a mesma da chave de IA. Sem token
    próprio cai no da plataforma, que é o número da própria ZappZen usado em
    demonstração e teste. Uma conexão sem `phone_number_id` não tem como
    enviar nada, e devolver None é o que faz o chamador registrar "conexão
    indisponível" em vez de estourar no meio de um envio.
    """
    if not conn or not conn.get("phone_number_id"):
        return None
    bloco = conn.get("token_cifrado")
    token = None
    if bloco:
        try:
            token = cripto.decifrar(bloco)
        except cripto.CredencialError as e:
            logger.error("Conexão %s com token ilegível: %s", conn.get("id"), e)
            return None
    token = token or os.environ.get("META_PLATFORM_TOKEN")
    if not token:
        return None
    return Credencial(str(conn["phone_number_id"]), token, conn.get("waba_id"))


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Client único do processo, com keep-alive.

    Mesmo raciocínio do client antigo: um por chamada pagava handshake TLS em
    toda mensagem enviada e em todo probe de saúde. Aqui é ainda mais claro,
    porque agora o destino é sempre o mesmo host da Meta. Criado sob demanda
    para nascer dentro do event loop que vai usá-lo.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _client


async def close_client():
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _erro_do_corpo(r: httpx.Response) -> WhatsAppError:
    try:
        erro = (r.json() or {}).get("error") or {}
    except Exception:
        erro = {}
    detalhe = (erro.get("error_data") or {}).get("details")
    codigo = erro.get("code")
    texto = detalhe or erro.get("message") or r.text[:200]
    return WhatsAppError(f"Cloud API {r.status_code}: {texto}",
                         codigo=codigo, detalhe=detalhe, http=r.status_code)


async def _request(metodo: str, caminho: str, token: str, *, json: Any = None,
                   params: dict | None = None, files: Any = None,
                   data: dict | None = None, repetivel: bool = True) -> dict:
    """Chamada com retry, e o retry é onde mora a decisão que importa.

    `repetivel=False` é para o POST de envio de mensagem: um ReadTimeout
    significa que a requisição chegou à Meta e a resposta se perdeu, então
    repetir manda a mesma mensagem duas vezes para o contato. Falha de
    **conexão** continua sendo repetida mesmo nesse caso, porque aí a
    requisição não chegou a sair, e um 5xx também, porque o próprio servidor
    disse que não processou.
    """
    ultimo: Exception | None = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            extra: dict = {}
            if json is not None:
                extra["json"] = json
            if files is not None:
                extra["files"] = files
            if data is not None:
                extra["data"] = data
            r = await _get_client().request(
                metodo, f"{_base()}{caminho}",
                headers={"Authorization": f"Bearer {token}"},
                params=params, **extra,
            )
            if r.status_code in STATUS_RETENTAR:
                ultimo = _erro_do_corpo(r)
                logger.warning("Cloud API %s transitório em %s %s (tentativa %d/%d)",
                               r.status_code, metodo, caminho, tentativa, MAX_TENTATIVAS)
            elif r.status_code >= 400:
                raise _erro_do_corpo(r)
            else:
                try:
                    return r.json()
                except Exception:
                    return {"raw": r.text}
        except httpx.ConnectError as e:
            ultimo = WhatsAppError(f"Cloud API {metodo} {caminho}: sem conexão ({e})")
            logger.warning("Cloud API sem conexão (tentativa %d/%d): %s",
                           tentativa, MAX_TENTATIVAS, e)
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
            ultimo = WhatsAppError(f"Cloud API {metodo} {caminho}: rede ({e})")
            if not repetivel:
                # Pode ter sido entregue. Repetir duplicaria a mensagem para o
                # contato, que é pior do que devolver o erro e deixar quem
                # chamou registrar a falha.
                raise ultimo
            logger.warning("Cloud API erro de rede (tentativa %d/%d): %s",
                           tentativa, MAX_TENTATIVAS, e)

        if tentativa < MAX_TENTATIVAS:
            await asyncio.sleep(BACKOFF_BASE * (2 ** (tentativa - 1)))

    raise ultimo or WhatsAppError(f"Cloud API {metodo} {caminho} falhou")


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------

def _wamid(resposta: dict) -> str | None:
    """O id da mensagem, que é o que liga o webhook de status a esta bolha."""
    msgs = resposta.get("messages") or []
    return (msgs[0] or {}).get("id") if msgs else None


async def _enviar(cred: Credencial, corpo: dict) -> str | None:
    corpo = {"messaging_product": "whatsapp", "recipient_type": "individual", **corpo}
    resposta = await _request("POST", f"/{cred.phone_number_id}/messages", cred.token,
                              json=corpo, repetivel=False)
    return _wamid(resposta)


async def send_text(cred: Credencial, numero: str, texto: str) -> str | None:
    """`preview_url` ligado: link em mensagem de atendimento com prévia é o
    comportamento que o contato espera de uma conversa de WhatsApp."""
    return await _enviar(cred, {
        "to": numero, "type": "text",
        "text": {"preview_url": True, "body": texto},
    })


async def send_media(cred: Credencial, numero: str, kind: str, *,
                     media_id: str | None = None, link: str | None = None,
                     caption: str = "", filename: str | None = None) -> str | None:
    """Mídia por id (arquivo nosso, já subido) ou por link (URL pública).

    As duas formas existem porque as duas origens existem: o arquivo que o
    atendente anexou está no nosso disco e precisa subir antes; a URL do nó de
    Mídia do editor a própria Meta busca, e mandá-la como `link` evita baixar
    o arquivo aqui só para subi-lo de novo.

    Áudio não aceita legenda na Cloud API. Mandar `caption` num áudio faz a
    requisição inteira ser recusada com erro 100, então a legenda é
    silenciosamente descartada aqui, e não perdida: quem chama grava a legenda
    no histórico de qualquer forma.
    """
    if not media_id and not link:
        raise WhatsAppError("Mídia sem id nem link")
    conteudo: dict = {"id": media_id} if media_id else {"link": link}
    if caption and kind in ("image", "video", "document"):
        conteudo["caption"] = caption
    if kind == "document" and filename:
        # Sem isto o contato recebe o anexo com o nome interno do arquivo.
        conteudo["filename"] = filename
    return await _enviar(cred, {"to": numero, "type": kind, kind: conteudo})


# ---------------------------------------------------------------------------
# Mensagens interativas
#
# Os tetos são do WhatsApp. Ele recusa a mensagem inteira quando um deles é
# ultrapassado, e antes disso já recusava em silêncio, então a validação
# continua sendo nossa: `flow_engine.validar_menu` barra a publicação e
# `flow_runtime._enviar_menu` degrada para texto numerado no envio.
MAX_BOTOES = 3
MAX_ITENS_LISTA = 10          # somando todas as seções
MAX_SECOES = 10
LIMITE_ROTULO_BOTAO = 20
LIMITE_ID_BOTAO = 256
LIMITE_ROTULO_ITEM = 24
LIMITE_DESC_ITEM = 72
LIMITE_ID_ITEM = 200
LIMITE_BOTAO_LISTA = 20
LIMITE_TITULO_SECAO = 24
LIMITE_CORPO_BOTOES = 1024
LIMITE_CORPO_LISTA = 4096
LIMITE_CABECALHO = 60
LIMITE_RODAPE = 60


def _corta(texto: str | None, limite: int) -> str:
    """O corte tira o espaço que sobra no fim: ele quase sempre cai no meio de
    uma palavra, e um rótulo terminado em espaço aparece torto no botão."""
    return (texto or "")[:limite].rstrip()


def _interativo(cred: Credencial, numero: str, interativo: dict,
                titulo: str, rodape: str) -> dict:
    if titulo:
        interativo["header"] = {"type": "text", "text": _corta(titulo, LIMITE_CABECALHO)}
    if rodape:
        interativo["footer"] = {"text": _corta(rodape, LIMITE_RODAPE)}
    return {"to": numero, "type": "interactive", "interactive": interativo}


async def send_buttons(cred: Credencial, numero: str, body: str, itens: list[dict],
                       titulo: str = "", rodape: str = "") -> str | None:
    """Botões de resposta rápida, até MAX_BOTOES.

    `itens` é [{"id", "label"}]. O id é o `sourceHandle` da saída do nó de
    Menu, e volta igual no webhook quando o contato toca: é o que dispensa
    casar texto, que falharia nos rótulos cortados.

    O corpo é obrigatório na Cloud API. Sem ele a mensagem é recusada com erro
    100, e o nó de Menu ficaria esperando resposta de uma pergunta que nunca
    saiu, então a recusa acontece aqui, antes da ida à rede, e quem chama
    degrada para texto.
    """
    if not (body or "").strip():
        raise WhatsAppError("Mensagem de botões sem texto no corpo")
    return await _enviar(cred, _interativo(cred, numero, {
        "type": "button",
        "body": {"text": _corta(body, LIMITE_CORPO_BOTOES)},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": _corta(it["id"], LIMITE_ID_BOTAO),
                                        "title": _corta(it.get("label"), LIMITE_ROTULO_BOTAO)}}
            for it in itens[:MAX_BOTOES]
        ]},
    }, titulo, rodape))


async def send_list(cred: Credencial, numero: str, body: str, texto_botao: str,
                    itens: list[dict], titulo: str = "", rodape: str = "",
                    titulo_secao: str = "") -> str | None:
    """Lista de opções, até MAX_ITENS_LISTA, aberta por um botão.

    Uma seção só: o WhatsApp aceita até MAX_SECOES, mas o editor ainda não
    expõe o agrupamento. O título da seção não pode ser vazio quando existe
    mais de uma seção; com uma só, ele é opcional, e a Meta aceita a chave
    ausente.
    """
    if not (body or "").strip():
        raise WhatsAppError("Mensagem de lista sem texto no corpo")
    linhas = []
    for it in itens[:MAX_ITENS_LISTA]:
        linha = {"id": _corta(it["id"], LIMITE_ID_ITEM),
                 "title": _corta(it.get("label"), LIMITE_ROTULO_ITEM)}
        if it.get("descricao"):
            linha["description"] = _corta(it["descricao"], LIMITE_DESC_ITEM)
        linhas.append(linha)
    secao: dict = {"rows": linhas}
    if titulo_secao:
        secao["title"] = _corta(titulo_secao, LIMITE_TITULO_SECAO)
    return await _enviar(cred, _interativo(cred, numero, {
        "type": "list",
        "body": {"text": _corta(body, LIMITE_CORPO_LISTA)},
        "action": {"button": _corta(texto_botao or "Ver opções", LIMITE_BOTAO_LISTA),
                   "sections": [secao]},
    }, titulo, rodape))


async def send_template(cred: Credencial, numero: str, nome: str, idioma: str,
                        componentes: list[dict] | None = None) -> str | None:
    """Modelo aprovado: o único envio que atravessa a janela de 24 horas.

    É o que sustenta campanha e lembrete de agendamento, porque nos dois casos
    quem escreve primeiro é a plataforma, e quase sempre fora da janela.
    """
    modelo: dict = {"name": nome, "language": {"code": idioma}}
    if componentes:
        modelo["components"] = componentes
    return await _enviar(cred, {"to": numero, "type": "template", "template": modelo})


async def marcar_lida(cred: Credencial, wamid: str, digitando: bool = False) -> None:
    """Marca a mensagem como lida e, opcionalmente, mostra "digitando...".

    Não é enfeite: sem isto o contato vê a mensagem dele sem os dois tiques
    azuis mesmo depois de o bot ter respondido, o que na conversa parece
    empresa que não leu. O indicador cai sozinho em 25 segundos ou quando a
    resposta sai.

    Falha aqui nunca derruba o atendimento: quem chama engole o erro.
    """
    corpo: dict = {"messaging_product": "whatsapp", "status": "read", "message_id": wamid}
    if digitando:
        corpo["typing_indicator"] = {"type": "text"}
    await _request("POST", f"/{cred.phone_number_id}/messages", cred.token,
                   json=corpo, repetivel=False)


# ---------------------------------------------------------------------------
# Mídia
# ---------------------------------------------------------------------------

async def upload_media(cred: Credencial, caminho: str | Path, mime: str,
                       filename: str | None = None) -> str:
    """Sobe um arquivo do nosso disco e devolve o `media_id` da Meta.

    O arquivo é entregue ao httpx como objeto aberto, e não como bytes: ele
    monta o multipart lendo aos pedaços, que é a regra do projeto (o teto por
    tipo chega a 100MB em documento). O id devolvido vale 30 dias e serve para
    quantos envios se quiser, o que é o que impede uma campanha com imagem de
    subir o mesmo arquivo uma vez por destinatário.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise WhatsAppError("Arquivo não encontrado no armazenamento")
    with open(caminho, "rb") as arquivo:
        resposta = await _request(
            "POST", f"/{cred.phone_number_id}/media", cred.token,
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (filename or caminho.name, arquivo, mime)},
        )
    media_id = resposta.get("id")
    if not media_id:
        raise WhatsAppError(f"Upload sem id na resposta: {str(resposta)[:200]}")
    return media_id


async def media_info(cred: Credencial, media_id: str) -> dict:
    """Metadados e URL temporária de uma mídia (recebida ou subida).

    A URL vale 5 minutos e exige o mesmo token no download, então não adianta
    guardá-la: é por isso que o binário é baixado na hora e vira arquivo
    nosso, exatamente como já era na API anterior.
    """
    return await _request("GET", f"/{media_id}", cred.token,
                          params={"phone_number_id": cred.phone_number_id})


async def baixar_midia(cred: Credencial, media_id: str) -> tuple[dict, AsyncIterator[bytes]]:
    """Devolve (metadados, pedaços do arquivo).

    Em duas etapas porque a Cloud API é assim: um GET no id dá a URL, e a URL
    é buscada com o mesmo Bearer. Sem o cabeçalho de autorização o download
    falha, o que é a pegadinha mais comum desta parte da API.

    O binário nunca é materializado: quem consome escreve em disco conforme os
    pedaços chegam.
    """
    info = await media_info(cred, media_id)
    url = info.get("url")
    if not url:
        raise WhatsAppError(f"Mídia {media_id} sem URL de download")

    async def pedacos() -> AsyncIterator[bytes]:
        async with _get_client().stream(
            "GET", url, headers={"Authorization": f"Bearer {cred.token}"}
        ) as r:
            if r.status_code >= 400:
                await r.aread()
                raise WhatsAppError(f"Download da mídia {media_id} falhou: {r.status_code}")
            async for pedaco in r.aiter_bytes():
                yield pedaco

    return info, pedacos()


# ---------------------------------------------------------------------------
# Conta: verificação da conexão, assinatura do webhook e modelos
# ---------------------------------------------------------------------------

async def perfil_numero(cred: Credencial) -> dict:
    """O número como a Meta o enxerga.

    É o probe de saúde da conexão e é também o que a tela mostra depois de
    cadastrar a credencial: nome verificado, número de exibição e qualidade.
    Um token inválido ou um `phone_number_id` de outra conta falham aqui, que
    é o único lugar onde isso pode ser descoberto antes de um contato real.
    """
    return await _request("GET", f"/{cred.phone_number_id}", cred.token, params={
        "fields": "display_phone_number,verified_name,quality_rating,"
                  "code_verification_status,platform_type,throughput",
    })


async def assinar_webhook(cred: Credencial) -> dict:
    """Assina o nosso app aos eventos da WABA do cliente.

    Sem isto a conta existe, o token funciona, o envio funciona, e **nenhuma
    mensagem recebida chega**: a Meta só entrega webhook de uma WABA que
    tenha o app assinado. É o passo que some com mais frequência de tutorial,
    e o sintoma (só entra, nunca sai) parece problema de webhook.
    """
    if not cred.waba_id:
        raise WhatsAppError("Conexão sem waba_id: não dá para assinar o webhook")
    return await _request("POST", f"/{cred.waba_id}/subscribed_apps", cred.token)


async def desassinar_webhook(cred: Credencial) -> dict:
    """Tira o nosso app dos eventos da WABA do cliente.

    Usado quando a empresa é excluída: sem isto a Meta continua entregando
    webhook de números que não pertencem mais a ninguém aqui, e cada evento
    vira uma consulta ao banco que nunca casa.
    """
    if not cred.waba_id:
        raise WhatsAppError("Conexão sem waba_id")
    return await _request("DELETE", f"/{cred.waba_id}/subscribed_apps", cred.token)


async def listar_templates(cred: Credencial) -> list[dict]:
    """Modelos aprovados da WABA, que é o que a tela de campanha oferece.

    Só os aprovados: oferecer um modelo em análise ou reprovado produziria uma
    campanha que falha em todos os destinatários, uma mensagem por vez.
    """
    if not cred.waba_id:
        raise WhatsAppError("Conexão sem waba_id: não dá para listar modelos")
    resposta = await _request("GET", f"/{cred.waba_id}/message_templates", cred.token,
                              params={"limit": 200,
                                      "fields": "name,language,status,category,components"})
    return [t for t in (resposta.get("data") or []) if t.get("status") == "APPROVED"]


def variaveis_do_template(template: dict) -> int:
    """Quantas variáveis o corpo do modelo espera.

    A tela precisa disso para pedir um valor por variável. Conta pelo texto do
    componente BODY, porque é o único que a campanha preenche, e porque o
    `example` nem sempre vem.
    """
    for comp in template.get("components") or []:
        if (comp.get("type") or "").upper() == "BODY":
            texto = comp.get("text") or ""
            achados = set()
            i = 0
            while True:
                abre = texto.find("{{", i)
                if abre < 0:
                    break
                fecha = texto.find("}}", abre)
                if fecha < 0:
                    break
                achados.add(texto[abre + 2:fecha].strip())
                i = fecha + 2
            return len(achados)
    return 0
