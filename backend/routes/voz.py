"""Telefone: o webhook de voz do Twilio e a configuração da empresa.

Dois públicos, num arquivo só porque um não existe sem o outro:

  - **O Twilio** chama `/api/webhooks/voz` quando o número toca e
    `/api/webhooks/voz/tecla` quando a pessoa aperta alguma coisa. É um
    endereço só para todas as empresas, como o da Meta, e quem diz de qual
    empresa é a ligação é o número chamado (`To`). Ele também busca os áudios
    em `/api/voz/audio/...`, sem login, porque quem pede é o Twilio.

  - **O admin da empresa** configura tudo em `/api/voz/*`: conta Twilio,
    áudios, mensagem, quem atende a resposta, e vê o resumo das ligações.

A resposta ao Twilio é sempre TwiML (XML) e sempre rápida. O envio da
mensagem de WhatsApp roda depois de a resposta sair: o Twilio espera no máximo
15 segundos, e a pessoa não pode ficar muda na linha enquanto a Meta responde.
"""
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException,
                     Request, UploadFile)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import cripto
import datas
import ligacoes
import media_store
import twilio_voz
from auth import require_tenant_admin
from db import get_db

logger = logging.getLogger("zappzen.voz")

router = APIRouter(tags=["voz"])

AUDIOS = ("pergunta", "confirmacao")
# O Twilio toca MP3 e WAV (e formatos de telefonia que ninguém tem em mãos).
# O áudio que o WhatsApp grava é OGG/Opus, e o gravador do iPhone gera M4A:
# os dois são recusados dizendo o que fazer, em vez de serem aceitos e a
# ligação ficar muda.
_AUDIO_OK = {".mp3": "audio/mpeg", ".wav": "audio/wav"}
_MIME_OK = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
            "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/vnd.wave": ".wav"}
MAX_AUDIO = 5 * 1024 * 1024
MAX_TENTATIVAS = 2


def _now():
    return datetime.now(timezone.utc).isoformat()


def _base() -> str:
    """O endereço público do backend, o mesmo que o Twilio enxerga.

    Sem ele não dá para conferir a assinatura (ela é calculada sobre a URL que
    o Twilio chamou) nem dizer ao Twilio para onde ligar. Fail-closed, como o
    `META_APP_SECRET`: sem configuração, recusa, em vez de aceitar sem prova.
    """
    base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        logger.error("PUBLIC_BASE_URL ausente: webhook de voz recusado")
        raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL não configurada")
    return base


def _twiml(*verbos: str) -> Response:
    return Response(content=twilio_voz.resposta(*verbos), media_type="application/xml")


# ---------------------------------------------------------------------------
# Webhook do Twilio
# ---------------------------------------------------------------------------

async def _autenticar(request: Request) -> tuple[dict | None, dict]:
    """A configuração da empresa dona do número chamado, com a origem provada.

    O número chamado (`To`) aponta a empresa, e a assinatura é conferida com o
    Auth Token **dela**: cada empresa tem a própria conta (ou subconta) Twilio,
    e o token de uma não assina a ligação de outra. `To` desconhecido devolve
    `None` e a ligação é encerrada sem fazer nada, porque não há com que
    conferir a assinatura.
    """
    form = await request.form()
    params = [(k, str(v)) for k, v in form.multi_items()]
    campos = dict(params)
    base = _base()

    db = get_db()
    config = await db.voz_config.find_one(
        {"numero": twilio_voz.e164(campos.get("To"))}, {"_id": 0})
    if not config:
        logger.info("Ligação para número sem empresa: %s", campos.get("To"))
        return None, campos

    try:
        token = cripto.decifrar(config.get("auth_token") or {})
    except cripto.CredencialError as e:
        logger.error("Empresa %s: Auth Token do Twilio ilegível: %s", config["tenant_id"], e)
        raise HTTPException(status_code=503, detail="Credencial do Twilio indisponível")

    url = f"{base}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    if not twilio_voz.assinatura_valida(token, url, params,
                                        request.headers.get("x-twilio-signature")):
        raise HTTPException(status_code=403, detail="Assinatura inválida")
    if campos.get("AccountSid") != config.get("account_sid"):
        raise HTTPException(status_code=403, detail="Conta Twilio não confere")
    return config, campos


def _tentativa(request: Request) -> int:
    try:
        return max(1, min(MAX_TENTATIVAS, int(request.query_params.get("tentativa") or 1)))
    except ValueError:
        return 1


def _audio_ou_texto(config: dict, tipo: str, chave_texto: str) -> str:
    """O áudio gravado, se houver; senão a voz sintética lendo o texto."""
    media_id = config.get(f"audio_{tipo}_id")
    if media_id and config.get("audio_token"):
        # O `v` muda quando o áudio é trocado: o Twilio guarda áudio em cache
        # pela URL, e sem isso continuaria tocando a gravação antiga.
        return twilio_voz.tocar(
            f"{_base()}/api/voz/audio/{config['audio_token']}/{tipo}?v={media_id[:8]}")
    return twilio_voz.falar(ligacoes.texto(config, chave_texto))


def _pergunta(config: dict, tentativa: int) -> Response:
    base = _base()
    verbos = [twilio_voz.coletar(
        f"{base}/api/webhooks/voz/tecla?tentativa={tentativa}",
        _audio_ou_texto(config, "pergunta", "texto_pergunta"))]
    # Sem tecla: pergunta uma segunda vez (quem estava tirando o telefone do
    # ouvido perdeu a primeira) e depois desliga. Mais que duas vezes é prender
    # na linha quem já decidiu não apertar nada.
    if tentativa < MAX_TENTATIVAS:
        verbos.append(twilio_voz.redirecionar(
            f"{base}/api/webhooks/voz?tentativa={tentativa + 1}"))
    verbos.append(twilio_voz.desligar())
    return _twiml(*verbos)


@router.post("/api/webhooks/voz")
async def receber_ligacao(request: Request):
    config, campos = await _autenticar(request)
    if not config:
        return _twiml(twilio_voz.desligar())

    if not config.get("ativo"):
        # Desligado na tela, mas o desvio da operadora continua apontando para
        # cá. Desligar a ligação muda seria pior que dizer onde achar a empresa.
        return _twiml(twilio_voz.falar(ligacoes.texto(config, "texto_sem_numero")),
                      twilio_voz.desligar())

    db = get_db()
    ligacao = await ligacoes.registrar(db, config, campos.get("CallSid") or "",
                                       campos.get("From"), campos.get("To"))
    if ligacao["oculto"]:
        return _twiml(twilio_voz.falar(ligacoes.texto(config, "texto_sem_numero")),
                      twilio_voz.desligar())
    return _pergunta(config, _tentativa(request))


@router.post("/api/webhooks/voz/tecla")
async def receber_tecla(request: Request, bg: BackgroundTasks):
    config, campos = await _autenticar(request)
    if not config:
        return _twiml(twilio_voz.desligar())

    db = get_db()
    tenant_id = config["tenant_id"]
    ligacao = await db.ligacoes.find_one(
        {"tenant_id": tenant_id, "call_sid": campos.get("CallSid") or ""}, {"_id": 0})
    digito = (campos.get("Digits") or "")[:1]
    if ligacao and digito:
        await ligacoes.marcar_tecla(db, tenant_id, ligacao["id"], digito)

    if digito == "1" and ligacao:
        bg.add_task(ligacoes.enviar_whatsapp, db, tenant_id, ligacao["id"])
        return _twiml(_audio_ou_texto(config, "confirmacao", "texto_confirmacao"),
                      twilio_voz.desligar())

    # Outra tecla: a pessoa quis responder e errou. Uma segunda chance, como
    # quem não apertou nada.
    tentativa = _tentativa(request)
    if tentativa < MAX_TENTATIVAS:
        return _pergunta(config, tentativa + 1)
    return _twiml(twilio_voz.desligar())


@router.get("/api/voz/audio/{token}/{tipo}")
async def servir_audio(token: str, tipo: str):
    """O áudio que o Twilio toca na ligação.

    Sem login, porque quem pede é o Twilio. O que protege é o `audio_token`,
    aleatório por empresa: sem ele não se chega ao arquivo, e com ele só se
    chega aos dois áudios da gravação, nunca a mídia de conversa.
    """
    if tipo not in AUDIOS or len(token) < 20:
        raise HTTPException(status_code=404, detail="Áudio não encontrado")
    db = get_db()
    config = await db.voz_config.find_one({"audio_token": token}, {"_id": 0})
    media_id = (config or {}).get(f"audio_{tipo}_id")
    if not media_id:
        raise HTTPException(status_code=404, detail="Áudio não encontrado")
    doc = await db.media_files.find_one(
        {"id": media_id, "tenant_id": config["tenant_id"]}, {"_id": 0})
    if not doc or doc.get("purged_at"):
        raise HTTPException(status_code=404, detail="Áudio não encontrado")
    path = media_store.file_path(doc)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Áudio não encontrado")
    return FileResponse(path, media_type=doc["mime"], headers={
        "Cache-Control": "public, max-age=300",
        "X-Content-Type-Options": "nosniff",
    })


# ---------------------------------------------------------------------------
# Configuração (admin da empresa)
# ---------------------------------------------------------------------------

# O que nunca sai para o navegador: o Auth Token, mesmo cifrado. Com ele e o
# Account SID dá para gastar o crédito da conta e reconfigurar o número.
_OCULTOS = ("_id", "auth_token")


async def _config(db, tenant_id: str) -> dict:
    """A configuração da empresa, criada vazia na primeira leitura."""
    config = await db.voz_config.find_one({"tenant_id": tenant_id}, {"_id": 0})
    if config:
        return config
    config = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "ativo": False,
        "numero": None,
        "account_sid": None,
        "auth_token": None,
        "token_mascara": None,
        "numero_configurado": False,
        "whatsapp_connection_id": None,
        "template": {"nome": "", "idioma": "pt_BR", "variaveis": []},
        "mensagem": "",
        "resposta_modo": "agente",
        "bot_id": None,
        "texto_pergunta": "",
        "texto_confirmacao": "",
        "texto_sem_numero": "",
        "audio_pergunta_id": None,
        "audio_confirmacao_id": None,
        # Gerado já na criação: é o que dá endereço aos áudios, e um token
        # trocado depois deixaria o Twilio tocando uma URL que não existe mais.
        "audio_token": secrets.token_urlsafe(24),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.voz_config.insert_one(dict(config))
    return config


async def _serializar(db, config: dict) -> dict:
    saida = {k: v for k, v in config.items() if k not in _OCULTOS}
    saida["textos_padrao"] = ligacoes.TEXTOS_PADRAO
    for tipo in AUDIOS:
        media_id = config.get(f"audio_{tipo}_id")
        doc = await db.media_files.find_one(
            {"id": media_id, "tenant_id": config["tenant_id"]},
            {"_id": 0, "id": 1, "filename": 1, "size": 1}) if media_id else None
        saida[f"audio_{tipo}"] = doc
    return saida


@router.get("/api/voz/config")
async def ler_config(user=Depends(require_tenant_admin)):
    db = get_db()
    return await _serializar(db, await _config(db, user["tenant_id"]))


class TemplateIn(BaseModel):
    nome: str = ""
    idioma: str = "pt_BR"
    variaveis: list[str] = Field(default_factory=list, max_length=10)


class ConfigIn(BaseModel):
    ativo: bool = False
    whatsapp_connection_id: str | None = None
    template: TemplateIn = Field(default_factory=TemplateIn)
    mensagem: str = Field("", max_length=1000)
    resposta_modo: str = "agente"
    bot_id: str | None = None
    texto_pergunta: str = Field("", max_length=600)
    texto_confirmacao: str = Field("", max_length=300)
    texto_sem_numero: str = Field("", max_length=600)


@router.put("/api/voz/config")
async def salvar_config(body: ConfigIn, user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    config = await _config(db, tenant_id)

    if body.resposta_modo not in ligacoes.MODOS:
        raise HTTPException(status_code=400, detail="Escolha quem atende a resposta")
    if body.resposta_modo == "bot":
        if not body.bot_id or not await db.bots.find_one(
                {"id": body.bot_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=400, detail="Escolha o robô que atende a resposta")
    if body.whatsapp_connection_id and not await db.whatsapp_connections.find_one(
            {"id": body.whatsapp_connection_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=400, detail="Conexão de WhatsApp não encontrada")
    if body.ativo and not config.get("numero_configurado"):
        # Ligar sem conta conectada daria a impressão de que está funcionando.
        raise HTTPException(
            status_code=400,
            detail="Conecte a conta Twilio e o número antes de ligar o atendimento")

    mudanca = body.model_dump()
    mudanca["template"]["nome"] = mudanca["template"]["nome"].strip()
    if body.resposta_modo != "bot":
        mudanca["bot_id"] = None
    mudanca["updated_at"] = _now()
    await db.voz_config.update_one({"id": config["id"], "tenant_id": tenant_id},
                                   {"$set": mudanca})
    return await _serializar(db, {**config, **mudanca})


class CredenciaisIn(BaseModel):
    account_sid: str
    auth_token: str | None = None  # ausente = manter o que já está gravado
    numero: str


@router.post("/api/voz/credenciais")
async def salvar_credenciais(body: CredenciaisIn, user=Depends(require_tenant_admin)):
    """Conecta a conta Twilio e aponta o número para o ZappZen.

    Mesmas regras da credencial da Cloud API: **valida antes de gravar** (senão
    a tela diria "conectado" com token errado, e o cliente só descobriria
    quando um cliente dele ligasse) e **configura o número aqui**, em vez de
    pedir ao cliente que cole a URL no painel do Twilio.
    """
    db = get_db()
    tenant_id = user["tenant_id"]
    config = await _config(db, tenant_id)
    base = _base()

    sid = body.account_sid.strip()
    if not sid.startswith("AC") or len(sid) != 34:
        raise HTTPException(status_code=400,
                            detail="O Account SID começa com AC e tem 34 caracteres")
    numero = twilio_voz.e164(body.numero)
    if not 11 <= len(numero) <= 16:
        raise HTTPException(status_code=400,
                            detail="Informe o número com código do país, ex.: +55 85 3333-4444")

    # O número é a chave de roteamento de todas as ligações do sistema: dois
    # donos para ele faria uma empresa receber as ligações da outra.
    outro = await db.voz_config.find_one(
        {"numero": numero, "tenant_id": {"$ne": tenant_id}}, {"_id": 0, "id": 1})
    if outro:
        raise HTTPException(status_code=409, detail="Este número já está em uso por outra empresa")

    token = (body.auth_token or "").strip()
    if not token:
        if not config.get("auth_token") or config.get("account_sid") != sid:
            # Trocar de conta exige o token da conta nova: reaproveitar o
            # guardado o mandaria para uma conta que ele não abre.
            raise HTTPException(status_code=400, detail="Informe o Auth Token da conta Twilio")
        try:
            token = cripto.decifrar(config["auth_token"])
        except cripto.CredencialError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        await twilio_voz.validar_conta(sid, token)
        registro = await twilio_voz.achar_numero(sid, token, numero)
    except twilio_voz.TwilioError as e:
        raise HTTPException(status_code=400, detail=str(e))

    aviso = None
    try:
        await twilio_voz.apontar_numero(sid, token, registro["sid"],
                                        f"{base}/api/webhooks/voz")
    except twilio_voz.TwilioError as e:
        aviso = (f"Conta validada, mas não foi possível configurar o número: {e}. "
                 "Sem isso as ligações não chegam ao ZappZen.")

    bloco = cripto.cifrar(token)
    mudanca = {
        "account_sid": sid,
        "auth_token": bloco,
        "token_mascara": bloco["mascara"],
        "numero": numero,
        "numero_configurado": aviso is None,
        "updated_at": _now(),
    }
    await db.voz_config.update_one({"id": config["id"], "tenant_id": tenant_id},
                                   {"$set": mudanca})
    saida = await _serializar(db, {**config, **mudanca})
    if aviso:
        saida["aviso"] = aviso
    return saida


def _formato_audio(arquivo: UploadFile) -> tuple[str, str]:
    """(mime, extensão) do áudio, ou recusa dizendo o que fazer."""
    nome = (arquivo.filename or "").lower()
    for ext, mime in _AUDIO_OK.items():
        if nome.endswith(ext):
            return mime, ext
    mime = (arquivo.content_type or "").lower().split(";")[0].strip()
    if mime in _MIME_OK:
        return mime, _MIME_OK[mime]
    raise HTTPException(
        status_code=400,
        detail="O Twilio só toca MP3 ou WAV. Áudio gravado no WhatsApp (OGG) ou no "
               "iPhone (M4A) precisa ser convertido para MP3 antes de enviar.")


async def _apagar_audio(db, tenant_id: str, media_id: str | None) -> None:
    """Tira o áudio antigo do disco e do banco.

    Ele não está em mensagem nenhuma, então não há bolha de histórico para
    preservar, ao contrário das fotos do agente. E a retenção não o recolhe
    (ver `media_retention`), então sem isto cada troca de gravação deixaria um
    arquivo para sempre.
    """
    if not media_id:
        return
    doc = await db.media_files.find_one({"id": media_id, "tenant_id": tenant_id}, {"_id": 0})
    if doc:
        try:
            media_store.file_path(doc).unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Áudio de voz %s não apagado do disco: %s", media_id, e)
        await db.media_files.delete_one({"id": media_id, "tenant_id": tenant_id})


@router.post("/api/voz/audio/{tipo}")
async def enviar_audio(tipo: str, arquivo: UploadFile = File(...),
                       user=Depends(require_tenant_admin)):
    if tipo not in AUDIOS:
        raise HTTPException(status_code=404, detail="Tipo de áudio desconhecido")
    db = get_db()
    tenant_id = user["tenant_id"]
    config = await _config(db, tenant_id)
    mime, ext = _formato_audio(arquivo)
    nome = arquivo.filename or f"{tipo}{ext}"
    if not nome.lower().endswith(ext):
        nome += ext
    try:
        doc = await media_store.store_stream(
            db, tenant_id, None, user["id"], nome, mime, arquivo.read,
            kind="audio", limit=MAX_AUDIO)
    except media_store.MediaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # `uso` tira o arquivo da retenção de mídia: a gravação é configuração, não
    # acervo de conversa, e apagá-la com 90 dias deixaria a ligação muda.
    await db.media_files.update_one({"id": doc["id"], "tenant_id": tenant_id},
                                    {"$set": {"uso": "voz"}})
    await _apagar_audio(db, tenant_id, config.get(f"audio_{tipo}_id"))
    await db.voz_config.update_one(
        {"id": config["id"], "tenant_id": tenant_id},
        {"$set": {f"audio_{tipo}_id": doc["id"], "updated_at": _now()}})
    config[f"audio_{tipo}_id"] = doc["id"]
    return await _serializar(db, config)


@router.delete("/api/voz/audio/{tipo}")
async def remover_audio(tipo: str, user=Depends(require_tenant_admin)):
    if tipo not in AUDIOS:
        raise HTTPException(status_code=404, detail="Tipo de áudio desconhecido")
    db = get_db()
    tenant_id = user["tenant_id"]
    config = await _config(db, tenant_id)
    await _apagar_audio(db, tenant_id, config.get(f"audio_{tipo}_id"))
    await db.voz_config.update_one(
        {"id": config["id"], "tenant_id": tenant_id},
        {"$set": {f"audio_{tipo}_id": None, "updated_at": _now()}})
    config[f"audio_{tipo}_id"] = None
    return await _serializar(db, config)


@router.get("/api/voz/ligacoes")
async def listar_ligacoes(limite: int = 50, user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    linhas = await db.ligacoes.find(
        {"tenant_id": tenant_id}, {"_id": 0, "call_sid": 0},
    ).sort([("created_at", -1), ("_id", -1)]).limit(max(1, min(limite, 200))).to_list(200)
    ids = list({l["contact_id"] for l in linhas if l.get("contact_id")})
    nomes = {
        c["id"]: c.get("nome")
        async for c in db.contacts.find({"tenant_id": tenant_id, "id": {"$in": ids}},
                                        {"_id": 0, "id": 1, "nome": 1})
    } if ids else {}
    for l in linhas:
        l["contato_nome"] = nomes.get(l.get("contact_id"))
    return linhas


@router.get("/api/voz/resumo")
async def resumo(de: str | None = None, ate: str | None = None,
                 user=Depends(require_tenant_admin)):
    # Instante, não dia: o corte de "este mês" vem do navegador já no fuso de
    # quem olha, e só precisa ficar no formato que o banco compara.
    return await ligacoes.resumo(get_db(), user["tenant_id"],
                                 datas.para_utc(de, "Início"), datas.para_utc(ate, "Fim"))
