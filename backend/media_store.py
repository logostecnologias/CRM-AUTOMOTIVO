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
import base64
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

DEFAULT_MIME = "application/octet-stream"

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

    mime = (mime or "").split(";")[0].strip() or (
        mimetypes.guess_type(filename or "")[0] or DEFAULT_MIME
    )
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


def file_path(doc: dict) -> Path:
    return media_root() / doc["tenant_id"] / doc["stored_name"]


def read_bytes(doc: dict) -> bytes:
    path = file_path(doc)
    if not path.exists():
        raise MediaError("Arquivo não encontrado no armazenamento")
    return path.read_bytes()


def to_data_uri(mime: str | None, data: bytes) -> str:
    return f"data:{mime or DEFAULT_MIME};base64,{base64.b64encode(data).decode()}"


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
