"""Teste do agente de IA atendendo de verdade, por dentro de
`handle_incoming_message` — que e o caminho por onde passa TODA mensagem
recebida do WhatsApp.

E por isso que o teste exercita a funcao inteira em vez de so `ai_agents`: o
risco do modulo nao esta em montar prompt, esta em ter mexido no roteamento de
mensagem. O que precisa ficar provado e que ligar um agente nao rouba conversa
de fluxo que ja existe, e que nenhum caminho de falha engole a mensagem.

O provedor nunca e chamado: `ai_runtime.responder_por_tenant` e substituido.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, r"c:\Projetos DEV\LOGOS - ZappZen\ZappZen-BotsWpp\backend")
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "WUZAPI_GATEWAY_URL": "http://x"}.items():
    os.environ.setdefault(k, v)

from cryptography.fernet import Fernet
os.environ["AI_CREDENTIALS_KEY"] = Fernet.generate_key().decode()

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import ai_agents
import ai_client
import ai_runtime
import flow_runtime
import routes.ai as rai

ENVIADOS: list[tuple] = []


async def fake_send_text(token, numero, texto):
    ENVIADOS.append((numero, texto))
    return {"ok": True}


async def fake_send_media(*a, **kw):
    return {"ok": True}


async def _sem_avatar(*a, **kw):
    return None


class _IAFalsa:
    """Substitui `ai_runtime.responder_por_tenant`. `proxima` define o que o
    modelo devolve; `erro` faz a chamada falhar."""

    def __init__(self):
        self.chamadas = []
        self.proxima = "Claro, posso ajudar com isso."
        self.erro = None

    async def __call__(self, db, tenant_id, instrucoes, historico):
        self.chamadas.append({"tenant_id": tenant_id, "instrucoes": instrucoes,
                              "historico": historico})
        if self.erro:
            raise self.erro
        return ai_client.Resposta(texto=self.proxima, modelo="claude-haiku-4-5",
                                  tokens_entrada=100, tokens_saida=20)


IA = _IAFalsa()

_MODULOS_FAKE = (flow_runtime, rai)


def _conectar_fake():
    db_mod.get_db = lambda: DB
    for _m in _MODULOS_FAKE:
        _m.get_db = lambda: DB
    flow_runtime.wuzapi.send_text = fake_send_text
    flow_runtime.wuzapi.send_media = fake_send_media
    flow_runtime._fetch_avatar_bg = _sem_avatar
    ai_runtime.responder_por_tenant = IA
    ai_agents.ai_runtime.responder_por_tenant = IA


TENANT = "t-1"
CONN_A, CONN_B = "conn-a", "conn-b"
NUM = "5511900000001"
NUM2 = "5511900000002"
ADMIN = {"id": "u-1", "tenant_id": TENANT, "role": "tenant_admin",
         "name": "Ana", "email": "ana@x.com"}

ok = 0
_msg_seq = 0


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


async def receber(texto, numero=NUM, conn=CONN_A, media=None):
    """Uma mensagem chegando do WhatsApp."""
    global _msg_seq
    _msg_seq += 1
    await flow_runtime.handle_incoming_message(
        TENANT, numero, texto, f"msg-{_msg_seq}", connection_id=conn,
        push_name="Maria", media=media)


async def sessao(numero=NUM):
    contato = await DB.contacts.find_one({"tenant_id": TENANT, "numero_whatsapp": numero})
    if not contato:
        return None
    return await DB.conversation_sessions.find_one(
        {"tenant_id": TENANT, "contact_id": contato["id"]})


async def sistemas(session_id):
    docs = await DB.messages_log.find(
        {"session_id": session_id, "direction": "sistema"}).to_list(50)
    return [d["content"] for d in docs]


async def semear(*, agente=None, com_bot=False, bot_trigger="first_message",
                 keyword=None):
    DB._cols.clear()
    ENVIADOS.clear()
    IA.chamadas.clear()
    IA.erro = None
    IA.proxima = "Claro, posso ajudar com isso."
    os.environ.pop("AI_PLATFORM_KEY", None)

    await DB.tenants.insert_one({"id": TENANT})
    await DB.users.insert_one(dict(ADMIN))
    for cid, nome in ((CONN_A, "Vendas"), (CONN_B, "Suporte")):
        await DB.whatsapp_connections.insert_one({
            "id": cid, "tenant_id": TENANT, "nome": nome,
            "status": "conectado", "wuzapi_token": f"tok-{cid}"})

    if com_bot:
        await DB.bots.insert_one({
            "id": "bot-1", "tenant_id": TENANT, "nome": "Robo",
            "connection_id": CONN_A, "trigger": bot_trigger,
            "status": "ativo", "main_flow_id": "flow-1"})
        await DB.flows.insert_one({
            "id": "flow-1", "tenant_id": TENANT, "bot_id": "bot-1",
            "published_at": "2026-08-01T00:00:00+00:00",
            "nodes": [
                {"id": "n1", "type": "start",
                 "data": {"trigger": bot_trigger, "trigger_keyword": keyword or ""}},
                {"id": "n2", "type": "text", "data": {"text": "RESPOSTA DO FLUXO"}},
            ],
            "edges": [{"source": "n1", "target": "n2", "sourceHandle": "out"}],
        })

    if agente is not None:
        await DB.ai_agents.insert_one({
            "id": "ag-1", "tenant_id": TENANT, "nome": "Bia",
            "tipo": "suporte", "modo": ai_agents.MODO_FALLBACK, "ativo": True,
            "tom": ["profissional"], "tamanho": "normais",
            "conexoes": [], "created_at": "2026-08-01T00:00:00+00:00",
            **agente})


# ---------------------------------------------------------------------------

async def etapa_fallback_responde():
    print("\n[fallback: responde onde nao ha bot]")
    await semear(agente={})
    await receber("qual o horario de voces?")

    s = await sessao()
    check("a conversa nasceu", s is not None)
    check("o agente respondeu", ENVIADOS and ENVIADOS[-1][1] == "Claro, posso ajudar com isso.", ENVIADOS)
    check("o provedor foi chamado uma vez", len(IA.chamadas) == 1, len(IA.chamadas))
    check("a conversa segue como bot, nao na fila",
          s["status_atendimento"] == "bot", s["status_atendimento"])
    check("e continua ativa", s["status"] == "ativa", s["status"])
    check("o contador de respostas subiu", s.get("ia_respostas") == 1, s.get("ia_respostas"))
    check("o agente ficou registrado na sessao", s.get("ia_agente_id") == "ag-1", s.get("ia_agente_id"))

    # A mensagem do contato chegou no historico enviado ao modelo.
    hist = IA.chamadas[0]["historico"]
    check("o historico termina na mensagem do contato",
          hist[-1]["role"] == "user" and "horario" in hist[-1]["content"], hist)
    check("o nome do contato entra no historico, nao nas instrucoes",
          "Maria" in hist[0]["content"] and "Maria" not in IA.chamadas[0]["instrucoes"])


async def etapa_continuidade():
    print("\n[a conversa continua com o agente]")
    await receber("e no sabado?")
    s = await sessao()
    check("respondeu de novo", len(IA.chamadas) == 2, len(IA.chamadas))
    check("contador acumulou", s.get("ia_respostas") == 2, s.get("ia_respostas"))
    hist = IA.chamadas[-1]["historico"]
    check("o historico agora tem a volta anterior", len(hist) >= 3, hist)
    check("alterna papeis",
          all(hist[i]["role"] != hist[i + 1]["role"] for i in range(len(hist) - 1)), hist)
    check("as instrucoes nao mudaram entre as chamadas (cache)",
          IA.chamadas[0]["instrucoes"] == IA.chamadas[1]["instrucoes"])


async def etapa_pediu_humano():
    print("\n[contato pede uma pessoa]")
    await semear(agente={})
    await receber("quero falar com um atendente")
    s = await sessao()
    check("nao gastou chamada no provedor", len(IA.chamadas) == 0, IA.chamadas)
    check("nada foi enviado ao contato", not ENVIADOS, ENVIADOS)
    check("foi para a fila", s["status_atendimento"] == "aguardando", s["status_atendimento"])
    check("com aguardando_desde preenchido", bool(s.get("aguardando_desde")))
    check("e o motivo ficou no historico",
          any("pediu atendimento humano" in m for m in await sistemas(s["id"])),
          await sistemas(s["id"]))


async def etapa_sentinela():
    print("\n[o agente decide transferir]")
    await semear(agente={})
    IA.proxima = "[HUMANO]"
    await receber("quero cancelar meu contrato e quero meu dinheiro de volta")
    s = await sessao()
    check("a sentinela nao vaza para o contato", not ENVIADOS, ENVIADOS)
    check("foi para a fila", s["status_atendimento"] == "aguardando", s["status_atendimento"])
    check("motivo registrado",
          any("transferiu para atendimento humano" in m for m in await sistemas(s["id"])))

    # Sentinela com pontuacao em volta tambem conta.
    await semear(agente={})
    IA.proxima = "[HUMANO]."
    await receber("reclamacao")
    check("sentinela com pontuacao tambem transfere", not ENVIADOS, ENVIADOS)


async def etapa_teto_de_respostas():
    print("\n[freio de mao]")
    await semear(agente={"max_respostas": 2})
    await receber("oi")
    await receber("nao entendi")
    check("respondeu duas vezes", len(ENVIADOS) == 2, ENVIADOS)
    await receber("continuo sem entender")
    s = await sessao()
    check("na terceira, transferiu", len(ENVIADOS) == 2, ENVIADOS)
    check("foi para a fila", s["status_atendimento"] == "aguardando", s["status_atendimento"])
    check("dizendo quantas vezes tentou",
          any("respondeu 2 vezes" in m for m in await sistemas(s["id"])),
          await sistemas(s["id"]))


async def etapa_nao_rouba_do_bot():
    print("\n[fallback nao rouba conversa de fluxo publicado]")
    await semear(agente={}, com_bot=True)
    await receber("oi")
    check("quem respondeu foi o fluxo",
          ENVIADOS and ENVIADOS[-1][1] == "RESPOSTA DO FLUXO", ENVIADOS)
    check("o provedor nem foi chamado", len(IA.chamadas) == 0, IA.chamadas)


async def etapa_modo_primeiro():
    print("\n[modo primeiro assume mesmo havendo bot]")
    await semear(agente={"modo": ai_agents.MODO_PRIMEIRO}, com_bot=True)
    await receber("oi")
    check("quem respondeu foi o agente",
          ENVIADOS and ENVIADOS[-1][1] == "Claro, posso ajudar com isso.", ENVIADOS)
    s = await sessao()
    check("a sessao nao ficou presa ao fluxo", s.get("bot_id") is None, s.get("bot_id"))
    check("nem a um no", s.get("node_atual_id") is None, s.get("node_atual_id"))

    # E a mensagem seguinte continua com o agente, nao tenta retomar o fluxo.
    await receber("me fala mais")
    check("a segunda mensagem tambem foi do agente", len(IA.chamadas) == 2, len(IA.chamadas))


async def etapa_palavra_chave_ganha():
    print("\n[palavra-chave tem precedencia sobre o modo primeiro]")
    await semear(agente={"modo": ai_agents.MODO_PRIMEIRO}, com_bot=True,
                 bot_trigger="keyword", keyword="orcamento")
    await receber("quero um orcamento")
    check("quem respondeu foi o fluxo da palavra-chave",
          ENVIADOS and ENVIADOS[-1][1] == "RESPOSTA DO FLUXO", ENVIADOS)
    check("o agente nao foi chamado", len(IA.chamadas) == 0, IA.chamadas)

    # Sem a palavra, o agente assume.
    await semear(agente={"modo": ai_agents.MODO_PRIMEIRO}, com_bot=True,
                 bot_trigger="keyword", keyword="orcamento")
    await receber("bom dia")
    check("sem a palavra-chave, o agente assume", len(IA.chamadas) == 1, IA.chamadas)


async def etapa_desligado_e_inativo():
    print("\n[agente desligado nao atua]")
    await semear(agente={"modo": ai_agents.MODO_DESLIGADO})
    await receber("oi")
    s = await sessao()
    check("modo desligado nao responde", len(IA.chamadas) == 0, IA.chamadas)
    check("cai na fila humana", s["status_atendimento"] == "aguardando")

    await semear(agente={"ativo": False})
    await receber("oi")
    check("agente inativo nao responde", len(IA.chamadas) == 0, IA.chamadas)

    await semear(agente=None)
    await receber("oi")
    check("sem agente nenhum, fila humana", len(IA.chamadas) == 0, IA.chamadas)
    s = await sessao()
    check("com a mensagem de sempre",
          any("Nenhum bot configurado" in m for m in await sistemas(s["id"])),
          await sistemas(s["id"]))


async def etapa_amarracao_por_conexao():
    print("\n[o agente so atende as conexoes dele]")
    await semear(agente={"conexoes": [CONN_A]})
    await receber("oi", conn=CONN_B, numero=NUM2)
    check("nao atende conexao fora da lista", len(IA.chamadas) == 0, IA.chamadas)
    s = await sessao(NUM2)
    check("essa conversa foi para a fila", s["status_atendimento"] == "aguardando")

    await receber("oi", conn=CONN_A, numero=NUM)
    check("atende a conexao amarrada", len(IA.chamadas) == 1, IA.chamadas)

    # Especifico ganha do generico.
    await semear(agente={"conexoes": [CONN_B], "nome": "Generico"})
    await DB.ai_agents.insert_one({
        "id": "ag-2", "tenant_id": TENANT, "nome": "SoDoA", "tipo": "vendas",
        "modo": ai_agents.MODO_FALLBACK, "ativo": True, "tom": [],
        "tamanho": "normais", "conexoes": [CONN_A],
        "created_at": "2026-08-02T00:00:00+00:00"})
    escolhido = await ai_agents.agente_da_conexao(DB, TENANT, CONN_A)
    check("o agente especifico da conexao ganha", escolhido["id"] == "ag-2", escolhido["nome"])


async def etapa_conversa_com_humano():
    print("\n[conversa ja com humano nao e tocada]")
    await semear(agente={"modo": ai_agents.MODO_PRIMEIRO})
    await receber("oi")
    s = await sessao()
    await DB.conversation_sessions.update_one(
        {"id": s["id"]},
        {"$set": {"status": "aguardando_humano", "status_atendimento": "em_atendimento",
                  "atendente_id": "u-1"}})
    antes = len(IA.chamadas)
    await receber("mais uma pergunta")
    check("o agente nao responde por cima do atendente",
          len(IA.chamadas) == antes, IA.chamadas)
    check("e nada foi enviado", len(ENVIADOS) == 1, ENVIADOS)


async def etapa_anexo_sem_legenda():
    print("\n[anexo sem legenda]")
    await semear(agente={})
    await receber("", media={"kind": "image"})
    s = await sessao()
    check("nao tenta responder imagem", len(IA.chamadas) == 0, IA.chamadas)
    check("vai para a fila", s["status_atendimento"] == "aguardando")
    check("dizendo que nao analisa arquivo",
          any("nao analisa" in m or "não analisa" in m for m in await sistemas(s["id"])),
          await sistemas(s["id"]))


async def etapa_falhas_nao_engolem_mensagem():
    print("\n[nenhuma falha engole a mensagem]")
    # Provedor fora do ar.
    await semear(agente={})
    IA.erro = ai_client.IAError("O provedor está fora do ar no momento.")
    await receber("oi")
    s = await sessao()
    check("falha do provedor manda para a fila",
          s["status_atendimento"] == "aguardando", s["status_atendimento"])
    check("com o motivo no historico",
          any("falhou" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))

    # Teto do plano / sem conta conectada.
    await semear(agente={})
    IA.erro = HTTPException(status_code=403, detail="Limite de IA do plano atingido")
    await receber("oi")
    s = await sessao()
    check("teto do plano manda para a fila", s["status_atendimento"] == "aguardando")
    check("dizendo que a IA esta indisponivel",
          any("indisponível" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))

    # Resposta vazia.
    await semear(agente={})
    IA.proxima = "   "
    await receber("oi")
    s = await sessao()
    check("resposta vazia manda para a fila", s["status_atendimento"] == "aguardando")
    check("nada vazio foi enviado ao contato", not ENVIADOS, ENVIADOS)


async def etapa_prompt():
    print("\n[o prompt montado]")
    agente = {
        "nome": "Bia", "tipo": "vendas", "empresa_nome": "Vubis",
        "empresa_segmento": "Tecnologia", "tom": ["profissional", "empatico"],
        "tamanho": "curtas", "nao_fazer": "Não dar desconto\nNão prometer prazo",
        "base_conhecimento": "Horário: 9h às 18h.",
        "escalar_quando": "Pedirem nota fiscal",
    }
    p = ai_agents.montar_instrucoes(agente)
    check("identifica agente e empresa", "Bia" in p and "Vubis" in p)
    check("traz a estrategia do tipo escolhido", "vender" in p.lower(), p[:200])
    check("combina os dois tons", "profissional" in p and "empático" in p.lower())
    check("pede o tamanho escolhido", "15 palavras" in p, p)
    check("carrega as restricoes da empresa", "Não dar desconto" in p and "Não prometer prazo" in p)
    check("carrega a base de conhecimento", "9h às 18h" in p)
    check("carrega a regra extra de transferencia", "Pedirem nota fiscal" in p)
    check("explica a sentinela", ai_agents.SENTINELA in p)
    check("proibe markdown (é WhatsApp)", "markdown" in p.lower())

    # Sem base de conhecimento o prompt tem que dizer isso, senao o modelo
    # inventa horario e preco.
    sem_base = ai_agents.montar_instrucoes({"nome": "X", "tipo": "geral"})
    check("sem base, avisa que nao sabe nada da empresa",
          "não recebeu base de conhecimento" in sem_base, sem_base[-400:])

    # Personalizado sem objetivo e recusado na rota.
    st, det = await erro(rai.criar_agente(
        rai.AgenteIn(nome="X", tipo="personalizado"), ADMIN))
    check("personalizado exige objetivo", st == 400, (st, det))

    st, det = await erro(rai.criar_agente(rai.AgenteIn(nome="X", tom=["inexistente"]), ADMIN))
    check("tom fora do catalogo e recusado", st == 400, (st, det))
    st, det = await erro(rai.criar_agente(rai.AgenteIn(nome="X", modo="turbo"), ADMIN))
    check("modo fora do catalogo e recusado", st == 400, (st, det))
    st, det = await erro(rai.criar_agente(rai.AgenteIn(nome="X", max_respostas=999), ADMIN))
    check("teto absurdo de respostas e recusado", st == 400, (st, det))


async def etapa_historico():
    print("\n[janela de historico]")
    await semear(agente={})
    s_id = "sess-hist"
    await DB.conversation_sessions.insert_one({"id": s_id, "tenant_id": TENANT})
    # Comeca com uma resposta nossa, para provar que a janela e reajustada.
    await DB.messages_log.insert_one({
        "id": "m0", "session_id": s_id, "tenant_id": TENANT, "direction": "enviada",
        "content": "sobra do turno anterior", "timestamp": "2026-08-01T10:00:00+00:00"})
    for i in range(3):
        await DB.messages_log.insert_one({
            "id": f"mu{i}", "session_id": s_id, "tenant_id": TENANT, "direction": "recebida",
            "content": f"pergunta {i}", "timestamp": f"2026-08-01T10:0{i+1}:00+00:00"})
    await DB.messages_log.insert_one({
        "id": "msys", "session_id": s_id, "tenant_id": TENANT, "direction": "sistema",
        "content": "isto nao pode entrar", "timestamp": "2026-08-01T10:05:00+00:00"})

    h = await ai_agents.montar_historico(DB, s_id, TENANT)
    check("comeca sempre no contato", h[0]["role"] == "user", h)
    check("mensagem de sistema fica de fora",
          all("isto nao pode entrar" not in t["content"] for t in h), h)
    check("turnos seguidos do contato viram um so", len(h) == 1, h)
    check("preservando o conteudo de todos",
          all(f"pergunta {i}" in h[0]["content"] for i in range(3)), h[0])


# ---------------------------------------------------------------------------

def test_suite():
    _conectar_fake()

    async def _tudo():
        await etapa_fallback_responde()
        await etapa_continuidade()
        await etapa_pediu_humano()
        await etapa_sentinela()
        await etapa_teto_de_respostas()
        await etapa_nao_rouba_do_bot()
        await etapa_modo_primeiro()
        await etapa_palavra_chave_ganha()
        await etapa_desligado_e_inativo()
        await etapa_amarracao_por_conexao()
        await etapa_conversa_com_humano()
        await etapa_anexo_sem_legenda()
        await etapa_falhas_nao_engolem_mensagem()
        await etapa_prompt()
        await etapa_historico()
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())
