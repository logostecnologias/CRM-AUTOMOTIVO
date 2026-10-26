"""Teste da visao do super admin: saude por empresa e visao geral.

O risco aqui nao e uma tela errada, e um alerta que nao aparece: empresa com
WhatsApp fora do ar que a visao geral diz estar "tudo em dia", ou empresa
parada que nao entra na lista de atencao. Por isso cada tipo de problema tem
uma empresa semeada so para ele, e uma empresa saudavel que nao pode aparecer
em alerta nenhum.
"""
import asyncio
import inspect
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste"}.items():
    os.environ.setdefault(k, v)

from fakedb import FakeDB

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import auth
import routes.tenants as rt

ok = 0


def _conectar_fake():
    db_mod.get_db = lambda: DB
    rt.get_db = lambda: DB
    auth.get_db = lambda: DB


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        raise AssertionError(nome)


def ha(dias=0, horas=0):
    return (datetime.now(timezone.utc) - timedelta(days=dias, hours=horas)).isoformat()


SUPER = {"id": "u-super", "role": "super_admin", "tenant_id": None}


async def etapa_semear():
    print("\n[semear]")
    await DB.plans.insert_one({"id": "p1", "nome": "Pro", "preco_mensal": 200.0,
                               "max_bots": 1, "max_conexoes": 2, "max_usuarios": 10})
    empresas = [
        # (id, nome, status, marca, plano, criada)
        ("t-ok", "Saudavel", "active", "zappzen", "p1", ha(60)),
        ("t-fora", "Fora do ar", "active", "r3", "p1", ha(60)),
        ("t-parada", "Parada", "active", "r3", "p1", ha(60)),
        ("t-sem", "Sem WhatsApp", "active", "zappzen", "p1", ha(10)),
        ("t-nova", "Recem criada", "active", "zappzen", None, ha(0, 2)),
        ("t-susp", "Suspensa", "suspended", "zappzen", "p1", ha(60)),
    ]
    for tid, nome, status, marca, plano, criada in empresas:
        await DB.tenants.insert_one({"id": tid, "name": nome, "status": status, "marca": marca,
                                     "plan_id": plano, "created_at": criada})
        await DB.users.insert_one({"id": f"u-{tid}", "tenant_id": tid, "role": "tenant_admin",
                                   "email": f"admin@{tid}.com", "name": "Admin",
                                   "created_at": criada})

    for tid, status in (("t-ok", "conectado"), ("t-fora", "desconectado"),
                        ("t-parada", "conectado"), ("t-susp", "desconectado")):
        await DB.whatsapp_connections.insert_one({"id": f"c-{tid}", "tenant_id": tid,
                                                  "nome": "Loja", "status": status})

    # Saudavel: 3 mensagens nesta semana, 1 na anterior; duas conversas, uma
    # pega por atendente.
    for d in (1, 2, 3, 9):
        await DB.messages_log.insert_one({"tenant_id": "t-ok", "timestamp": ha(d)})
    await DB.conversation_sessions.insert_one({"id": "s1", "tenant_id": "t-ok", "created_at": ha(1)})
    await DB.conversation_sessions.insert_one({"id": "s2", "tenant_id": "t-ok", "created_at": ha(1),
                                               "assumido_em": ha(1)})
    # Parada: so mensagem de 20 dias atras.
    await DB.messages_log.insert_one({"tenant_id": "t-parada", "timestamp": ha(20)})
    # Fora do ar tambem passou do plano (2 robos, teto 1).
    for b in ("b1", "b2"):
        await DB.bots.insert_one({"id": b, "tenant_id": "t-fora"})
    await DB.messages_log.insert_one({"tenant_id": "t-fora", "timestamp": ha(1)})
    check("semeado", await DB.tenants.count_documents({}) == 6)


async def etapa_lista():
    print("\n[lista de empresas]")
    lista = await rt.list_tenants(SUPER)
    por = {t["id"]: t for t in lista}
    tipos = lambda tid: {p["tipo"] for p in por[tid]["saude"]["problemas"]}

    check("todas as empresas na lista", len(lista) == 6)
    check("o email do admin vem na linha",
          por["t-ok"]["saude"]["admins"][0]["email"] == "admin@t-ok.com")
    check("saudavel sem problema nenhum", tipos("t-ok") == set(), tipos("t-ok"))
    s = por["t-ok"]["saude"]
    check("mensagens da semana e da anterior",
          (s["mensagens_7d"], s["mensagens_7d_anterior"]) == (3, 1),
          (s["mensagens_7d"], s["mensagens_7d_anterior"]))
    check("conversas da semana", s["conversas_7d"] == 2, s["conversas_7d"])
    check("conexao fora do ar vira problema alto", "conexoes" in tipos("t-fora"), tipos("t-fora"))
    check("acima do plano detectado", "acima_plano" in tipos("t-fora"), tipos("t-fora"))
    check("empresa com WhatsApp sem mensagem na semana esta parada",
          "parada" in tipos("t-parada"), tipos("t-parada"))
    check("e a ultima mensagem vem junto",
          por["t-parada"]["saude"]["ultima_mensagem"] is not None)
    check("cadastro sem WhatsApp apontado", tipos("t-sem") == {"sem_whatsapp"}, tipos("t-sem"))
    # Recem-criada esta em implantacao: so o plano vazio e cobrado.
    check("empresa recem-criada nao vira alerta de implantacao",
          tipos("t-nova") == {"sem_plano"}, tipos("t-nova"))
    check("suspensa nao gera alerta", tipos("t-susp") == set(), tipos("t-susp"))


async def etapa_visao():
    print("\n[visao geral]")
    v = await rt.visao_geral(SUPER)
    check("ativas e suspensas", (v["empresas"]["ativas"], v["empresas"]["suspensas"]) == (5, 1))
    # 4 ativas com plano de 200; a suspensa nao paga e a sem plano nao conta.
    check("receita mensal so das ativas com plano", v["receita"]["mensal"] == 800.0,
          v["receita"]["mensal"])
    marcas = {m["marca"]: m for m in v["receita"]["por_marca"]}
    check("receita por marca", marcas["r3"]["receita"] == 400.0, marcas)
    check("mensagens da semana somadas", v["semana"]["mensagens"] == 4, v["semana"])
    tipos = [a["tipo"] for a in v["alertas"]]
    check("alerta alto vem antes do medio", tipos.index("conexoes") < tipos.index("parada"), tipos)
    fora = next(a for a in v["alertas"] if a["tipo"] == "conexoes")
    check("o alerta diz a empresa e onde resolver",
          fora["empresas"][0]["id"] == "t-fora" and fora["empresas"][0]["para"] == "/app/whatsapp")
    check("serie de 14 dias, todos presentes", len(v["serie"]) == 14)
    total = sum(d["automatico"] + d["humano"] for d in v["serie"])
    humano = sum(d["humano"] for d in v["serie"])
    check("serie separa atendente de automatico", (total, humano) == (2, 1), (total, humano))
    check("quem mais usou vem no topo", v["top"][0]["id"] == "t-ok", v["top"])


async def etapa_detalhe():
    print("\n[detalhe]")
    d = await rt.tenant_detalhe("t-fora", SUPER)
    check("equipe com email", d["usuarios"][0]["email"] == "admin@t-fora.com")
    check("conexoes listadas", d["conexoes"][0]["status"] == "desconectado")
    robos = next(l for l in d["uso"] if l["chave"] == "max_bots")
    check("uso do plano pela mesma conta do cliente", (robos["usado"], robos["limite"]) == (2, 1))


async def etapa_barreira():
    print("\n[permissao]")
    for f in (rt.list_tenants, rt.tenant_detalhe, rt.visao_geral):
        guarda = [p.default.dependency for p in inspect.signature(f).parameters.values()
                  if hasattr(p.default, "dependency")]
        check(f"{f.__name__} exige super admin", guarda == [auth.require_super_admin])


def test_suite():
    _conectar_fake()

    async def _tudo():
        await etapa_semear()
        await etapa_lista()
        await etapa_visao()
        await etapa_detalhe()
        await etapa_barreira()
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())


if __name__ == "__main__":
    test_suite()
