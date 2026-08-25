"""Teste de ponta a ponta do fluxo de campanha, com Mongo falso e WuzAPI falsa."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, r"c:\Projetos DEV\LOGOS - ZappZen\ZappZen-BotsWpp\backend")
os.environ.setdefault("MONGO_URL", "mongodb://x/")
os.environ.setdefault("DB_NAME", "x")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("WUZAPI_GATEWAY_URL", "http://x")

from fakedb import FakeDB

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import campaigns
import campaign_runner
import flow_runtime
import outbound
import wuzapi_client

# get_db foi importado por nome dentro dos modulos — troca cada referencia.
for mod in (campaigns, campaign_runner, flow_runtime, outbound):
    mod.get_db = lambda: DB

ENVIADOS = []


async def fake_send_text(token, numero, texto):
    ENVIADOS.append(("text", token, numero, texto))
    return {"ok": True}


async def fake_send_media(token, numero, kind, media, caption, filename=None):
    ENVIADOS.append(("media", token, numero, caption))
    return {"ok": True}


for mod in (campaigns, flow_runtime):
    mod.wuzapi.send_text = fake_send_text
    mod.wuzapi.send_media = fake_send_media
async def _sem_avatar(*a, **k):
    return None
flow_runtime._fetch_avatar_bg = _sem_avatar

_MODULOS_FAKE = (campaign_runner, campaigns, flow_runtime, outbound)


def _conectar_fake():
    """(Re)aponta o `get_db` de cada módulo para o Mongo falso DESTE arquivo.

    Precisa ser chamado no início do teste, não só no import: o pytest importa
    todos os módulos de teste no mesmo processo, e `get_db` é atributo de módulo
    compartilhado — sem isto, o último arquivo importado ficaria com o banco de
    todos, e os testes anteriores rodariam contra dados de outra suíte.
    """
    db_mod.get_db = lambda: DB
    for _m in _MODULOS_FAKE:
        _m.get_db = lambda: DB
    for _m in (campaigns, flow_runtime):
        _m.wuzapi.send_text = fake_send_text
        _m.wuzapi.send_media = fake_send_media
    flow_runtime._fetch_avatar_bg = _sem_avatar


TENANT = "t-1"
CONN = "conn-1"
ok = 0


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome} {extra}")
        raise AssertionError(nome)


async def semear():
    DB._cols.clear()
    await DB.tenants.insert_one({"id": TENANT, "plan_id": "p1"})
    await DB.plans.insert_one({"id": "p1", "nome": "Pro", "max_disparos_mes": 100})
    await DB.whatsapp_connections.insert_one({
        "id": CONN, "tenant_id": TENANT, "nome": "Comercial",
        "status": "conectado", "wuzapi_token": "tok-abc",
        "departamento_padrao_id": "dep-1",
    })
    for i, (nome, num, tags, opt) in enumerate([
        ("Maria Silva", "5511900000001", ["vip"], False),
        ("Joao Souza", "5511900000002", ["vip", "lead"], False),
        ("Ana Lima", "5511900000003", ["lead"], True),      # pediu para sair
        ("Pedro Reis", "5511900000004", [], False),
    ]):
        await DB.contacts.insert_one({
            "id": f"c{i+1}", "tenant_id": TENANT, "nome": nome,
            "numero_whatsapp": num, "tags": tags, "opt_out": opt,
            "created_at": "2026-08-01T00:00:00+00:00",
        })


async def nova_campanha(publico, **kw):
    doc = {
        "id": "camp-1", "tenant_id": TENANT, "nome": "Promo Agosto", "canal": "wuzapi",
        "whatsapp_connection_id": CONN,
        "conteudo": {"tipo": "text", "texto": "Oi {primeiro_nome}, temos novidade!", "media_id": None},
        "publico": publico,
        "cadencia": {"por_minuto": 60},
        "agendada_para": None, "resposta_modo": "aguardando", "bot_id": None,
        "departamento_id": "dep-1", "status": "enviando", "motivo_pausa": None,
        "totais": {"total": 0, "enviados": 0, "falhas": 0, "ignorados": 0},
        "created_at": "2026-08-24T00:00:00+00:00", "updated_at": "2026-08-24T00:00:00+00:00",
    }
    doc.update(kw)
    await DB.campaigns.insert_one(doc)
    return doc


async def etapa_publico_e_disparo():
    print("\n[1] Publico respeita opt-out e etiqueta")
    await semear()
    camp = await nova_campanha({"tipo": "tags", "tags": ["lead"], "contact_ids": []})

    total = await campaigns.audience_count(DB, TENANT, camp["publico"])
    check("etiqueta 'lead' tem 2 contatos, mas 1 pediu para sair -> 1", total == 1, total)

    camp["publico"] = {"tipo": "todos", "tags": [], "contact_ids": []}
    await DB.campaigns.update_one({"id": "camp-1"}, {"$set": {"publico": camp["publico"]}})
    criados = await campaigns.materialize_recipients(DB, camp)
    check("publico 'todos' materializa 3 de 4 (Ana fica fora)", criados == 3, criados)

    de_novo = await campaigns.materialize_recipients(DB, camp)
    check("materializar de novo nao duplica", de_novo == 0, de_novo)

    print("\n[2] Runner dispara a campanha inteira")
    ENVIADOS.clear()
    campaign_runner.JITTER = (0, 0)          # sem espera no teste
    await campaign_runner._run_campaign("camp-1")

    check("3 mensagens enviadas", len(ENVIADOS) == 3, len(ENVIADOS))
    check("interpolou o primeiro nome",
          any("Oi Maria, temos novidade!" == e[3] for e in ENVIADOS),
          [e[3] for e in ENVIADOS])
    check("usou o token da conexao", all(e[1] == "tok-abc" for e in ENVIADOS))
    check("nao mandou para quem pediu para sair",
          not any(e[2] == "5511900000003" for e in ENVIADOS))

    final = await DB.campaigns.find_one({"id": "camp-1"})
    check("campanha concluida", final["status"] == "concluida", final["status"])
    check("totais fecham", final["totais"]["enviados"] == 3, final["totais"])

    sessoes = await DB.conversation_sessions.find({}).to_list(None)
    check("uma conversa criada por destinatario", len(sessoes) == 3, len(sessoes))
    check("conversa carrega a campanha", all(s["campanha_id"] == "camp-1" for s in sessoes))
    check("conversa nasce em 'bot', nao na fila humana",
          all(s["status_atendimento"] == "bot" for s in sessoes))
    check("conversa marcada para dar partida na primeira resposta",
          all(s["aguardando_primeira_resposta"] for s in sessoes))
    check("departamento da campanha propagado",
          all(s["departamento_id"] == "dep-1" for s in sessoes))

    msgs = await DB.messages_log.find({}).to_list(None)
    check("mensagem gravada no historico de cada conversa", len(msgs) == 3, len(msgs))
    check("mensagem marcada com a campanha",
          all(m["meta"]["campanha_id"] == "camp-1" for m in msgs))
    sess = sessoes[0]
    check("previa da conversa preenchida (last_message)", bool(sess.get("last_message")), sess.get("last_message"))


async def etapa_resposta_vai_para_fila():
    print("\n[3] Resposta do contato entra na fila e conta como resposta")
    alvo = await DB.campaign_recipients.find_one({"numero_whatsapp": "5511900000001"})
    check("destinatario comeca sem resposta", alvo["respondeu"] is False)

    await flow_runtime.handle_incoming_message(
        TENANT, "5511900000001", "quanto custa?", "msg-1", connection_id=CONN,
        push_name="Maria Silva")

    alvo = await DB.campaign_recipients.find_one({"numero_whatsapp": "5511900000001"})
    check("resposta marcada no destinatario", alvo["respondeu"] is True)
    check("horario da resposta gravado", bool(alvo["respondido_em"]))

    s = await DB.conversation_sessions.find_one({"contact_id": "c1"})
    check("conversa foi para a fila humana", s["status_atendimento"] == "aguardando", s["status_atendimento"])
    check("marca de primeira resposta consumida", s["aguardando_primeira_resposta"] is False)
    check("nao ficou com unread zerado", s.get("unread_count", 0) >= 1, s.get("unread_count"))

    sistema = [m for m in await DB.messages_log.find({"session_id": s["id"]}).to_list(None)
               if m["direction"] == "sistema"]
    check("aviso de sistema fala de campanha, nao de 'bot indisponivel'",
          sistema and "campanha" in sistema[0]["content"].lower(),
          sistema[0]["content"] if sistema else None)


async def etapa_opt_out_por_mensagem():
    print("\n[4] Contato responde SAIR e sai da base")
    antes = await DB.contacts.find_one({"id": "c2"})
    check("Joao recebia campanha", not antes.get("opt_out"))

    await flow_runtime.handle_incoming_message(
        TENANT, "5511900000002", "SAIR", "msg-2", connection_id=CONN, push_name="Joao")

    depois = await DB.contacts.find_one({"id": "c2"})
    check("Joao marcado como opt-out", depois["opt_out"] is True)
    check("data do opt-out gravada", bool(depois["opt_out_em"]))

    total = await campaigns.audience_count(DB, TENANT, {"tipo": "todos"})
    check("publico 'todos' cai de 3 para 2", total == 2, total)

    # frase de atendimento que contem a palavra nao pode descadastrar
    await flow_runtime.handle_incoming_message(
        TENANT, "5511900000004", "quero cancelar meu pedido", "msg-3",
        connection_id=CONN, push_name="Pedro")
    pedro = await DB.contacts.find_one({"id": "c4"})
    check("'quero cancelar meu pedido' NAO descadastra", not pedro.get("opt_out"))


async def etapa_bot_atende_resposta():
    print("\n[5] Campanha com robo: a resposta da partida no fluxo")
    await semear()
    await DB.bots.insert_one({"id": "bot-1", "tenant_id": TENANT, "nome": "Qualificador",
                              "status": "ativo", "main_flow_id": "flow-1"})
    await DB.flows.insert_one({
        "id": "flow-1", "tenant_id": TENANT, "bot_id": "bot-1",
        "published_at": "2026-08-01T00:00:00+00:00",
        "nodes": [
            {"id": "n1", "type": "start", "data": {"trigger": "first_message"}},
            {"id": "n2", "type": "text", "data": {"text": "Legal, {nome_contato}! Qual seu CEP?"}},
        ],
        "edges": [{"source": "n1", "target": "n2", "sourceHandle": "out"}],
    })
    camp = await nova_campanha({"tipo": "selecionados", "tags": [], "contact_ids": ["c1"]},
                               resposta_modo="bot", bot_id="bot-1")
    await campaigns.materialize_recipients(DB, camp)
    ENVIADOS.clear()
    await campaign_runner._run_campaign("camp-1")
    check("disparo saiu", len(ENVIADOS) == 1, len(ENVIADOS))

    s = await DB.conversation_sessions.find_one({"contact_id": "c1"})
    check("conversa ja vinculada ao bot", s["bot_id"] == "bot-1", s["bot_id"])

    ENVIADOS.clear()
    await flow_runtime.handle_incoming_message(
        TENANT, "5511900000001", "tenho interesse", "msg-10", connection_id=CONN)

    check("o bot respondeu (fluxo rodou do inicio)", len(ENVIADOS) == 1, ENVIADOS)
    check("resposta do bot interpolada",
          ENVIADOS and "Maria Silva" in ENVIADOS[0][3], ENVIADOS)
    s = await DB.conversation_sessions.find_one({"contact_id": "c1"})
    check("conversa segue com o bot, nao na fila",
          s["status_atendimento"] == "bot", s["status_atendimento"])
    check("marca de primeira resposta consumida", not s["aguardando_primeira_resposta"])
    check("flow_id vinculado", s["flow_id"] == "flow-1", s["flow_id"])


async def etapa_conexao_caida_pausa():
    print("\n[6] Conexao caida pausa a campanha em vez de queimar o publico")
    await semear()
    camp = await nova_campanha({"tipo": "todos", "tags": [], "contact_ids": []})
    await campaigns.materialize_recipients(DB, camp)
    await DB.whatsapp_connections.update_one({"id": CONN}, {"$set": {"status": "desconectado"}})
    ENVIADOS.clear()
    await campaign_runner._run_campaign("camp-1")

    c = await DB.campaigns.find_one({"id": "camp-1"})
    check("campanha pausada", c["status"] == "pausada", c["status"])
    check("motivo explica o porque", "desconectado" in (c["motivo_pausa"] or ""), c["motivo_pausa"])
    check("nada foi enviado", len(ENVIADOS) == 0, len(ENVIADOS))
    pend = await DB.campaign_recipients.count_documents({"campaign_id": "camp-1", "status": "pendente"})
    check("publico intacto para retomar depois", pend == 3, pend)


async def etapa_claim_nao_duplica():
    print("\n[7] Dois workers nao mandam para o mesmo contato")
    await semear()
    camp = await nova_campanha({"tipo": "todos", "tags": [], "contact_ids": []})
    await campaigns.materialize_recipients(DB, camp)
    tomados = await asyncio.gather(*[campaign_runner._claim(DB, "camp-1") for _ in range(5)])
    ids = [t["id"] for t in tomados if t]
    check("3 destinatarios tomados, 2 vieram vazios", len(ids) == 3, len(ids))
    check("nenhum repetido", len(set(ids)) == len(ids), ids)


async def etapa_metricas():
    print("\n[8] Metricas agrupadas")
    from routes.campaigns import _metricas
    await semear()
    camp = await nova_campanha({"tipo": "todos", "tags": [], "contact_ids": []})
    await campaigns.materialize_recipients(DB, camp)
    campaign_runner.JITTER = (0, 0)
    await campaign_runner._run_campaign("camp-1")
    await DB.campaign_recipients.update_one({"numero_whatsapp": "5511900000001"},
                                            {"$set": {"respondeu": True}})
    m = await _metricas(DB, "camp-1")
    check("3 enviados", m["enviado"] == 3, m)
    check("1 resposta contada", m["respostas"] == 1, m)
    check("nenhuma falha", m["falha"] == 0, m)



# ---------------------------------------------------------------------------
# Entradas do pytest.
#
# Uma função por etapa, na ordem em que foram escritas: as etapas compartilham
# o estado do Mongo falso deste módulo e cada uma continua de onde a anterior
# parou. O pytest.ini usa `--dist loadscope`, que fixa o módulo inteiro num
# worker só — é o que preserva essa ordem sob execução paralela.
# ---------------------------------------------------------------------------

def test_suite():
    _conectar_fake()

    async def _tudo():
        await etapa_publico_e_disparo()
        await etapa_resposta_vai_para_fila()
        await etapa_opt_out_por_mensagem()
        await etapa_bot_atende_resposta()
        await etapa_conexao_caida_pausa()
        await etapa_claim_nao_duplica()
        await etapa_metricas()
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())
