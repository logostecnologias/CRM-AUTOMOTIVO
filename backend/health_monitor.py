"""Periodic health check for WhatsApp connections.

Two things happen on every CHECK_INTERVAL sweep:
  - status='pareando' connections are always probed against WuzAPI's
    /session/status — if it reports connected+loggedIn, we promote them to
    'conectado' locally. This is what makes pairing complete in the UI even
    when the WuzAPI -> gateway -> backend webhook can't be delivered (e.g.
    local dev, where the backend isn't publicly reachable) — it's a
    polling fallback for the same signal the 'PairSuccess'/'Connected'
    webhook events would have given us.
  - status='conectado' connections whose last_webhook_event_at is older
    than STALE_AFTER are probed too — if WuzAPI no longer reports them as
    connected+loggedIn, we flip the local status to 'desconectado' so the
    tenant knows and can reconnect.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from db import get_db
import wuzapi_client as wuzapi

logger = logging.getLogger("zappzen.health")

CHECK_INTERVAL = 5           # seconds between sweeps
STALE_AFTER = 5 * 60         # 5 minutes with no webhook event → probe a 'conectado' row

_task: asyncio.Task | None = None


def _numero_from_jid(jid: str) -> str | None:
    return jid.split(":")[0].split("@")[0] if jid else None


async def _probe_pareando(row: dict):
    db = get_db()
    conn_id = row["id"]
    token = row.get("wuzapi_token")
    if not token:
        return
    try:
        state = await wuzapi.connection_state(token)
    except wuzapi.WuzapiError as e:
        logger.warning("WuzAPI session/status failed for %s: %s", conn_id, e)
        return

    if state.get("connected") and state.get("loggedIn"):
        now = datetime.now(timezone.utc).isoformat()
        logger.info("Connection %s finished pairing (detected via polling) — marking conectado", conn_id)
        await db.whatsapp_connections.update_one(
            {"id": conn_id},
            {"$set": {
                "status": "conectado",
                "qrcode_atual": None,
                "numero": _numero_from_jid(state.get("jid", "")),
                "last_webhook_event_at": now,
                "updated_at": now,
            }},
        )


async def _probe_conectado(row: dict):
    db = get_db()
    conn_id = row["id"]
    token = row.get("wuzapi_token")
    if not token:
        return
    try:
        state = await wuzapi.connection_state(token)
    except wuzapi.WuzapiError as e:
        logger.warning("WuzAPI session/status failed for %s: %s", conn_id, e)
        return

    now = datetime.now(timezone.utc).isoformat()
    if state.get("connected") and state.get("loggedIn"):
        # Alive — bump the timestamp so we don't probe again immediately.
        await db.whatsapp_connections.update_one(
            {"id": conn_id},
            {"$set": {"last_webhook_event_at": now, "updated_at": now}},
        )
    else:
        logger.info("Connection %s appears dead (connected=%r loggedIn=%r) — marking desconectado",
                    conn_id, state.get("connected"), state.get("loggedIn"))
        await db.whatsapp_connections.update_one(
            {"id": conn_id},
            {"$set": {"status": "desconectado", "qrcode_atual": None, "updated_at": now}},
        )


async def _sweep():
    db = get_db()

    async for row in db.whatsapp_connections.find({"status": "pareando"}):
        try:
            await _probe_pareando(row)
        except Exception as e:
            logger.exception("Pairing probe failed for connection %s: %s", row.get("id"), e)

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER)).isoformat()
    cursor = db.whatsapp_connections.find({
        "status": "conectado",
        "$or": [
            {"last_webhook_event_at": None},
            {"last_webhook_event_at": {"$lt": cutoff}},
        ],
    })
    async for row in cursor:
        try:
            await _probe_conectado(row)
        except Exception as e:
            logger.exception("Health probe failed for tenant %s: %s", row.get("tenant_id"), e)


async def _loop():
    logger.info("WhatsApp health monitor started (interval=%ds, stale=%ds)", CHECK_INTERVAL, STALE_AFTER)
    while True:
        try:
            await _sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Health sweep crashed: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
