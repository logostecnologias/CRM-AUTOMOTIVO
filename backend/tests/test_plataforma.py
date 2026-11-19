"""Teste da visao do super admin: saude por empresa, visao geral e ficha.

O risco aqui nao e uma tela errada, e um alerta que nao aparece: empresa com
WhatsApp fora do ar que a visao geral diz estar "tudo em dia", ou empresa
parada que nao entra na lista de atencao. Por isso cada tipo de problema tem
uma empresa semeada so para ele, e uma empresa saudavel que nao pode aparecer
em alerta nenhum.

Os planos sairam em 18/11/2026: nenhum alerta, campo ou numero de plano pode
voltar. O unico teto que sobrou e o de IA, como campo da empresa, e ele conta
so o consumo pago pela plataforma.
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
from fastapi import HTTPException
from pydantic import ValidationError

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import auth
import migrations
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


async def erro(coro):
    try:
        await coro
    except HTTPException as e:
        return e.status_code, str(e.detail)
    return None, None


def ha(dias=0, horas=0):
    return (datetime.now(timezone.utc) - timedelta(days=dias, hours=horas)).isoformat()


MES = datetime.now(timezone.utc).strftime("%Y-%m")
SUPER = {"id": "u-super", "role": "super_admin", "tenant_id": None, "email": "sa@logos.com"}


async def etapa_semear():
    print("\n[semear]")
    empresas = [
        # (id, nome, status, marca, criada)
        ("t-ok", "Saudavel", "active", "logos", ha(60)),
        ("t-fora", "Fora do ar", "active", "r3", ha(60)),
        ("t-parada", "Parada", "active", "r3", ha(60)),
        ("t-sem", "Sem WhatsApp", "active", "logos", ha(10)),
        ("t-nova", "Recem criada", "active", "logos", ha(0, 2)),
        ("t-susp", "Suspensa", "suspended", "logos", ha(60)),
        ("t-ia", "IA no teto", "active", "logos", ha(60)),
    ]
    for tid, nome, status, marca, criada in empresas:
        await DB.tenants.insert_one({"id": tid, "name": nome, "status": status, "marca": marca,
                                     "created_at": criada})
        await DB.users.insert_one({"id": f"u-{tid}", "tenant_id": tid, "role": "tenant_admin",
                                   "email": f"admin@{tid}.com", "name": "Admin",
                                   "created_at": criada})

    for tid, status in (("t-ok", "conectado"), ("t-fora", "desconectado"),
                        ("t-parada", "conectado"), ("t-susp", "desconectado"),
                        ("t-ia", "conectado")):
        await DB.whatsapp_connections.insert_one({"id": f"c-{tid}", "tenant_id": tid,
                                                  "nome": "Loja", "status": status})

    # Saudavel: 3 mensagens nesta semana, 1 na anterior; duas conversas, uma
    # pega por atendente; um atendente que entrou ontem.
    for d in (1, 2, 3, 9):
        await DB.messages_log.insert_one({"tenant_id": "t-ok", "timestamp": ha(d)})
    await DB.conversation_sessions.insert_one({"id": "s1", "tenant_id": "t-ok", "created_at": ha(1)})
    await DB.conversation_sessions.insert_one({"id": "s2", "tenant_id": "t-ok", "created_at": ha(1),
                                               "assumido_em": ha(1)})
    await DB.users.insert_one({"id": "u-atend", "tenant_id": "t-ok", "role": "agent",
                               "email": "vendedor@t-ok.com", "name": "Vendedor",
                               "created_at": ha(30), "ultimo_acesso": ha(1)})
    # Leads: 2 nesta semana, 1 na anterior, 1 antigo que nao conta.
    for i, d in enumerate((1, 2, 10, 40)):
        await DB.contacts.insert_one({"id": f"ct{i}", "tenant_id": "t-ok", "created_at": ha(d)})
    # Vendas: uma ganha no mes, uma perdida e uma ganha ha 60 dias.
    await DB.deals.insert_one({"id": "d1", "tenant_id": "t-ok", "status": "ganho",
                               "fechado_em": ha(5), "valor": 85000})
    await DB.deals.insert_one({"id": "d2", "tenant_id": "t-ok", "status": "perdido",
                               "fechado_em": ha(5), "valor": 50000})
    await DB.deals.insert_one({"id": "d3", "tenant_id": "t-ok", "status": "ganho",
                               "fechado_em": ha(60), "valor": 40000})
    # Parada: so mensagem de 20 dias atras.
    await DB.messages_log.insert_one({"tenant_id": "t-parada", "timestamp": ha(20)})
    await DB.messages_log.insert_one({"tenant_id": "t-fora", "timestamp": ha(1)})
    await DB.messages_log.insert_one({"tenant_id": "t-ia", "timestamp": ha(1)})

    # IA: t-ia tem teto de 1000 e ja gastou 1200 pela plataforma. t-ok gastou
    # 5000 na conta propria, o que nao pode virar alerta nem custo nosso.
    await DB.tenants.update_one({"id": "t-ia"}, {"$set": {"limite_tokens_ia_mes": 1000}})
    await DB.ai_usage.insert_one({"tenant_id": "t-ia", "mes": MES, "origem": "plataforma",
                                  "tokens": 1200, "custo_usd": 0.5})
    await DB.tenants.update_one({"id": "t-ok"}, {"$set": {"limite_tokens_ia_mes": 1000}})
    await DB.ai_usage.insert_one({"tenant_id": "t-ok", "mes": MES, "origem": "cliente",
                                  "tokens": 5000, "custo_usd": 2.0})

    # Linha do tempo: uma acao de auditoria e uma entrada em modo suporte.
    await DB.users.insert_one({"id": "u-super", "role": "super_admin", "email": "sa@logos.com",
                               "name": "SA", "created_at": ha(100)})
    await DB.audit_log.insert_one({"id": "a1", "acao": "contact.export", "tenant_id": "t-ok",
                                   "ator_email": "admin@t-ok.com", "em": ha(0, 3)})
    await DB.impersonation_log.insert_one({"id": "i1", "super_admin_id": "u-super",
                                           "tenant_id": "t-fora", "iniciado_em": ha(0, 1)})
    check("semeado", await DB.tenants.count_documents({}) == 7)


async def etapa_lista():
    print("\n[lista de empresas]")
    lista = await rt.list_tenants(SUPER)
    por = {t["id"]: t for t in lista}
    tipos = lambda tid: {p["tipo"] for p in por[tid]["saude"]["problemas"]}

    check("todas as empresas na lista", len(lista) == 7)
    check("nenhum vestigio de plano na linha", all("plan" not in t for t in lista))
    check("o email do admin vem na linha",
          por["t-ok"]["saude"]["admins"][0]["email"] == "admin@t-ok.com")
    check("saudavel sem problema nenhum", tipos("t-ok") == set(), tipos("t-ok"))
    s = por["t-ok"]["saude"]
    check("mensagens da semana e da anterior",
          (s["mensagens_7d"], s["mensagens_7d_anterior"]) == (3, 1),
          (s["mensagens_7d"], s["mensagens_7d_anterior"]))
    check("conversas da semana", s["conversas_7d"] == 2, s["conversas_7d"])
    check("leads da semana e da anterior",
          (s["leads_7d"], s["leads_7d_anterior"]) == (2, 1), (s["leads_7d"], s["leads_7d_anterior"]))
    check("vendas: so o ganho dos ultimos 30 dias",
          (s["vendas_30d"], s["vendas_30d_valor"]) == (1, 85000.0),
          (s["vendas_30d"], s["vendas_30d_valor"]))
    check("equipe e atendentes contados", (s["usuarios"], s["atendentes"]) == (2, 1),
          (s["usuarios"], s["atendentes"]))
    check("ultimo acesso da equipe", s["ultimo_acesso"] is not None, s["ultimo_acesso"])
    check("consumo na conta propria nao conta no teto",
          s["ia"]["tokens_plataforma"] == 0 and s["ia"]["tokens"] == 5000, s["ia"])
    check("conexao fora do ar vira problema alto", "conexoes" in tipos("t-fora"), tipos("t-fora"))
    check("empresa com WhatsApp sem mensagem na semana esta parada",
          "parada" in tipos("t-parada"), tipos("t-parada"))
    check("e a ultima mensagem vem junto",
          por["t-parada"]["saude"]["ultima_mensagem"] is not None)
    check("cadastro sem WhatsApp apontado", tipos("t-sem") == {"sem_whatsapp"}, tipos("t-sem"))
    check("empresa recem-criada nao vira alerta", tipos("t-nova") == set(), tipos("t-nova"))
    check("suspensa nao gera alerta", tipos("t-susp") == set(), tipos("t-susp"))
    check("IA no teto e problema alto", tipos("t-ia") == {"ia_no_teto"}, tipos("t-ia"))
    check("e a porcentagem vem calculada", por["t-ia"]["saude"]["ia"]["pct"] == 120,
          por["t-ia"]["saude"]["ia"])


async def etapa_visao():
    print("\n[visao geral]")
    v = await rt.visao_geral(SUPER)
    check("ativas e suspensas", (v["empresas"]["ativas"], v["empresas"]["suspensas"]) == (6, 1))
    check("sem receita nem plano", "receita" not in v, list(v))
    check("semaforo: alto, medio e em dia",
          v["faixas"] == {"alto": 2, "medio": 2, "em_dia": 2}, v["faixas"])
    marcas = {m["marca"]: m for m in v["por_marca"]}
    check("empresas por marca", marcas["r3"]["empresas"] == 2 and marcas["logos"]["empresas"] == 4,
          marcas)
    check("mensagens da semana somadas", v["semana"]["mensagens"] == 5, v["semana"])
    check("leads da semana somados", v["semana"]["leads"] == 2, v["semana"])
    check("vendas do mes somadas", v["vendas_30d"] == {"n": 1, "valor": 85000.0}, v["vendas_30d"])
    check("custo de IA so o pago pela plataforma", v["ia"]["custo_usd"] == 0.5, v["ia"])
    check("ranking de IA pelo consumo da plataforma", v["ia"]["ranking"][0]["id"] == "t-ia",
          v["ia"]["ranking"])
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
    acoes = [a["acao"] for a in v["atividade"]]
    check("linha do tempo junta suporte e auditoria, mais recente primeiro",
          acoes[:2] == ["suporte.entrar", "contact.export"], acoes)
    check("o modo suporte diz quem entrou e onde",
          v["atividade"][0]["ator"] == "sa@logos.com" and v["atividade"][0]["empresa"] == "Fora do ar",
          v["atividade"][0])


async def etapa_detalhe():
    print("\n[ficha]")
    d = await rt.tenant_detalhe("t-ok", SUPER)
    check("equipe com email e ultimo acesso",
          any(u["email"] == "vendedor@t-ok.com" and u["ultimo_acesso"] for u in d["usuarios"]))
    check("resumo da operacao", d["resumo"]["contatos"] == 4, d["resumo"])
    check("serie da propria empresa", sum(x["automatico"] + x["humano"] for x in d["serie"]) == 2)
    check("historico so da empresa",
          [h["acao"] for h in d["historico"]] == ["contact.export"], d["historico"])
    f = await rt.tenant_detalhe("t-fora", SUPER)
    check("conexoes listadas", f["conexoes"][0]["status"] == "desconectado")
    st, _ = await erro(rt.tenant_detalhe("nao-existe", SUPER))
    check("empresa inexistente da 404", st == 404, st)


async def etapa_configurar():
    print("\n[configurar a empresa]")
    t = await rt.update_tenant("t-ia", rt.TenantUpdate(limite_tokens_ia_mes=5000), SUPER)
    check("teto de IA gravado", t["limite_tokens_ia_mes"] == 5000, t)
    t = await rt.update_tenant("t-ia", rt.TenantUpdate(limite_tokens_ia_mes=None), SUPER)
    check("nulo enviado limpa o teto", t["limite_tokens_ia_mes"] is None, t)
    t = await rt.update_tenant("t-ia", rt.TenantUpdate(name="IA Renomeada"), SUPER)
    check("mexer no nome nao apaga o resto", t["name"] == "IA Renomeada" and t["status"] == "active", t)
    t = await rt.update_tenant("t-ia", rt.TenantUpdate(retencao_midia_dias=0), SUPER)
    check("retencao 0 (nunca apagar) e aceita", t["retencao_midia_dias"] == 0, t)
    try:
        rt.TenantUpdate(status="qualquer")
        check("status fora da lista e recusado", False, "passou")
    except ValidationError:
        check("status fora da lista e recusado", True)
    check("cada mudanca deixou rastro",
          await DB.audit_log.count_documents({"acao": "tenant.update", "tenant_id": "t-ia"}) == 4)


async def etapa_senha():
    print("\n[redefinir senha]")
    antes = await DB.users.find_one({"id": "u-atend"})
    r = await rt.redefinir_senha("t-ok", "u-atend", rt.SenhaNova(password="NovaSenha2026"), SUPER)
    check("a rota confirma", r == {"ok": True}, r)
    depois = await DB.users.find_one({"id": "u-atend"})
    check("a senha nova vale", auth.verify_password("NovaSenha2026", depois["password_hash"]))
    check("e as sessoes abertas caem",
          (depois.get("token_version") or 0) == (antes.get("token_version") or 0) + 1)
    check("deixa rastro",
          await DB.audit_log.count_documents({"acao": "user.senha_redefinida"}) == 1)
    st, _ = await erro(rt.redefinir_senha("t-fora", "u-atend",
                                          rt.SenhaNova(password="OutraSenha99"), SUPER))
    check("usuario de outra empresa nao e alcancado", st == 404, st)
    try:
        rt.SenhaNova(password="curta")
        check("senha curta recusada", False, "passou")
    except ValidationError:
        check("senha curta recusada", True)


async def etapa_migracao():
    print("\n[migracao dos planos]")
    await DB.plans.insert_one({"id": "p-velho", "nome": "Pro", "max_tokens_ia_mes": 7000,
                               "retencao_midia_dias": 365})
    await DB.tenants.insert_one({"id": "t-legada", "name": "Legada", "status": "active",
                                 "plan_id": "p-velho", "created_at": ha(90)})
    n = await migrations.planos_para_empresa(DB)
    t = await DB.tenants.find_one({"id": "t-legada"})
    check("teto e retencao copiados do plano",
          (n, t["limite_tokens_ia_mes"], t["retencao_midia_dias"]) == (1, 7000, 365), (n, t))
    check("idempotente", await migrations.planos_para_empresa(DB) == 0)
    check("nao apaga nada: plano e plan_id continuam",
          t["plan_id"] == "p-velho" and await DB.plans.count_documents({}) == 1)


async def etapa_barreira():
    print("\n[permissao]")
    for f in (rt.list_tenants, rt.tenant_detalhe, rt.visao_geral, rt.update_tenant,
              rt.redefinir_senha, rt.create_tenant, rt.delete_tenant):
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
        await etapa_configurar()
        await etapa_senha()
        await etapa_migracao()
        await etapa_barreira()
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())


if __name__ == "__main__":
    test_suite()
