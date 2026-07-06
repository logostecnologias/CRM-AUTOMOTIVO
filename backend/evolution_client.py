"""Evolution API v2 async client.
Docs: https://doc.evolution-api.com

Endpoint shape assumed (Evolution API v2):
  POST   /instance/create                     — cria instância (apikey header)
  GET    /instance/connect/{instanceName}     — retorna QR base64
  GET    /instance/connectionState/{name}     — estado (open/close/connecting)
  DELETE /instance/logout/{instanceName}      — logout
  DELETE /instance/delete/{instanceName}      — remove
  POST   /webhook/set/{instanceName}          — reconfigura webhook
  POST   /message/sendText/{instanceName}     — {number, text}
  POST   /message/sendMedia/{instanceName}    — {number, mediatype, media, caption}
"""
import os
import asyncio
import logging
import httpx
from typing import Any

logger = logging.getLogger("zappzen.evo")


class EvolutionError(Exception):
    pass


def _base() -> str:
    url = os.environ["EVOLUTION_API_URL"].rstrip("/")
    return url


def _headers() -> dict:
    return {
        "apikey": os.environ["EVOLUTION_API_KEY"],
        "Content-Type": "application/json",
    }


# Retry config: try up to MAX_ATTEMPTS times, with exponential backoff.
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5  # seconds — waits 0.5s, 1s, 2s between attempts
RETRY_STATUS = {500, 502, 503, 504}


async def _request(method: str, path: str, json: Any = None) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.request(method, f"{_base()}{path}", json=json, headers=_headers())
            if r.status_code in RETRY_STATUS:
                last_err = EvolutionError(f"Evolution {method} {path} -> {r.status_code}: {r.text[:200]}")
                logger.warning("Evolution transient %s on attempt %d/%d: %s %s",
                               r.status_code, attempt, MAX_ATTEMPTS, method, path)
            elif r.status_code >= 400:
                # Non-retriable client error — fail fast.
                raise EvolutionError(f"Evolution {method} {path} -> {r.status_code}: {r.text[:200]}")
            else:
                try:
                    return r.json()
                except Exception:
                    return {"raw": r.text}
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
            last_err = EvolutionError(f"Evolution {method} {path} network error: {e}")
            logger.warning("Evolution network error on attempt %d/%d: %s", attempt, MAX_ATTEMPTS, e)

        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))

    raise last_err or EvolutionError(f"Evolution {method} {path} failed after {MAX_ATTEMPTS} attempts")


async def create_instance(instance_name: str, webhook_url: str) -> dict:
    body = {
        "instanceName": instance_name,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
        "webhook": {
            "url": webhook_url,
            "byEvents": False,
            "base64": True,
            "events": [
                "QRCODE_UPDATED",
                "CONNECTION_UPDATE",
                "MESSAGES_UPSERT",
            ],
        },
    }
    return await _request("POST", "/instance/create", body)


async def fetch_qr(instance_name: str) -> dict:
    return await _request("GET", f"/instance/connect/{instance_name}")


async def connection_state(instance_name: str) -> dict:
    return await _request("GET", f"/instance/connectionState/{instance_name}")


async def logout_instance(instance_name: str) -> dict:
    return await _request("DELETE", f"/instance/logout/{instance_name}")


async def send_text(instance_name: str, number: str, text: str) -> dict:
    body = {"number": number, "text": text}
    return await _request("POST", f"/message/sendText/{instance_name}", body)


async def send_media(instance_name: str, number: str, mediatype: str, media_url: str, caption: str = "") -> dict:
    body = {"number": number, "mediatype": mediatype, "media": media_url, "caption": caption}
    return await _request("POST", f"/message/sendMedia/{instance_name}", body)
