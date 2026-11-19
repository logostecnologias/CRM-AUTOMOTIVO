"""Teste da tela de Configuracoes: troca de senha, nome e dados da empresa.

Onde estao os riscos deste modulo, e por isso o que se testa aqui:

- **A troca de senha** e a unica escrita de credencial que parte do proprio
  usuario. Errar a conferencia da senha atual, deixar o hash antigo valendo, ou
  permitir que o modo suporte troque a senha do Super Admin achando que troca a
  do cliente, sao falhas que nao dao erro nenhum — dao acesso.
- **A empresa** devolve so os dados dela, isolada por tenant. Os planos sairam
  em 18/11/2026: nada de plano, preco ou limite pode voltar a aparecer aqui.
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, r"c:\Projetos DEV\LOGOS - ZappZen\ZappZen-BotsWpp\backend")
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste"}.items():
    os.environ.setdefault(k, v)

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import auth
import routes.settings as rset
import routes.campaigns as rcamp

_MODULOS_FAKE = (rset, rcamp)


def _conectar_fake():
    """Reaplicado a cada teste, nao so no import: o pytest carrega todos os
    modulos de teste no mesmo processo e `get_db` e atributo de modulo."""
    db_mod.get_db = lambda: DB
    for _m in _MODULOS_FAKE:
        _m.get_db = lambda: DB


TENANT_A, TENANT_B = "t-a", "t-b"
SENHA_A = "senha-original-1"

ADMIN_A = {"id": "u-a", "tenant_id": TENANT_A, "role": "tenant_admin",
           "name": "Ana", "email": "ana@x.com"}
AGENTE_A = {"id": "u-ag", "tenant_id": TENANT_A, "role": "agent",
            "name": "Aline", "email": "aline@x.com"}
ADMIN_B = {"id": "u-b", "tenant_id": TENANT_B, "role": "tenant_admin",
           "name": "Bruno", "email": "bruno@x.com"}

ok = 0


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        raise AssertionError(nome)


async def erro(coro):
    try:
        await coro
    except HTTPException as e:
        return e.status_code, str(e.detail)
    return None, None


async def etapa_semear():
    print("\n[semear]")
    await DB.tenants.insert_one({"id": TENANT_A, "name": "Logos Tecnologias",
                                 "status": "active",
                                 "created_at": "2026-03-12T10:00:00+00:00"})
    await DB.tenants.insert_one({"id": TENANT_B, "name": "Revenda B",
                                 "status": "active",
                                 "created_at": "2026-05-01T10:00:00+00:00"})
    for u, senha in ((ADMIN_A, SENHA_A), (AGENTE_A, "outra-senha-9"), (ADMIN_B, "b-senha-77")):
        await DB.users.insert_one({**u, "status": "active",
                                   "password_hash": auth.hash_password(senha)})
    check("semeadura pronta", await DB.users.count_documents({}) == 3)


# ---------------------------------------------------------------------------
# Senha
# ---------------------------------------------------------------------------

async def etapa_troca_de_senha():
    print("\n[troca de senha]")
    NOVA = "nova-senha-forte"

    st, det = await erro(rset.trocar_senha(
        rset.SenhaIn(senha_atual="chute-errado", nova_senha=NOVA), ADMIN_A))
    check("senha atual errada e recusada", st == 400, (st, det))
    doc = await DB.users.find_one({"id": ADMIN_A["id"]})
    check("e o hash nao foi tocado na tentativa recusada",
          auth.verify_password(SENHA_A, doc["password_hash"]))

    st, det = await erro(rset.trocar_senha(
        rset.SenhaIn(senha_atual=SENHA_A, nova_senha="curta1"), ADMIN_A))
    check("nova senha curta e recusada", st == 400, (st, det))
    check("e a recusa diz o minimo", str(rset.SENHA_MINIMA) in (det or ""), det)

    st, det = await erro(rset.trocar_senha(
        rset.SenhaIn(senha_atual=SENHA_A, nova_senha=SENHA_A), ADMIN_A))
    check("repetir a senha atual e recusado", st == 400, (st, det))

    r = await rset.trocar_senha(rset.SenhaIn(senha_atual=SENHA_A, nova_senha=NOVA), ADMIN_A)
    check("troca valida passa", r["ok"] is True, r)
    doc = await DB.users.find_one({"id": ADMIN_A["id"]})
    check("a senha nova vale agora", auth.verify_password(NOVA, doc["password_hash"]))
    check("e a antiga parou de valer",
          not auth.verify_password(SENHA_A, doc["password_hash"]))

    # Trocar a senha de A nao pode encostar em ninguem mais.
    outro = await DB.users.find_one({"id": AGENTE_A["id"]})
    check("a senha do colega ficou intacta",
          auth.verify_password("outra-senha-9", outro["password_hash"]))

    # E o caminho volta ao normal para as etapas seguintes.
    await rset.trocar_senha(rset.SenhaIn(senha_atual=NOVA, nova_senha=SENHA_A), ADMIN_A)
    check("voltou para a senha original", auth.verify_password(
        SENHA_A, (await DB.users.find_one({"id": ADMIN_A["id"]}))["password_hash"]))


async def etapa_modo_suporte():
    print("\n[modo suporte]")
    # Em impersonation o token e do Super Admin com papel trocado: `user["id"]`
    # continua sendo o dele. Sem esta guarda, o suporte trocaria a senha do
    # Super Admin achando que troca a do cliente.
    sa_no_cliente = {**ADMIN_A, "id": "u-super", "impersonation_id": "imp-1"}
    st, det = await erro(rset.trocar_senha(
        rset.SenhaIn(senha_atual=SENHA_A, nova_senha="qualquer-coisa-8"), sa_no_cliente))
    check("modo suporte nao troca senha", st == 403, (st, det))
    st, det = await erro(rset.atualizar_conta(rset.ContaIn(name="Invasor"), sa_no_cliente))
    check("modo suporte nao troca nome", st == 403, (st, det))
    doc = await DB.users.find_one({"id": ADMIN_A["id"]})
    check("e a conta do cliente ficou como estava", doc["name"] == "Ana", doc.get("name"))


async def etapa_nome():
    print("\n[nome]")
    r = await rset.atualizar_conta(rset.ContaIn(name="  Ana Paula  "), ADMIN_A)
    check("nome e aparado", r["name"] == "Ana Paula", r)
    doc = await DB.users.find_one({"id": ADMIN_A["id"]})
    check("e gravado", doc["name"] == "Ana Paula", doc.get("name"))
    st, _ = await erro(rset.atualizar_conta(rset.ContaIn(name="   "), ADMIN_A))
    check("nome so de espaco e recusado", st == 400, st)


# ---------------------------------------------------------------------------
# Empresa e uso
# ---------------------------------------------------------------------------

async def etapa_empresa():
    print("\n[empresa]")
    r = await rset.empresa(ADMIN_A)
    check("devolve o nome da empresa, nao o id",
          r["empresa"]["nome"] == "Logos Tecnologias", r["empresa"])
    check("sem plano nem uso de limites", set(r) == {"empresa"}, set(r))

    # Isolamento: cada admin so ve a propria empresa.
    rb = await rset.empresa(ADMIN_B)
    check("admin de B ve a empresa de B", rb["empresa"]["nome"] == "Revenda B", rb["empresa"])


async def etapa_barreira_de_permissao():
    print("\n[barreira de permissao]")
    # Chamar a funcao da rota direto NAO executa o Depends — a guarda so pode
    # ser conferida onde ela e declarada, na assinatura do endpoint.
    def deps_de(fn):
        return [p.default.dependency for p in inspect.signature(fn).parameters.values()
                if hasattr(p.default, "dependency")]

    check("empresa exige tenant_admin",
          auth.require_tenant_admin in deps_de(rset.empresa), deps_de(rset.empresa))
    # Conta e senha sao do proprio usuario: qualquer pessoa autenticada, porque
    # a guarda ali e "so mexe em si mesmo", nao o papel.
    for fn in (rset.atualizar_conta, rset.trocar_senha):
        check(f"{fn.__name__} exige apenas autenticacao",
              auth.get_current_user in deps_de(fn), deps_de(fn))

    st, _ = await erro(auth.require_tenant_admin(
        {"id": "x", "role": "agent", "tenant_id": TENANT_A}))
    check("atendente e barrado por require_tenant_admin", st == 403, st)


# ---------------------------------------------------------------------------

def test_suite():
    _conectar_fake()

    async def _tudo():
        await etapa_semear()
        await etapa_troca_de_senha()
        await etapa_modo_suporte()
        await etapa_nome()
        await etapa_empresa()
        await etapa_barreira_de_permissao()
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())
