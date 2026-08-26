"""Teste do nó de Menu nos formatos interativos: botões de resposta rápida e
lista de opções.

O risco deste módulo não está em montar o payload — está em duas coisas que
falham **em silêncio**:

1. O WhatsApp descarta mensagem interativa fora dos tetos dele (mais de 3
   botões, rótulo acima de 20 caracteres) sem devolver erro nenhum. Como o nó
   de Menu deixa a conversa em `awaiting`, uma mensagem descartada trava a
   conversa: o contato não sabe que devia responder e o fluxo espera para
   sempre. O que precisa ficar provado é que nada disso vira mensagem perdida —
   a publicação recusa, e o envio degrada para texto numerado.

2. A resposta do contato chega num nó do payload que não é `conversation`, e o
   rótulo volta cortado em 20 caracteres. Casar por texto falharia justamente
   nos menus mais descritivos, então a correspondência é pelo id — e o id é o
   mesmo `sourceHandle` da saída do nó.

Nada sai para a rede: `send_text`/`send_buttons`/`send_list` são substituídos
por gravadores, e o payload do cliente é conferido espionando `_request`.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "WUZAPI_GATEWAY_URL": "http://x"}.items():
    os.environ.setdefault(k, v)

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import flow_engine
import flow_runtime
import wuzapi_client as wuzapi
import routes.flows as rflows
import routes.webhooks as rwebhooks

# As funções de verdade, guardadas antes de qualquer dublê. `flow_runtime.wuzapi`
# É o próprio módulo `wuzapi_client`, então substituir por lá troca a função
# para todo mundo — inclusive para a etapa que quer justamente exercitar a
# original.
REAL_SEND_BUTTONS = wuzapi.send_buttons
REAL_SEND_LIST = wuzapi.send_list

# Cada chamada de envio fica aqui: (rota, kwargs).
ENVIADOS: list[tuple] = []
# Quando não é None, o próximo envio interativo levanta este erro — é como se
# testa a degradação por falha de rede ou de gateway.
FALHA_INTERATIVA = {"erro": None}


async def fake_send_text(token, numero, texto):
    ENVIADOS.append(("text", {"numero": numero, "texto": texto}))
    return {"ok": True}


async def fake_send_buttons(token, numero, body, itens, titulo="", rodape=""):
    if FALHA_INTERATIVA["erro"]:
        raise FALHA_INTERATIVA["erro"]
    ENVIADOS.append(("buttons", {"body": body, "itens": itens,
                                 "titulo": titulo, "rodape": rodape}))
    return {"ok": True}


async def fake_send_list(token, numero, body, texto_botao, itens,
                         titulo="", rodape="", titulo_secao=""):
    if FALHA_INTERATIVA["erro"]:
        raise FALHA_INTERATIVA["erro"]
    ENVIADOS.append(("list", {"body": body, "texto_botao": texto_botao,
                              "itens": itens, "titulo": titulo,
                              "rodape": rodape, "titulo_secao": titulo_secao}))
    return {"ok": True}


async def _sem_avatar(*a, **kw):
    return None


_MODULOS_FAKE = (flow_runtime, rflows)


def _conectar_fake():
    """Reaplicado no início de cada etapa, não só no import.

    O pytest importa todos os módulos de teste no mesmo processo, e `get_db` e
    os dublês de envio são atributos de módulo compartilhados: sem reaplicar, o
    último arquivo importado fica com o banco de todos e as mensagens
    "enviadas" caem no gravador da outra suíte.
    """
    db_mod.get_db = lambda: DB
    for m in _MODULOS_FAKE:
        m.get_db = lambda: DB
    flow_runtime.wuzapi.send_text = fake_send_text
    flow_runtime.wuzapi.send_buttons = fake_send_buttons
    flow_runtime.wuzapi.send_list = fake_send_list
    flow_runtime._fetch_avatar_bg = _sem_avatar


TENANT = "t-1"
CONN = "conn-a"
NUM = "5511900000001"
ADMIN = {"id": "u-1", "tenant_id": TENANT, "role": "tenant_admin",
         "name": "Ana", "email": "ana@x.com"}
PUBLICADO_EM = "2026-08-01T00:00:00+00:00"

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


async def receber(texto, escolha=None):
    global _msg_seq
    _msg_seq += 1
    await flow_runtime.handle_incoming_message(
        TENANT, NUM, texto, f"msg-{_msg_seq}", connection_id=CONN,
        push_name="Maria", escolha=escolha)


async def sessao():
    contato = await DB.contacts.find_one({"tenant_id": TENANT, "numero_whatsapp": NUM})
    if not contato:
        return None
    return await DB.conversation_sessions.find_one(
        {"tenant_id": TENANT, "contact_id": contato["id"]})


async def menu_no_historico():
    s = await sessao()
    docs = await DB.messages_log.find(
        {"session_id": s["id"], "direction": "enviada"}).to_list(50)
    return [d for d in docs if d["type"] == "menu"][0]


def so(rota):
    return [kw for r, kw in ENVIADOS if r == rota]


async def recebidas():
    s = await sessao()
    return await DB.messages_log.find(
        {"session_id": s["id"], "direction": "recebida"}).to_list(50)


def _nos(dados_menu: dict, opcoes: list[dict]) -> list[dict]:
    """Fluxo de uma pergunta só: Início → Menu, duas saídas de texto e um Fim.

    O nó de Fim existe porque a publicação recusa nó sem saída, e sem ele o
    teste de publicação bateria nessa checagem antes de chegar na do menu — que
    é o que ele quer exercitar. As opções têm id fixo (`op_sim`/`op_nao`)
    porque é justamente o id que precisa reaparecer no botão e voltar na
    resposta do contato.
    """
    return [
        {"id": "n1", "type": "start", "data": {"trigger": "first_message"}},
        {"id": "n2", "type": "menu", "data": {
            "label": "Termo LGPD",
            "text": "Você autoriza a coleta de dados?",
            "options": opcoes,
            "invalid_message": "Não entendi. Escolha uma das opções.",
            **dados_menu,
        }},
        {"id": "n3", "type": "text", "data": {"text": "AUTORIZOU"}},
        {"id": "n4", "type": "text", "data": {"text": "RECUSOU"}},
        {"id": "n5", "type": "end", "data": {}},
    ]


_ARESTAS = [
    {"source": "n1", "target": "n2", "sourceHandle": "out"},
    {"source": "n2", "target": "n3", "sourceHandle": "op_sim"},
    {"source": "n2", "target": "n4", "sourceHandle": "op_nao"},
    {"source": "n3", "target": "n5", "sourceHandle": "out"},
    {"source": "n4", "target": "n5", "sourceHandle": "out"},
]


async def semear(menu: dict, *, opcoes=None):
    DB._cols.clear()
    ENVIADOS.clear()
    FALHA_INTERATIVA["erro"] = None

    opcoes = opcoes if opcoes is not None else [
        {"id": "op_sim", "label": "Sim, estou de acordo"},
        {"id": "op_nao", "label": "Não"},
    ]

    await DB.tenants.insert_one({"id": TENANT})
    await DB.users.insert_one(dict(ADMIN))
    await DB.whatsapp_connections.insert_one({
        "id": CONN, "tenant_id": TENANT, "nome": "Recepção",
        "status": "conectado", "wuzapi_token": "tok-a"})
    await DB.bots.insert_one({
        "id": "bot-1", "tenant_id": TENANT, "nome": "Robo",
        "connection_id": CONN, "trigger": "first_message",
        "status": "ativo", "main_flow_id": "flow-1"})
    await DB.flows.insert_one({
        "id": "flow-1", "tenant_id": TENANT, "bot_id": "bot-1",
        "published_at": PUBLICADO_EM,
        "nodes": _nos(menu, opcoes),
        "edges": list(_ARESTAS),
    })


# ---------------------------------------------------------------------------

async def etapa_texto_continua_igual():
    """Nó de Menu sem `formato` é de um fluxo publicado antes desta versão, e
    tem que continuar saindo como lista numerada pelo /chat/send/text."""
    print("\n[texto numerado: o formato antigo não mudou]")
    _conectar_fake()
    await semear({})  # sem `formato`
    await receber("oi")

    check("saiu por send_text", [r for r, _ in ENVIADOS] == ["text"], ENVIADOS)
    texto = so("text")[0]["texto"]
    check("a pergunta está no corpo", "Você autoriza a coleta de dados?" in texto, texto)
    check("as opções estão numeradas",
          "1. Sim, estou de acordo" in texto and "2. Não" in texto, texto)

    ENVIADOS.clear()
    await receber("2")
    check("o número escolheu a segunda saída",
          [kw["texto"] for kw in so("text")] == ["RECUSOU"], ENVIADOS)


async def etapa_botoes_enviados():
    print("\n[botões: sai pelo endpoint de botões, com os ids das saídas]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES,
                  "titulo": "Termo de uso",
                  "rodape": "Hospital São Domingos"})
    await receber("oi")

    check("saiu por send_buttons", [r for r, _ in ENVIADOS] == ["buttons"], ENVIADOS)
    kw = so("buttons")[0]
    check("o corpo é a pergunta",
          kw["body"] == "Você autoriza a coleta de dados?", kw["body"])
    check("o título foi junto", kw["titulo"] == "Termo de uso", kw["titulo"])
    check("o rodapé foi junto", kw["rodape"] == "Hospital São Domingos", kw["rodape"])
    check("os ids dos botões são os das saídas do nó",
          [i["id"] for i in kw["itens"]] == ["op_sim", "op_nao"], kw["itens"])

    # O histórico guarda a versão em texto, com as opções — é o que o atendente
    # vê ao abrir a conversa na Central.
    doc = await menu_no_historico()
    check("o histórico lista as opções",
          "1. Sim, estou de acordo" in doc["content"], doc["content"])
    check("e o título aparece acima da pergunta",
          doc["content"].startswith("Termo de uso\nVocê autoriza"), doc["content"][:60])
    check("o histórico registra o formato que saiu",
          doc["meta"]["menu"] == {"formato": "botoes"}, doc["meta"])


async def etapa_resposta_por_botao():
    """O caso que motiva casar por id: o rótulo volta cortado, então o texto da
    resposta não é igual ao rótulo configurado."""
    print("\n[resposta de botão: casa pelo id, não pelo texto]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES},
                 opcoes=[{"id": "op_sim", "label": "Sim, autorizo o uso dos meus dados"},
                         {"id": "op_nao", "label": "Não"}])
    await receber("oi")
    ENVIADOS.clear()

    cortado = "Sim, autorizo o uso"  # os 20 primeiros caracteres, como a WuzAPI manda
    await receber(cortado, escolha={"id": "op_sim", "titulo": cortado})

    check("seguiu a saída certa mesmo com o rótulo cortado",
          [kw["texto"] for kw in so("text")] == ["AUTORIZOU"], ENVIADOS)
    s = await sessao()
    check("o menu não está mais esperando resposta", not s.get("awaiting"), s.get("awaiting"))


async def etapa_rotulo_recuperado_do_menu():
    """Observado num toque de verdade (25/08/2026): a resposta do botão chega
    com o id e **sem rótulo nenhum**. O último recurso do webhook é gravar o
    id, e a Central passou a mostrar "t2_dur" — um identificador interno no
    lugar da frase que o contato leu na tela.

    O rótulo vem de `awaiting.rotulos`, guardado quando o menu saiu. É melhor
    que qualquer campo do payload: completo, sem o corte de 20 caracteres.
    """
    print("\n[resposta sem rótulo: recupera do menu que perguntou]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES},
                 opcoes=[{"id": "op_sim", "label": "Sim, autorizo o uso dos meus dados"},
                         {"id": "op_nao", "label": "Não"}])
    await receber("oi")

    s = await sessao()
    check("os rótulos ficaram guardados com o awaiting",
          (s.get("awaiting") or {}).get("rotulos")
          == {"op_sim": "Sim, autorizo o uso dos meus dados", "op_nao": "Não"},
          (s.get("awaiting") or {}).get("rotulos"))

    ENVIADOS.clear()
    # Exatamente o que o webhook monta nesse caso: sem título, e o `text` cai
    # no último recurso, que é o próprio id.
    await receber("op_sim", escolha={"id": "op_sim", "titulo": ""})

    msgs = await recebidas()
    check("o histórico mostra o rótulo, não o id",
          msgs[-1]["content"] == "Sim, autorizo o uso dos meus dados",
          msgs[-1]["content"])
    check("e o rótulo é o completo, não o cortado em 20",
          len(msgs[-1]["content"]) > wuzapi.LIMITE_ROTULO_BOTAO, msgs[-1]["content"])
    check("e a saída certa foi seguida",
          [kw["texto"] for kw in so("text")] == ["AUTORIZOU"], ENVIADOS)


async def etapa_texto_digitado_nao_e_sobrescrito():
    """O rótulo só substitui o texto quando o texto veio da própria escolha.
    Se o contato escreveu algo, é o que ele escreveu que vale."""
    print("\n[texto do contato ganha do rótulo recuperado]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES})
    await receber("oi")
    ENVIADOS.clear()

    await receber("na verdade quero falar com uma pessoa",
                  escolha={"id": "op_sim", "titulo": ""})
    msgs = await recebidas()
    check("o histórico guarda o que o contato escreveu",
          msgs[-1]["content"] == "na verdade quero falar com uma pessoa",
          msgs[-1]["content"])


async def etapa_id_de_menu_antigo_e_invalido():
    """O contato pode tocar num botão de uma mensagem anterior da conversa. O id
    não está entre as opções do menu atual, e isso é resposta inválida — não
    pode virar acerto na primeira saída."""
    print("\n[id fora das opções: cai no caminho de inválido]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES})
    await receber("oi")
    ENVIADOS.clear()

    await receber("Opção de ontem",
                  escolha={"id": "op_de_outro_menu", "titulo": "Opção de ontem"})
    check("respondeu a mensagem de inválido",
          [kw["texto"] for kw in so("text")] == ["Não entendi. Escolha uma das opções."],
          ENVIADOS)
    s = await sessao()
    check("continua esperando a resposta",
          (s.get("awaiting") or {}).get("node_id") == "n2", s.get("awaiting"))


async def etapa_lista_enviada():
    print("\n[lista: seção, linhas e descrição]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_LISTA,
                  "titulo": "Agendamentos",
                  "botao_texto": "Agendamentos",
                  "titulo_secao": "Especialidades",
                  "text": "Qual tipo de agendamento quer fazer?"},
                 opcoes=[{"id": "op_sim", "label": "Oncologia",
                          "descricao": "Consultas e retornos"},
                         {"id": "op_nao", "label": "Medicina nuclear"}])
    await receber("oi")

    check("saiu por send_list", [r for r, _ in ENVIADOS] == ["list"], ENVIADOS)
    kw = so("list")[0]
    check("o botão que abre a lista tem o texto configurado",
          kw["texto_botao"] == "Agendamentos", kw["texto_botao"])
    check("a seção tem título", kw["titulo_secao"] == "Especialidades", kw["titulo_secao"])
    check("as linhas levam id e descrição",
          [(i["id"], i.get("descricao")) for i in kw["itens"]]
          == [("op_sim", "Consultas e retornos"), ("op_nao", "")], kw["itens"])

    doc = await menu_no_historico()
    check("a descrição entra no histórico",
          "Oncologia — Consultas e retornos" in doc["content"], doc["content"])


async def etapa_resposta_por_lista():
    print("\n[resposta de lista: id da linha]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_LISTA, "botao_texto": "Ver opções"})
    await receber("oi")
    ENVIADOS.clear()

    await receber("Não", escolha={"id": "op_nao", "titulo": "Não"})
    check("seguiu a saída da linha escolhida",
          [kw["texto"] for kw in so("text")] == ["RECUSOU"], ENVIADOS)


async def etapa_teto_degrada_em_vez_de_perder():
    """Quatro botões: o WhatsApp descartaria a mensagem sem erro, e o fluxo
    ficaria esperando uma resposta que o contato nunca foi convidado a dar."""
    print("\n[teto estourado: degrada para texto, não perde a pergunta]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES},
                 opcoes=[{"id": f"op_{i}", "label": f"Opção {i}"} for i in range(4)])
    await receber("oi")

    check("não tentou enviar botões", not so("buttons"), ENVIADOS)
    check("a pergunta chegou como texto", len(so("text")) == 1, ENVIADOS)
    texto = so("text")[0]["texto"]
    check("com as quatro opções numeradas",
          all(f"{i+1}. Opção {i}" in texto for i in range(4)), texto)

    meta = (await menu_no_historico())["meta"]["menu"]
    check("o histórico diz que degradou e por quê",
          meta["pedido"] == "botoes" and "no máximo 3" in (meta["degradado"] or ""), meta)

    # E o contato ainda consegue responder digitando.
    ENVIADOS.clear()
    await receber("1")
    s = await sessao()
    check("a escolha por número ainda funciona", not s.get("awaiting"), s.get("awaiting"))


async def etapa_falha_de_envio_degrada():
    """Gateway que não conheça /chat/send/buttons, WuzAPI fora do ar: a
    pergunta ainda tem que chegar."""
    print("\n[falha no envio interativo: cai para texto]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES})
    FALHA_INTERATIVA["erro"] = wuzapi.WuzapiError(
        "WuzAPI POST /chat/send/buttons -> 404: not found")
    await receber("oi")

    check("a pergunta chegou como texto", len(so("text")) == 1, ENVIADOS)
    meta = (await menu_no_historico())["meta"]["menu"]
    check("o formato pedido ficou registrado", meta["pedido"] == "botoes", meta)
    check("e o motivo da degradação também",
          "404" in (meta.get("degradado") or ""), meta)


async def etapa_publicacao_recusa_menu_invalido():
    print("\n[publicação: recusa o que o WhatsApp descartaria]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_BOTOES},
                 opcoes=[{"id": f"op_{i}", "label": f"Opção {i}"} for i in range(4)])

    status, detalhe = await erro(rflows.publish_flow("flow-1", ADMIN))
    check("recusou com 400", status == 400, status)
    check("disse qual menu e quantas opções tem",
          "Termo LGPD" in detalhe and "tem 4" in detalhe, detalhe)

    flow = await DB.flows.find_one({"id": "flow-1"})
    check("não publicou", flow.get("published_at") == PUBLICADO_EM,
          flow.get("published_at"))

    # Corrigido para duas opções, publica.
    await DB.flows.update_one({"id": "flow-1"}, {"$set": {"nodes": _nos(
        {"formato": flow_engine.FORMATO_BOTOES},
        [{"id": "op_sim", "label": "Sim"}, {"id": "op_nao", "label": "Não"}])}})
    await rflows.publish_flow("flow-1", ADMIN)
    flow = await DB.flows.find_one({"id": "flow-1"})
    check("publicou depois de corrigido",
          flow["published_at"] != PUBLICADO_EM, flow["published_at"])


async def etapa_lista_sem_texto_de_botao():
    """Lista sem o rótulo do botão não abre no aparelho do contato."""
    print("\n[lista sem texto de botão: recusada na publicação]")
    _conectar_fake()
    await semear({"formato": flow_engine.FORMATO_LISTA, "botao_texto": ""})
    status, detalhe = await erro(rflows.publish_flow("flow-1", ADMIN))
    check("recusou com 400", status == 400, status)
    check("explicou o que falta", "texto do botão" in detalhe, detalhe)


async def etapa_payload_do_cliente():
    """O payload que iria para a rede.

    É a parte que erra em silêncio: id na grafia errada não dá erro nenhum, só
    faz a escolha do contato voltar sem id e cair como resposta inválida.
    """
    print("\n[cliente: o payload que sai na rede]")
    capturado = {}

    async def espiao(method, path, headers, json=None, body=None):
        capturado["path"] = path
        capturado["json"] = json
        return {"ok": True}

    original = wuzapi._request
    wuzapi._request = espiao
    try:
        await REAL_SEND_BUTTONS(
            "tok", NUM, "Autoriza?",
            [{"id": "op_sim", "label": "Sim, autorizo o uso dos meus dados"},
             {"id": "op_nao", "label": "Não"},
             {"id": "op_3", "label": "Depois"},
             {"id": "op_4", "label": "Excedente"}],
            titulo="Termo", rodape="Rodapé")
        p = capturado["json"]
        check("rota de botões", capturado["path"] == "/chat/send/buttons", capturado["path"])
        check("corta no teto de botões", len(p["Buttons"]) == wuzapi.MAX_BOTOES, p["Buttons"])
        b = p["Buttons"][0]
        check("tipo de resposta rápida", b["type"] == "reply", b)
        # 20 caracteres cairiam no meio de "dos", e o corte não pode deixar
        # espaço sobrando no fim do botão.
        check("o rótulo é cortado no teto de 20, sem espaço sobrando",
              b["title"] == "Sim, autorizo o uso"
              and len(b["title"]) <= wuzapi.LIMITE_ROTULO_BOTAO, repr(b["title"]))
        check("o id vai nas duas grafias que o handler aceita",
              b["id"] == "op_sim" and b["buttonId"] == "op_sim", b)
        check("título e rodapé nos campos da WuzAPI",
              p["Title"] == "Termo" and p["Footer"] == "Rodapé", p)

        capturado.clear()
        await REAL_SEND_LIST(
            "tok", NUM, "Qual agendamento?", "Agendamentos",
            [{"id": f"op_{i}", "label": f"Opção {i}", "descricao": "d"}
             for i in range(12)],
            titulo="Agendamentos", titulo_secao="Especialidades")
        p = capturado["json"]
        check("rota de lista", capturado["path"] == "/chat/send/list", capturado["path"])
        check("corta no teto de itens",
              len(p["Sections"][0]["rows"]) == wuzapi.MAX_ITENS_LISTA,
              len(p["Sections"][0]["rows"]))
        linha = p["Sections"][0]["rows"][0]
        check("o id da linha vai nas duas grafias",
              linha["RowId"] == "op_0" and linha["rowId"] == "op_0", linha)
        check("o corpo vai em Desc", p["Desc"] == "Qual agendamento?", p)
        check("o botão que abre a lista vai em ButtonText",
              p["ButtonText"] == "Agendamentos", p)
        check("a seção leva o título", p["Sections"][0]["title"] == "Especialidades", p)
    finally:
        wuzapi._request = original


def etapa_extrator_do_webhook():
    """As quatro formas em que a escolha chega. Cobrir só uma faria a resposta
    do contato ser descartada como "mensagem sem texto"."""
    print("\n[webhook: extrai a escolha de cada formato de resposta]")
    e = rwebhooks._extract_escolha

    check("botão clássico",
          e({"buttonsResponseMessage": {"selectedButtonId": "op_sim",
                                        "selectedDisplayText": "Sim"}})
          == {"id": "op_sim", "titulo": "Sim"})
    check("lista",
          e({"listResponseMessage": {"title": "Oncologia",
                                     "singleSelectReply": {"selectedRowId": "op_onc"}}})
          == {"id": "op_onc", "titulo": "Oncologia"})
    check("botão de template",
          e({"templateButtonReplyMessage": {"selectedId": "op_nao",
                                            "selectedDisplayText": "Não"}})
          == {"id": "op_nao", "titulo": "Não"})
    # O que a WuzAPI de fato produz hoje: NativeFlowButton, com o id dentro de
    # um JSON **em string**. Sem desempacotar, a escolha vem sem id.
    check("native flow (o formato da WuzAPI)",
          e({"interactiveResponseMessage": {
              "body": {"text": "Sim, estou de acordo"},
              "nativeFlowResponseMessage": {
                  "name": "quick_reply",
                  "paramsJson": '{"id":"op_sim","display_text":"Sim, estou de acordo"}'}}})
          == {"id": "op_sim", "titulo": "Sim, estou de acordo"})
    check("grafia alternativa de paramsJson",
          e({"interactiveResponseMessage": {
              "nativeFlowResponseMessage": {"paramsJSON": '{"id":"op_x"}'}}})
          == {"id": "op_x", "titulo": ""})
    check("paramsJson corrompido não levanta",
          e({"interactiveResponseMessage": {
              "body": {"text": "Sim"},
              "nativeFlowResponseMessage": {"paramsJson": "{nao-e-json"}}})
          == {"id": None, "titulo": "Sim"})
    check("mensagem de texto comum não é escolha",
          e({"conversation": "bom dia"}) is None)
    check("nó vazio não é escolha", e({"buttonsResponseMessage": {}}) is None)


def etapa_resolvedor():
    """A ordem de precedência, isolada. Id primeiro; número e rótulo continuam
    valendo porque o contato pode digitar em vez de tocar."""
    print("\n[resolvedor: id, número, rótulo]")
    r = flow_engine.resolver_escolha_menu
    opts = [{"id": "a", "label": "Sim"}, {"id": "b", "label": "Não"}]

    check("id ganha do texto", r(opts, "Sim", "b") == "b")
    check("número escolhe pela posição", r(opts, "2", None) == "b")
    check("rótulo casa sem caixa e sem espaço", r(opts, "  não  ", None) == "b")
    check("número fora da faixa é inválido", r(opts, "9", None) is None)
    check("zero não vira índice -1", r(opts, "0", None) is None)
    check("texto vazio não casa rótulo vazio",
          r([{"id": "a", "label": ""}], "", None) is None)
    check("id desconhecido cai para o texto", r(opts, "2", "zzz") == "b")
    check("opção sem id usa a posição",
          r([{"label": "Um"}, {"label": "Dois"}], "2", None) == "opt_1")


def etapa_validador():
    print("\n[validador: os tetos e o que eles dizem]")
    v = flow_engine.validar_menu
    check("formato texto nunca reclama",
          v({"formato": "texto", "options": [{"label": "x" * 200}] * 50}) == [])
    check("menu sem formato é tratado como texto", v({"options": []}) == [])
    check("menu interativo sem opção é problema",
          any("sem nenhuma opção" in p for p in v({"formato": "botoes", "options": []})))
    check("três botões passam",
          v({"formato": "botoes", "options": [{"label": "x"}] * 3}) == [])
    check("rótulo de 20 passa e de 21 não",
          v({"formato": "botoes", "options": [{"label": "x" * 20}]}) == []
          and any("passa de 20" in p for p in
                  v({"formato": "botoes", "options": [{"label": "x" * 21}]})))
    check("lista usa o teto de 24 no rótulo",
          v({"formato": "lista", "botao_texto": "Ver",
             "options": [{"label": "x" * 24}]}) == []
          and any("passa de 24" in p for p in
                  v({"formato": "lista", "botao_texto": "Ver",
                     "options": [{"label": "x" * 25}]})))
    check("dez itens passam, onze não",
          v({"formato": "lista", "botao_texto": "Ver",
             "options": [{"label": "x"}] * 10}) == []
          and any("no máximo 10" in p for p in
                  v({"formato": "lista", "botao_texto": "Ver",
                     "options": [{"label": "x"}] * 11})))
    check("formato desconhecido é problema",
          any("desconhecido" in p for p in
              v({"formato": "carrossel", "options": [{"label": "x"}]})))


# ---------------------------------------------------------------------------

async def _assincronas():
    await etapa_payload_do_cliente()
    await etapa_texto_continua_igual()
    await etapa_botoes_enviados()
    await etapa_resposta_por_botao()
    await etapa_rotulo_recuperado_do_menu()
    await etapa_texto_digitado_nao_e_sobrescrito()
    await etapa_id_de_menu_antigo_e_invalido()
    await etapa_lista_enviada()
    await etapa_resposta_por_lista()
    await etapa_teto_degrada_em_vez_de_perder()
    await etapa_falha_de_envio_degrada()
    await etapa_publicacao_recusa_menu_invalido()
    await etapa_lista_sem_texto_de_botao()


def test_suite():
    etapa_resolvedor()
    etapa_validador()
    etapa_extrator_do_webhook()
    asyncio.run(_assincronas())
    print(f"\n{ok} verificações passaram")


if __name__ == "__main__":
    test_suite()
