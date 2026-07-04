from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends

from db import get_db
from auth import require_tenant_admin

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/metrics")
async def dashboard_metrics(user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    return {
        "active_conversations": await db.conversation_sessions.count_documents(
            {"tenant_id": tenant_id, "status": "ativa"}
        ),
        "awaiting_human": await db.conversation_sessions.count_documents(
            {"tenant_id": tenant_id, "status": "aguardando_humano"}
        ),
        "messages_month": await db.messages_log.count_documents(
            {"tenant_id": tenant_id, "timestamp": {"$gte": since}}
        ),
        "active_bots": await db.bots.count_documents(
            {"tenant_id": tenant_id, "status": "ativo"}
        ),
        "total_contacts": await db.contacts.count_documents({"tenant_id": tenant_id}),
        "total_bots": await db.bots.count_documents({"tenant_id": tenant_id}),
    }
