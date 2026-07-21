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

NOTE: not yet verified whether Image/Audio/Document/Video accept a plain
http(s) URL (like Evolution's `media` field did) or require base64/data-URI.
Test this against a real send before relying on it in send_media().
"""
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


async def _request(method: str, path: str, headers: dict, json: Any = None) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.request(method, f"{_base()}{path}", json=json, headers=headers)
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
    return await _request("POST", "/session/connect", _token_headers(token))


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


async def send_text(token: str, number: str, text: str) -> dict:
    return await _request("POST", "/chat/send/text", _token_headers(token), {"Phone": number, "Body": text})


_MEDIA_ENDPOINTS = {
    "image": ("/chat/send/image", "Image"),
    "audio": ("/chat/send/audio", "Audio"),
    "document": ("/chat/send/document", "Document"),
    "video": ("/chat/send/video", "Video"),
    "sticker": ("/chat/send/sticker", "Sticker"),
}


async def send_media(token: str, number: str, mediatype: str, media: str, caption: str = "") -> dict:
    endpoint, field = _MEDIA_ENDPOINTS.get(mediatype, _MEDIA_ENDPOINTS["document"])
    return await _request("POST", endpoint, _token_headers(token), {"Phone": number, field: media, "Caption": caption})
