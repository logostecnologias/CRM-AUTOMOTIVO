"""WuzAPI (whatsmeow) async client, routed through the zappzen-gateway.

The gateway (not WuzAPI directly) is the base URL for everything here: it
applies rate limiting to every call and, for /chat/send/*, automatically
resolves the phone number to WhatsApp's canonical JID first (handles the
Brazilian 9-digit quirk transparently — no need to replicate that logic
here).

Two-tier auth, unlike Evolution's single apikey:
  - WUZAPI_ADMIN_TOKEN: only for /admin/users (create/list/delete instances).
  - per-connection token: returned when creating an instance, used as the
    `token` header for every other call (session, chat, user) for that
    instance. Store it as `wuzapi_token` — it's the functional replacement
    for what used to be passed around as `instance_name`.

Endpoint shape (WuzAPI, via gateway):
  POST   /admin/users               — cria instância (Authorization: ADMIN_TOKEN)
  DELETE /admin/users/{id}          — remove instância
  POST   /session/connect           — inicia sessão (token header)
  POST   /session/disconnect        — desconecta mantendo sessão (permite reconectar sem novo QR)
  POST   /session/logout            — desconecta e apaga sessão
  GET    /session/status            — {"data": {"connected": bool, "loggedIn": bool, ...}}
  GET    /session/qr                — {"data": {"QRCode": "data:image/png;base64,..."}}
  POST   /chat/send/text            — {Phone, Body}
  POST   /chat/send/image           — {Phone, Image, Caption}
  POST   /chat/send/audio           — {Phone, Audio, Caption}
  POST   /chat/send/document        — {Phone, Document, FileName, Caption}
  POST   /chat/send/video           — {Phone, Video, Caption}
  POST   /chat/send/sticker         — {Phone, Sticker}
  POST   /chat/downloadimage        — mídia recebida: {Url, DirectPath, MediaKey,
                                       Mimetype, FileSHA256, FileEncSHA256, FileLength}
  POST   /chat/downloadvideo        — idem
  POST   /chat/downloadaudio        — idem
  POST   /chat/downloaddocument     — idem

Media fields (Image/Audio/Document/Video/Sticker) carry the file itself as a
base64 data URI ("data:image/png;base64,..."), not a URL — WuzAPI does not
fetch remote files on its own. Callers pass an already-built data URI here;
media_store.ensure_data_uri() is what turns a stored file or a public URL
into one.
"""
import base64
import os
import secrets
import asyncio
import logging
import httpx
from typing import Any

logger = logging.getLogger("zappzen.wuzapi")


class WuzapiError(Exception):
    pass


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def _base() -> str:
    return os.environ["WUZAPI_GATEWAY_URL"].rstrip("/")


def _admin_headers() -> dict:
    return {
        "Authorization": os.environ["WUZAPI_ADMIN_TOKEN"],
        "Content-Type": "application/json",
    }


def _token_headers(token: str) -> dict:
    return {"token": token, "Content-Type": "application/json"}


MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5  # waits 0.5s, 1s, 2s between attempts
RETRY_STATUS = {500, 502, 503, 504}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Client único do processo, com keep-alive.

    Um client por chamada pagava handshake TCP (e TLS, quando o gateway está
    atrás de HTTPS) em cada mensagem enviada, em cada probe do health monitor
    e em cada tentativa de retry. Aqui as conexões ficam abertas e são
    reaproveitadas. Criado sob demanda de propósito: precisa nascer dentro do
    event loop que vai usá-lo.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _client


async def close_client():
    """Fecha o pool no shutdown. Sem isto o encerramento deixa sockets abertos."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _request(method: str, path: str, headers: dict, json: Any = None) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = await _get_client().request(method, f"{_base()}{path}", json=json, headers=headers)
            if r.status_code in RETRY_STATUS:
                last_err = WuzapiError(f"WuzAPI {method} {path} -> {r.status_code}: {r.text[:200]}")
                logger.warning("WuzAPI transient %s on attempt %d/%d: %s %s",
                               r.status_code, attempt, MAX_ATTEMPTS, method, path)
            elif r.status_code >= 400:
                raise WuzapiError(f"WuzAPI {method} {path} -> {r.status_code}: {r.text[:200]}")
            else:
                try:
                    return r.json()
                except Exception:
                    return {"raw": r.text}
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
            last_err = WuzapiError(f"WuzAPI {method} {path} network error: {e}")
            logger.warning("WuzAPI network error on attempt %d/%d: %s", attempt, MAX_ATTEMPTS, e)

        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))

    raise last_err or WuzapiError(f"WuzAPI {method} {path} failed after {MAX_ATTEMPTS} attempts")


async def create_instance(name: str, token: str, webhook_url: str, events: str = "Message,ReadReceipt") -> dict:
    body = {"name": name, "token": token, "webhook": webhook_url, "events": events}
    resp = await _request("POST", "/admin/users", _admin_headers(), body)
    return resp.get("data", resp)  # {"id":..., "name":..., "token":..., ...}


async def delete_instance(wuzapi_id: str) -> dict:
    return await _request("DELETE", f"/admin/users/{wuzapi_id}", _admin_headers())


async def connect(token: str) -> dict:
    body = {"Subscribe": ["Message", "ReadReceipt"], "Immediate": True}
    return await _request("POST", "/session/connect", _token_headers(token), body)


async def fetch_qr(token: str) -> str | None:
    resp = await _request("GET", "/session/qr", _token_headers(token))
    return (resp.get("data") or {}).get("QRCode")


async def connection_state(token: str) -> dict:
    resp = await _request("GET", "/session/status", _token_headers(token))
    return resp.get("data", {})  # {"connected": bool, "loggedIn": bool, "jid": "...", ...}


async def disconnect_instance(token: str) -> dict:
    return await _request("POST", "/session/disconnect", _token_headers(token))


async def logout_instance(token: str) -> dict:
    return await _request("POST", "/session/logout", _token_headers(token))


async def get_avatar(token: str, phone: str) -> str | None:
    """Profile picture URL for a contact, or None if they hide it (WuzAPI
    returns a 500 for that case — a normal, expected outcome here, not a
    real server error)."""
    try:
        resp = await _request("POST", "/user/avatar", _token_headers(token), {"Phone": phone})
    except WuzapiError:
        return None
    return (resp.get("data") or {}).get("URL") or None


async def send_text(token: str, number: str, text: str) -> dict:
    return await _request("POST", "/chat/send/text", _token_headers(token), {"Phone": number, "Body": text})


_MEDIA_ENDPOINTS = {
    "image": ("/chat/send/image", "Image"),
    "audio": ("/chat/send/audio", "Audio"),
    "document": ("/chat/send/document", "Document"),
    "video": ("/chat/send/video", "Video"),
    "sticker": ("/chat/send/sticker", "Sticker"),
}


_DOWNLOAD_ENDPOINTS = {
    "image": "/chat/downloadimage",
    "video": "/chat/downloadvideo",
    "audio": "/chat/downloadaudio",
    "document": "/chat/downloaddocument",
}


async def download_media(token: str, mediatype: str, media_info: dict) -> bytes:
    """Fetches an *incoming* media file, decrypting it from WhatsApp's servers.

    `media_info` carries the encryption metadata straight off the message
    (Url/DirectPath/MediaKey/Mimetype/FileSHA256/FileEncSHA256/FileLength) —
    the file is stored encrypted, so it can only be pulled with those.

    Only needed when WuzAPI doesn't already ship the bytes in the webhook
    (i.e. when it runs with -skipmedia). The response envelope isn't pinned
    down in WuzAPI's docs, so the payload is unwrapped leniently: the base64
    has been seen both raw and as a data URI, under a handful of key spellings.
    """
    endpoint = _DOWNLOAD_ENDPOINTS.get(mediatype, _DOWNLOAD_ENDPOINTS["document"])
    resp = await _request("POST", endpoint, _token_headers(token), media_info)
    data = resp.get("data", resp)
    if isinstance(data, str):
        b64 = data
    else:
        b64 = next((data[k] for k in ("Data", "data", "base64", "Base64", "Media")
                    if isinstance(data.get(k), str)), None)
    if not b64:
        raise WuzapiError(f"WuzAPI {endpoint}: resposta sem conteúdo base64")
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        return base64.b64decode(b64)
    except Exception as e:
        raise WuzapiError(f"WuzAPI {endpoint}: base64 inválido ({e})")


async def send_media(token: str, number: str, mediatype: str, media: str,
                     caption: str = "", filename: str | None = None) -> dict:
    """`media` must already be a base64 data URI (see module docstring)."""
    endpoint, field = _MEDIA_ENDPOINTS.get(mediatype, _MEDIA_ENDPOINTS["document"])
    body = {"Phone": number, field: media, "Caption": caption}
    if endpoint == _MEDIA_ENDPOINTS["document"][0]:
        # WuzAPI names the document from FileName; without it the contact
        # receives an unnamed attachment with no extension.
        body["FileName"] = filename or "arquivo"
    return await _request("POST", endpoint, _token_headers(token), body)
