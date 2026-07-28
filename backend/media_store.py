"""Armazenamento dos arquivos de mídia trocados nas conversas.

O binário fica em disco (`MEDIA_DIR`, default `backend/media/<tenant_id>/`) e
cada arquivo ganha um documento em `media_files` carregando o `tenant_id`. É
esse documento — nunca o caminho em disco — que autoriza o download: sem ele,
um id vazado daria acesso a arquivo de outra empresa. O nome original do
usuário também nunca vira nome de arquivo (path traversal); ele fica só nos
metadados, para exibição e para o campo FileName do WhatsApp.

Para a WuzAPI, mídia vai sempre como data URI base64
("data:image/png;base64,..."), que é o formato dos campos
Image/Video/Audio/Document. URLs http(s) — usadas pelo nó de Mídia do editor
de fluxos — são baixadas aqui e convertidas antes do envio.
"""
import asyncio
import base64
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

DEFAULT_MIME = "application/octet-stream"

# Blocos de leitura para codificar o arquivo aos poucos. Precisa ser múltiplo
# de 3: base64 consome 3 bytes por vez, e só assim a concatenação dos blocos
# codificados é idêntica a codificar o arquivo inteiro de uma vez.
CHUNK = 3 * 256 * 1024

# O mime vem do upload, ou seja, do cliente. Aceitar só a forma canônica
# (tipo/subtipo) evita que ele carregue aspas ou barras invertidas — o valor
# é embutido no data URI, que por sua vez vai dentro de um JSON.
_MIME_OK = re.compile(r"^[A-Za-z0-9!#$&^_.+-]{1,64}/[A-Za-z0-9!#$&^_.+-]{1,64}$")

# Tetos por tipo, espelhando os limites práticos do WhatsApp. Documento fica
# abaixo dos 100MB que o WhatsApp aceita porque aqui o arquivo ainda vira
# base64 (+33%) e atravessa o gateway em um único POST.
MAX_BYTES = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 20 * 1024 * 1024,
}
HARD_MAX_BYTES = max(MAX_BYTES.values())

KIND_LABEL = {
    "image": "Imagem",
    "video": "Vídeo",
    "audio": "Áudio",
    "document": "Documento",
}


class MediaError(Exception):
    pass


def sanitize_mime(mime: str | None, filename: str | None = None) -> str:
    """Mime em forma canônica, ou o genérico se não for reconhecível."""
    limpo = (mime or "").split(";")[0].strip().lower()
    if not _MIME_OK.match(limpo):
        limpo = (mimetypes.guess_type(filename or "")[0] or "").lower()
    return limpo if _MIME_OK.match(limpo) else DEFAULT_MIME


def media_root() -> Path:
    root = os.environ.get("MEDIA_DIR") or (Path(__file__).parent / "media")
    return Path(root)


def classify(mime: str | None, filename: str | None = None) -> str:
    """Tipo de envio da WuzAPI para este arquivo.

    Áudio que não seja ogg/opus vai como documento de propósito: o endpoint
    /chat/send/audio produz mensagem de voz, que o WhatsApp só toca em
    ogg/opus. Um mp3 mandado por ali chega quebrado — como documento, chega
    inteiro e o cliente baixa normalmente.
    """
    mime = (mime or "").lower().split(";")[0].strip()
    if (not mime or mime == DEFAULT_MIME) and filename:
        mime = (mimetypes.guess_type(filename)[0] or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime in ("audio/ogg", "audio/opus"):
        return "audio"
    return "document"


def _extension(filename: str | None, mime: str | None) -> str:
    ext = Path(filename or "").suffix
    if ext and len(ext) <= 10 and ext.isascii():
        return ext.lower()
    return mimetypes.guess_extension(mime or "") or ".bin"


def _safe_display_name(filename: str | None, mime: str | None) -> str:
    """Nome só para exibição/FileName — sem diretório, nunca usado no disco."""
    name = Path(filename or "").name.strip()
    return name or f"arquivo{_extension(None, mime)}"


async def store_upload(
    db,
    tenant_id: str,
    session_id: str | None,
    user_id: str | None,
    filename: str | None,
    mime: str | None,
    data: bytes,
    kind: str | None = None,
    limit: int | None = None,
) -> dict:
    """`kind`/`limit` só são passados no caminho de recebimento: o tipo já vem
    decidido pelo nó da mensagem, e o teto é o geral — recusar por exceder o
    limite de envio perderia uma mídia que o contato já mandou."""
    if not data:
        raise MediaError("Arquivo vazio")
    kind = kind or classify(mime, filename)
    limit = limit or MAX_BYTES.get(kind, HARD_MAX_BYTES)
    if len(data) > limit:
        raise MediaError(
            f"{KIND_LABEL.get(kind, 'Arquivo')} acima do limite de {limit // (1024 * 1024)}MB"
        )

    mime = sanitize_mime(mime, filename)
    media_id = str(uuid.uuid4())
    stored_name = f"{uuid.uuid4().hex}{_extension(filename, mime)}"
    folder = media_root() / tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored_name).write_bytes(data)

    doc = {
        "id": media_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "uploaded_by": user_id,
        "filename": _safe_display_name(filename, mime),
        "stored_name": stored_name,
        "mime": mime,
        "kind": kind,
        "size": len(data),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.media_files.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def store_stream(
    db,
    tenant_id: str,
    session_id: str | None,
    user_id: str | None,
    filename: str | None,
    mime: str | None,
    read_chunk,
    kind: str | None = None,
    limit: int | None = None,
) -> dict:
    """Igual a store_upload, mas grava o upload conforme ele chega.

    `read_chunk` é uma corrotina que devolve o próximo bloco (o `.read(n)` do
    UploadFile). Juntar o arquivo inteiro na memória para só então escrevê-lo
    custava duas cópias dele — e o teto por tipo chega a 20MB, por envio
    simultâneo. Aqui a memória fica no tamanho de um bloco.

    O arquivo parcial é apagado se algo der errado: quem estoura o limite não
    pode deixar 20MB órfãos em disco.
    """
    kind = kind or classify(mime, filename)
    limit = limit or MAX_BYTES.get(kind, HARD_MAX_BYTES)
    mime = sanitize_mime(mime, filename)

    media_id = str(uuid.uuid4())
    stored_name = f"{uuid.uuid4().hex}{_extension(filename, mime)}"
    folder = media_root() / tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    destino = folder / stored_name

    total = 0
    try:
        with open(destino, "wb") as saida:
            while True:
                bloco = await read_chunk(CHUNK)
                if not bloco:
                    break
                total += len(bloco)
                if total > limit:
                    raise MediaError(
                        f"{KIND_LABEL.get(kind, 'Arquivo')} acima do limite de "
                        f"{limit // (1024 * 1024)}MB"
                    )
                saida.write(bloco)
        if not total:
            raise MediaError("Arquivo vazio")
    except BaseException:
        destino.unlink(missing_ok=True)
        raise

    doc = {
        "id": media_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "uploaded_by": user_id,
        "filename": _safe_display_name(filename, mime),
        "stored_name": stored_name,
        "mime": mime,
        "kind": kind,
        "size": total,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.media_files.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


def file_path(doc: dict) -> Path:
    return media_root() / doc["tenant_id"] / doc["stored_name"]


def read_bytes(doc: dict) -> bytes:
    path = file_path(doc)
    if not path.exists():
        raise MediaError("Arquivo não encontrado no armazenamento")
    return path.read_bytes()


def to_data_uri(mime: str | None, data: bytes) -> str:
    return f"data:{mime or DEFAULT_MIME};base64,{base64.b64encode(data).decode()}"


class DataUriStream:
    """O arquivo armazenado, como data URI, lido aos pedaços na hora do envio.

    Existe para o arquivo nunca precisar caber inteiro na memória. O caminho
    antigo (`to_data_uri(mime, read_bytes(doc))`) mantinha vivos ao mesmo
    tempo o arquivo bruto, o base64 em bytes e mais uma cópia em str — e o
    httpx ainda serializava tudo de novo para montar o JSON. Um vídeo de 16MB
    chegava à ordem de dezenas de MB de pico; assim, o pico é um bloco.

    `len()` dá o tamanho exato do data URI sem montá-lo — base64 é
    determinístico (4 bytes de saída para cada 3 de entrada, arredondando
    para cima), e é isso que permite mandar Content-Length e evitar
    `Transfer-Encoding: chunked`, que nem todo servidor aceita.

    Cada `async for` reabre o arquivo do zero, de propósito: o envio tem
    retry, e um gerador já consumido mandaria corpo vazio na segunda
    tentativa.
    """

    def __init__(self, doc: dict):
        self.path = file_path(doc)
        if not self.path.exists():
            raise MediaError("Arquivo não encontrado no armazenamento")
        # O tamanho vem do disco, não do documento: é o arquivo que vai ser
        # lido, e um Content-Length que não bate com o corpo corrompe a
        # requisição inteira.
        self.size = self.path.stat().st_size
        # O prefixo carrega o mime saneado — ele termina dentro de uma string
        # JSON. O base64 em si só tem caracteres seguros, por construção.
        self.prefixo = f"data:{sanitize_mime(doc.get('mime'))};base64,".encode()

    def __len__(self) -> int:
        return len(self.prefixo) + 4 * ((self.size + 2) // 3)

    async def __aiter__(self):
        yield self.prefixo
        lido = 0
        with open(self.path, "rb") as entrada:
            while True:
                # Em thread para não travar o event loop lendo disco.
                bloco = await asyncio.to_thread(entrada.read, CHUNK)
                if not bloco:
                    break
                lido += len(bloco)
                yield base64.b64encode(bloco)
        if lido != self.size:
            # O arquivo mudou de tamanho entre o stat e a leitura: o corpo já
            # foi enviado pela metade e não há como voltar atrás, mas o erro
            # precisa aparecer no log em vez de virar mídia truncada calada.
            raise MediaError(
                f"Arquivo mudou durante o envio ({lido} != {self.size} bytes)"
            )




async def ensure_data_uri(source: str, mime: str | None = None) -> str:
    """Aceita data URI (devolve como está) ou URL http(s) (baixa e converte).

    O nó de Mídia do editor guarda uma URL pública, e a WuzAPI não busca URL
    sozinha — sem esta conversão o nó falharia no envio real.
    """
    if not source:
        raise MediaError("Mídia sem origem")
    if source.startswith("data:"):
        return source
    if not source.startswith(("http://", "https://")):
        raise MediaError(f"Origem de mídia não suportada: {source[:40]}")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await client.get(source)
    if r.status_code >= 400:
        raise MediaError(f"Falha ao baixar mídia ({r.status_code})")
    content = r.content
    if len(content) > HARD_MAX_BYTES:
        raise MediaError("Mídia remota acima do limite de tamanho")
    return to_data_uri(mime or r.headers.get("content-type"), content)


def public_payload(doc: dict) -> dict:
    """Recorte que vai no `meta` da mensagem e é lido pelo chat."""
    return {
        "id": doc["id"],
        "filename": doc["filename"],
        "mime": doc["mime"],
        "kind": doc["kind"],
        "size": doc["size"],
    }
