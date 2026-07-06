"""Periodic health check for WhatsApp connections.

Every CHECK_INTERVAL seconds, look for tenants with status='conectado' whose
last_webhook_event_at is older than STALE_AFTER seconds. For each, query
Evolution API /instance/connectionState — if the state is not 'open', flip
the local status to 'desconectado' so the tenant knows and can reconnect.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from db import get_db
import evolution_client as evo

logger = logging.getLogger("zappzen.health")

CHECK_INTERVAL = 60          # seconds between sweeps
STALE_AFTER = 5 * 60         # 5 minutes with no webhook event → probe

_task: asyncio.Task | None = None


async def _probe_one(row: dict):
    db = get_db()
    tenant_id = row["tenant_id"]
    inst = row.get("evolution_instance_name")
    if not inst:
        return
    try:
        state_resp = await evo.connection_state(inst)
    except evo.EvolutionError as e:
        logger.warning("Evolution connectionState failed for %s: %s", inst, e)
        return
    # v2 returns { instance: { instanceName, state } }
    inst_data = state_resp.get("instance") if isinstance(state_resp, dict) else None
    state = None
    if isinstance(inst_data, dict):
        state = (inst_data.get("state") or "").lower()
    else:
        state = (state_resp.get("state") or "").lower() if isinstance(state_resp, dict) else ""

    now = datetime.now(timezone.utc).isoformat()
    if state == "open":
        # Alive — bump the timestamp so we don't probe again immediately.
        await db.whatsapp_connections.update_one(
            {"tenant_id": tenant_id},
            {"$set": {"last_webhook_event_at": now, "updated_at": now}},
        )
    else:
        logger.info("Connection %s appears dead (state=%r) — marking desconectado", inst, state)
        await db.whatsapp_connections.update_one(
            {"tenant_id": tenant_id},
            {"$set": {"status": "desconectado", "qrcode_atual": None, "updated_at": now}},
        )


async def _sweep():
    db = get_db()
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
            await _probe_one(row)
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
