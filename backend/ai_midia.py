"""O que o agente de IA consegue ler de um anexo do contato.

Até aqui o agente era só de texto: foto ou áudio sem legenda ia direto para a
fila, e com legenda ele lia só a legenda. No WhatsApp isso é metade das
mensagens: o cliente manda a nota de voz em vez de digitar e a foto da peça em
vez de descrever.

Os dois anexos seguem caminhos diferentes, porque os modelos são diferentes
para cada um:

  - **Áudio vira texto antes de chegar ao agente.** Nenhum modelo de conversa do
    catálogo ouve áudio de forma confiável. A transcrição é gravada na própria
    mensagem (`meta.transcricao`), então é feita uma vez só, entra no histórico
    das respostas seguintes de graça, e o atendente da Central lê o mesmo texto
    embaixo da bolha.

  - **Foto vai como imagem para o modelo**, que enxerga (Claude, GPT-5, Gemini).
    Descrever a foto uma vez e guardar o texto seria mais barato, mas a pergunta
    vem depois ("tem dessa em azul?", "qual o código da peça?") e a descrição
    feita antes não sabe o que vai ser perguntado. Só as últimas `MAX_IMAGENS`
    vão como imagem; as mais antigas viram aviso de texto, senão uma conversa
    longa reenviaria o álbum inteiro em toda resposta.

Nenhum caminho finge: modelo que não enxerga, áudio que não transcreveu e
documento sem leitura viram aviso no histórico, e anexo sem nada legível vai
para uma pessoa, como antes.
"""
import asyncio
import base64
import io
import logging

import ai_client
import ai_runtime
import media_store

logger = logging.getLogger("zappzen.ia")

# Quantas fotos da janela vão como imagem. Cada uma custa ~1.500 tokens de
# entrada por resposta; três cobrem "mandei a frente, o lado e a etiqueta".
MAX_IMAGENS = 3

# Lado maior da imagem enviada. Acima disso o provedor reduz de qualquer jeito
# e cobra pela imagem grande; abaixo, a etiqueta de uma peça fica ilegível.
LADO_MAX = 1280

# Sem Pillow a imagem vai como chegou, desde que caiba: a Anthropic recusa
# acima de 5MB, e o base64 cresce um terço.
MAX_BYTES_SEM_REDUCAO = 3_500_000
MIME_IMAGEM_OK = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Quantos áudios sem transcrição uma resposta transcreve. O normal é um (o que
# acabou de chegar); o teto cobre a rajada de três notas de voz seguidas sem
# deixar uma conversa antiga ser transcrita inteira de uma vez.
MAX_TRANSCRICOES = 3

# Extensão que o provedor de transcrição reconhece, pelo mime. A nota de voz do
# WhatsApp é ogg/opus; o resto vem do chat de teste e de áudio encaminhado.
_EXTENSAO_AUDIO = {
    "audio/ogg": ".ogg", "audio/opus": ".ogg", "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a", "audio/aac": ".m4a", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/webm": ".webm",
    "audio/flac": ".flac", "video/webm": ".webm",
}


def entende_audio(agente: dict) -> bool:
    """Ligado por padrão: ao contrário da agenda, não escreve nada no sistema,
    e desligado o contato que manda áudio cai na fila como antes."""
    return agente.get("audio_ativo", True) is not False


def entende_imagem(agente: dict) -> bool:
    return agente.get("imagem_ativa", True) is not False


def visao_do_agente(agente: dict) -> bool | None:
    """Se o modelo que vai responder enxerga: True, False ou None (não se sabe,
    modelo livre fora do catálogo). Desligado no agente conta como False."""
    if not entende_imagem(agente):
        return False
    em_uso = ai_runtime.modelo_em_uso(agente)
    if not em_uso or not em_uso[0] or not em_uso[1]:
        return None
    return ai_client.aceita_imagem(*em_uso)


# ---------------------------------------------------------------------------
# Texto que representa o anexo no histórico
# ---------------------------------------------------------------------------

def texto_do_anexo(kind: str, legenda: str, *, transcricao: str | None = None,
                   nome: str | None = None, imagem_vai: bool = False) -> str:
    """Como uma mensagem com anexo aparece para o modelo.

    O aviso entre colchetes diz o que chegou sem fingir que o modelo viu: com
    "[o contato enviou uma foto]" ele pode pedir para descrever ou transferir;
    sem aviso nenhum, a legenda "quanto custa?" ficaria sem referência.
    """
    legenda = (legenda or "").strip()
    if kind == "audio":
        if transcricao:
            base = f"[áudio do contato, transcrito] {transcricao}"
        else:
            base = "[o contato enviou um áudio que não foi possível transcrever]"
    elif kind == "image":
        if imagem_vai:
            return legenda
        base = "[o contato enviou uma foto que você não consegue ver]"
    elif kind == "video":
        base = "[o contato enviou um vídeo que você não consegue ver]"
    else:
        base = f"[o contato enviou o arquivo {nome}]" if nome else "[o contato enviou um arquivo]"
    return f"{base}\n{legenda}" if legenda else base


# ---------------------------------------------------------------------------
# Imagem
# ---------------------------------------------------------------------------

async def midia_utilizavel(db, tenant_id: str, media_id: str | None) -> dict | None:
    """O documento do arquivo, se ele ainda existe em disco. Filtrado por
    `tenant_id`, como todo acesso a `media_files`."""
    if not media_id:
        return None
    doc = await db.media_files.find_one({"id": media_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc or doc.get("purged_at") or not media_store.file_path(doc).exists():
        return None
    return doc


def _reduzir(caminho, mime: str) -> dict | None:
    """A imagem reduzida a `LADO_MAX`, em JPEG. Roda numa thread: é CPU.

    A figurinha do WhatsApp é webp animado; o primeiro quadro basta.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        tamanho = caminho.stat().st_size
        if mime not in MIME_IMAGEM_OK or tamanho > MAX_BYTES_SEM_REDUCAO:
            return None
        return {"mime": mime, "b64": base64.b64encode(caminho.read_bytes()).decode()}
    with Image.open(caminho) as img:
        # A foto do celular vem deitada com a rotação numa etiqueta EXIF; sem
        # aplicá-la o modelo lê a etiqueta da peça de lado.
        img = ImageOps.exif_transpose(img)
        img.thumbnail((LADO_MAX, LADO_MAX))
        if img.mode not in ("RGB", "L"):
            fundo = Image.new("RGB", img.size, (255, 255, 255))
            com_alfa = img.convert("RGBA")
            fundo.paste(com_alfa, mask=com_alfa.split()[-1])
            img = fundo
        saida = io.BytesIO()
        img.save(saida, "JPEG", quality=85)
    return {"mime": "image/jpeg", "b64": base64.b64encode(saida.getvalue()).decode()}


async def imagem_para_modelo(doc: dict) -> dict | None:
    """`{"mime", "b64"}` pronto para `ai_client`, ou None se não der para ler.

    É o único lugar em que uma mídia passa inteira pela memória, e não há como
    evitar: o provedor recebe a imagem dentro do JSON. A redução é o que mantém
    isso pequeno (uma foto de 4MB vira ~200KB).
    """
    try:
        return await asyncio.to_thread(_reduzir, media_store.file_path(doc), doc.get("mime") or "")
    except Exception as e:
        logger.warning("Imagem %s ilegível para o agente: %s", doc.get("id"), e)
        return None


# ---------------------------------------------------------------------------
# Áudio
# ---------------------------------------------------------------------------

def nome_para_transcricao(doc: dict) -> str:
    mime = (doc.get("mime") or "").lower()
    return f"audio{_EXTENSAO_AUDIO.get(mime, '.ogg')}"


async def transcrever_doc(db, tenant_id: str, agente: dict, doc: dict) -> str:
    """Transcreve um arquivo. Levanta `IAError`/`HTTPException` com o motivo."""
    mime = (doc.get("mime") or "").lower()
    if mime not in _EXTENSAO_AUDIO:
        raise ai_client.IAError(f"formato de áudio {mime or 'desconhecido'} não suportado")
    texto = await ai_runtime.transcrever_audio(
        db, tenant_id, agente, media_store.file_path(doc), nome_para_transcricao(doc))
    if not texto:
        raise ai_client.IAError("o áudio não tem fala reconhecível")
    return texto


async def transcrever_pendentes(db, agente: dict, session_id: str, tenant_id: str,
                                limite_historico: int) -> None:
    """Transcreve os áudios recentes do contato que ainda não têm texto.

    Grava o resultado na mensagem (`meta.transcricao`) ou o motivo da falha
    (`meta.transcricao_erro`): sem a marca de erro, um áudio intranscrevível
    seria tentado de novo (e cobrado) a cada resposta seguinte.

    Não levanta: falhar aqui deixa o áudio como aviso no histórico, e quem
    decide se isso basta para responder é `ai_agents.tentar_responder`.
    """
    if not entende_audio(agente):
        return
    docs = await db.messages_log.find(
        {"session_id": session_id, "tenant_id": tenant_id,
         "direction": {"$in": ["recebida", "enviada"]}},
        {"_id": 0, "id": 1, "direction": 1, "type": 1, "meta": 1},
    ).sort([("timestamp", -1), ("_id", -1)]).to_list(limite_historico)
    pendentes = [d for d in docs
                 if d.get("direction") == "recebida" and d.get("type") == "audio"
                 and (d.get("meta") or {}).get("media")
                 and not (d.get("meta") or {}).get("transcricao")
                 and not (d.get("meta") or {}).get("transcricao_erro")][:MAX_TRANSCRICOES]
    for msg in pendentes:
        media = msg["meta"]["media"]
        doc = await midia_utilizavel(db, tenant_id, media.get("id"))
        try:
            if not doc:
                raise ai_client.IAError("o arquivo do áudio não está mais disponível")
            campo, valor = "meta.transcricao", await transcrever_doc(db, tenant_id, agente, doc)
        except Exception as e:
            motivo = getattr(e, "detail", None) or str(e)
            logger.info("Áudio %s não transcrito: %s", msg.get("id"), motivo)
            campo, valor = "meta.transcricao_erro", str(motivo)
        await db.messages_log.update_one(
            {"id": msg["id"], "tenant_id": tenant_id}, {"$set": {campo: valor}})
