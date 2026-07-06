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
import httpx
from typing import Any


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


async def _request(method: str, path: str, json: Any = None) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.request(method, f"{_base()}{path}", json=json, headers=_headers())
        if r.status_code >= 400:
            raise EvolutionError(f"Evolution {method} {path} -> {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}


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
