"""Tela de Configurações da empresa: a própria conta e os dados da empresa.

**Trocar a própria senha.** `/api/users` inteiro é `require_tenant_admin` e
edita *outro* usuário — não havia caminho para alguém trocar a sua, nem
conferência da senha atual.

Até 18/11/2026 a tela também mostrava o plano contratado e o uso contra cada
limite. Os planos saíram do sistema; a empresa fica só com os dados dela.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import (get_current_user, require_tenant_admin,
                  hash_password, verify_password)
from db import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])

SENHA_MINIMA = 8


def _bloqueia_modo_suporte(user: dict):
    """Em impersonation o token é do Super Admin com o papel trocado, então
    `user["id"]` continua sendo o **dele**. Editar a conta daqui mexeria na
    credencial do Super Admin achando que mexe na do cliente.
    """
    if user.get("impersonation_id"):
        raise HTTPException(
            status_code=403,
            detail="Em modo suporte não é possível alterar dados de conta. "
                   "Saia do modo suporte para editar a sua.",
        )


# ---------------------------------------------------------------------------
# Minha conta
# ---------------------------------------------------------------------------

class ContaIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/conta")
async def atualizar_conta(body: ContaIn, user=Depends(get_current_user)):
    """O nome é o que aparece no prefixo de toda mensagem enviada por um
    atendente (`send_human_message`), então trocá-lo muda o que o contato lê."""
    _bloqueia_modo_suporte(user)
    nome = body.name.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="O nome não pode ficar vazio")
    await get_db().users.update_one({"id": user["id"]}, {"$set": {"name": nome}})
    return {"ok": True, "name": nome}


class SenhaIn(BaseModel):
    senha_atual: str
    nova_senha: str


@router.post("/senha")
async def trocar_senha(body: SenhaIn, user=Depends(get_current_user)):
    """A senha atual é exigida mesmo já havendo sessão válida: o cookie é
    httpOnly e de longa duração, então uma máquina destravada bastaria para
    trocar a senha e tomar a conta.
    """
    _bloqueia_modo_suporte(user)
    db = get_db()
    # `get_current_user` remove o hash do documento que devolve — daí reler.
    doc = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 1})
    if not doc or not verify_password(body.senha_atual, doc.get("password_hash") or ""):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    if len(body.nova_senha) < SENHA_MINIMA:
        raise HTTPException(
            status_code=400,
            detail=f"A nova senha precisa de pelo menos {SENHA_MINIMA} caracteres",
        )
    if body.nova_senha == body.senha_atual:
        raise HTTPException(status_code=400, detail="A nova senha é igual à atual")
    # `$inc` em token_version invalida toda sessão emitida antes desta troca
    # (ZZ-09): quem tinha o cookie antigo — inclusive numa máquina roubada — é
    # derrubado na próxima requisição.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(body.nova_senha)},
         "$inc": {"token_version": 1}},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Empresa
# ---------------------------------------------------------------------------

@router.get("/empresa")
async def empresa(user=Depends(require_tenant_admin)):
    """Nome, situação e data de cadastro da empresa."""
    db = get_db()
    tenant = await db.tenants.find_one(
        {"id": user["tenant_id"]}, {"_id": 0, "id": 1, "name": 1, "status": 1, "created_at": 1}
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return {
        "empresa": {
            "id": tenant["id"],
            "nome": tenant.get("name"),
            "status": tenant.get("status"),
            "criada_em": tenant.get("created_at"),
        },
    }
