"""Aplica os limites (max_bots/max_conexoes/max_usuarios) do plano vinculado
ao tenant. Tenant sem plan_id (ou plano sem o campo de limite) fica sem
restrição — trata como "ilimitado" em vez de bloquear."""
from fastapi import HTTPException

# (collection, campo do plano, rótulo em português)
LIMITS = [
    ("bots", "max_bots", "robôs"),
    ("whatsapp_connections", "max_conexoes", "conexões WhatsApp"),
    ("users", "max_usuarios", "usuários"),
]


async def plan_excess(db, tenant_id: str, plan: dict) -> list[str]:
    """Onde o tenant já passa dos limites do plano informado. Usado ao trocar o
    plano de uma empresa: a troca é permitida, mas o super admin precisa saber
    que ela fica acima do teto — o excedente continua funcionando, porque
    enforce_plan_limit só barra criações novas."""
    out = []
    for collection, field, label in LIMITS:
        limit = plan.get(field)
        if limit is None:
            continue
        count = await db[collection].count_documents({"tenant_id": tenant_id})
        if count > limit:
            out.append(f"{count} {label} (máx. {limit})")
    return out


async def enforce_plan_limit(db, tenant_id: str, collection: str, field: str, label: str):
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "plan_id": 1})
    if not tenant or not tenant.get("plan_id"):
        return
    plan = await db.plans.find_one({"id": tenant["plan_id"]}, {"_id": 0})
    if not plan or plan.get(field) is None:
        return
    limit = plan[field]
    count = await db[collection].count_documents({"tenant_id": tenant_id})
    if count >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Limite do plano \"{plan['nome']}\" atingido: máx. {limit} {label}",
        )
