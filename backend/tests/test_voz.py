"""Teste do atendimento telefônico: ligação → tecla 1 → WhatsApp.

O que precisa ficar provado é o que falha em silêncio, ou falha caro:

  - **A assinatura do Twilio.** O webhook manda WhatsApp para o número que veio
    no POST. Sem a assinatura conferida (e conferida com o token da empresa
    certa), qualquer pessoa faria o sistema escrever, em nome de um cliente,
    para quem ela quisesse.

  - **O roteamento pelo número chamado.** Errar isso entrega a ligação de uma
    empresa na conta de WhatsApp de outra.

  - **Uma mensagem por pessoa.** Retry do Twilio e quem liga três vezes
    seguidas não podem virar três mensagens pagas na mesma conversa.

  - **Texto livre ou modelo**, pela janela de 24h, com a mesma regra do
    lembrete da agenda.

  - **A resposta do contato cai em algum lugar** e é contada. Sem isso a
    ligação vira conversa muda, e o resumo da tela mente.

Nada sai para a rede: o envio de WhatsApp e a API do Twilio são dublados.
"""
import asyncio
import inspect
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste",
             "CREDENTIALS_KEY": "VlKvCmSGH9QsR1bwg10fq1e4oiOZ_0MP3B-YxhSL1oo="}.items():
    os.environ.setdefault(k, v)
os.environ["PUBLIC_BASE_URL"] = "https://zz.exemplo.com"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="zz-voz-")

from fastapi import HTTPException

from fakedb import FakeDB

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import auth
import contatos
import cripto
import flow_runtime
import ligacoes
import media_retention
import media_store
import routes.voz as rv
import twilio_voz

BASE = "https://zz.exemplo.com"
TENANT = "t-refri"
OUTRO = "t-outro"
SID = "AC" + "a" * 32
SID_OUTRO = "AC" + "b" * 32
TOKEN = "token-twilio-refri"
TOKEN_OUTRO = "token-twilio-outro"
NUMERO = "+558533334444"
NUMERO_OUTRO = "+551133334444"
ADMIN = {"id": "u-admin", "tenant_id": TENANT, "role": "tenant_admin",
         "name": "Dono", "email": "d@x.com"}

ENVIOS: list[dict] = []
ok = 0


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        raise AssertionError(nome)


async def fake_send_text(cred, numero, texto, *a, **kw):
    ENVIOS.append({"tipo": "texto", "numero": numero, "texto": texto})
    return f"wamid.T{len(ENVIOS)}"


async def fake_send_template(cred, numero, nome, idioma, componentes, *a, **kw):
    ENVIOS.append({"tipo": "modelo", "numero": numero, "nome": nome,
                   "componentes": componentes})
    return f"wamid.M{len(ENVIOS)}"


def _conectar_fake():
    """(Re)aponta `get_db` e o envio para este arquivo, a cada etapa: o pytest
    importa todas as suítes no mesmo processo e esses são atributos de módulo
    compartilhados."""
    db_mod.get_db = lambda: DB
    rv.get_db = lambda: DB
    flow_runtime.get_db = lambda: DB
    flow_runtime.whatsapp.send_text = fake_send_text
    flow_runtime.whatsapp.send_template = fake_send_template


# ---------------------------------------------------------------------------
# Dublês de Request do Twilio
# ---------------------------------------------------------------------------

class _Form:
    def __init__(self, itens):
        self._itens = itens

    def multi_items(self):
        return list(self._itens)


class _URL:
    def __init__(self, path, query):
        self.path, self.query = path, query


class _Req:
    """Um POST do Twilio: formulário, URL e assinatura.

    `token` assina com o Auth Token informado; `assinar=False` manda sem
    cabeçalho. A URL assinada é a pública, como o Twilio a enxerga.
    """

    def __init__(self, caminho, campos, token=TOKEN, assinar=True, query=""):
        self._itens = list(campos.items())
        self.url = _URL(caminho, query)
        self.query_params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        url = f"{BASE}{caminho}" + (f"?{query}" if query else "")
        self.headers = ({"x-twilio-signature": twilio_voz.assinatura(token, url, self._itens)}
                        if assinar else {})

    async def form(self):
        return _Form(self._itens)


class _BG:
    def __init__(self):
        self.tarefas = []

    def add_task(self, fn, *a, **kw):
        self.tarefas.append((fn, a, kw))

    async def rodar(self):
        for fn, a, kw in self.tarefas:
            await fn(*a, **kw)
        self.tarefas = []


def _ligacao(call_sid, de, para=NUMERO, sid=SID):
    return {"CallSid": call_sid, "From": de, "To": para, "AccountSid": sid,
            "CallStatus": "ringing", "Direction": "inbound"}


async def _erro(coro):
    try:
        await coro
    except HTTPException as e:
        return e.status_code, e.detail
    return None, None


async def semear():
    DB.__init__()
    ENVIOS.clear()
    await DB.tenants.insert_one({"id": TENANT, "name": "Refrigeração Polar"})
    await DB.tenants.insert_one({"id": OUTRO, "name": "Outra"})
    await DB.whatsapp_connections.insert_one({
        "id": "conn-1", "tenant_id": TENANT, "phone_number_id": "pn-1",
        "waba_id": "waba-1", "status": "conectado", "departamento_padrao_id": None})
    for tenant, sid, token, numero in ((TENANT, SID, TOKEN, NUMERO),
                                       (OUTRO, SID_OUTRO, TOKEN_OUTRO, NUMERO_OUTRO)):
        await DB.voz_config.insert_one({
            "id": f"cfg-{tenant}", "tenant_id": tenant, "ativo": True,
            "numero": numero, "account_sid": sid, "auth_token": cripto.cifrar(token),
            "numero_configurado": True, "whatsapp_connection_id": None,
            "template": {"nome": "retorno_ligacao", "idioma": "pt_BR",
                         "variaveis": ["{empresa}"]},
            "mensagem": "", "resposta_modo": "agente", "bot_id": None,
            "audio_token": f"tok-{tenant}-" + "x" * 20,
            "audio_pergunta_id": None, "audio_confirmacao_id": None})


def _xml(resp) -> str:
    return resp.body.decode("utf-8")


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------

async def etapa_assinatura():
    print("\n[assinatura do Twilio]")
    # O exemplo da documentação do Twilio, com o resultado que ela publica. Se
    # o algoritmo divergir (ordem dos parâmetros, URL com query), este é o
    # primeiro número a mudar.
    params = [("CallSid", "CA1234567890ABCDE"), ("Caller", "+12349013030"),
              ("Digits", "1234"), ("From", "+12349013030"), ("To", "+18005551212")]
    sig = twilio_voz.assinatura("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params)
    check("bate com o exemplo publicado pelo Twilio",
          sig == "0/KCTR6DLpKmkAf8muzZqo1nDgQ=", sig)
    check("assinatura alterada é recusada",
          not twilio_voz.assinatura_valida("12345", "https://mycompany.com/myapp.php?foo=1&bar=2",
                                           params, sig[:-2] + "x="))
    check("sem assinatura é recusada",
          not twilio_voz.assinatura_valida("12345", "https://x", params, None))


async def etapa_roteamento():
    print("\n[roteamento pelo número chamado]")
    _conectar_fake()
    await semear()

    resp = await rv.receber_ligacao(_Req("/api/webhooks/voz", _ligacao("CA1", "+5585999990001")))
    xml = _xml(resp)
    check("ligação da empresa certa toca a pergunta e espera a tecla",
          "<Gather" in xml and "numDigits=\"1\"" in xml, xml)
    check("a tecla volta para o endereço público",
          f"{BASE}/api/webhooks/voz/tecla?tentativa=1" in xml, xml)
    lig = await DB.ligacoes.find_one({"call_sid": "CA1"})
    check("a ligação é registrada na empresa dona do número",
          lig and lig["tenant_id"] == TENANT and lig["numero"] == "5585999990001", lig)

    # Assinada com o token de OUTRA empresa: é o ataque de quem tem uma conta
    # Twilio própria e aponta para o nosso webhook com o número de um cliente.
    st, _ = await _erro(rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CA2", "+5585999990002"), token=TOKEN_OUTRO)))
    check("token de outra empresa é recusado com 403", st == 403, st)
    st, _ = await _erro(rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CA3", "+5585999990003"), assinar=False)))
    check("sem assinatura é recusado com 403", st == 403, st)
    st, _ = await _erro(rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CA4", "+5585999990004", sid=SID_OUTRO))))
    check("AccountSid que não é o da empresa é recusado", st == 403, st)
    check("nada disso registrou ligação",
          await DB.ligacoes.count_documents({"call_sid": {"$in": ["CA2", "CA3", "CA4"]}}) == 0)

    resp = await rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CA5", "+5585999990005", para="+5599000000000")))
    check("número que não é de ninguém desliga sem registrar",
          "<Hangup/>" in _xml(resp) and "<Gather" not in _xml(resp)
          and not await DB.ligacoes.find_one({"call_sid": "CA5"}), _xml(resp))

    # A outra empresa recebe as próprias ligações normalmente.
    resp = await rv.receber_ligacao(_Req(
        "/api/webhooks/voz", _ligacao("CA6", "+5511999990006", para=NUMERO_OUTRO, sid=SID_OUTRO),
        token=TOKEN_OUTRO))
    lig = await DB.ligacoes.find_one({"call_sid": "CA6"})
    check("e a outra empresa recebe as dela", lig and lig["tenant_id"] == OUTRO, lig)


async def etapa_tentativas_e_casos():
    print("\n[segunda tentativa, número oculto, desligado]")
    _conectar_fake()
    await semear()

    xml = _xml(await rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CB1", "+5585999990001"))))
    check("sem tecla, pergunta de novo uma vez",
          f"{BASE}/api/webhooks/voz?tentativa=2" in xml, xml)
    xml = _xml(await rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CB1", "+5585999990001"), query="tentativa=2")))
    check("na segunda não redireciona mais, desliga", "<Redirect" not in xml
          and "<Hangup/>" in xml, xml)
    check("e a mesma ligação não é registrada duas vezes",
          await DB.ligacoes.count_documents({"call_sid": "CB1"}) == 1)

    xml = _xml(await rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CB2", "anonymous"))))
    check("número oculto ouve onde achar a empresa, sem tecla",
          "<Gather" not in xml and "WhatsApp" in xml, xml)
    lig = await DB.ligacoes.find_one({"call_sid": "CB2"})
    check("e fica registrado como oculto, sem número", lig["oculto"] and lig["numero"] is None, lig)

    await DB.voz_config.update_one({"tenant_id": TENANT}, {"$set": {"ativo": False}})
    xml = _xml(await rv.receber_ligacao(
        _Req("/api/webhooks/voz", _ligacao("CB3", "+5585999990003"))))
    check("desligado na tela: diz onde achar a empresa, sem tecla e sem registro",
          "<Gather" not in xml and not await DB.ligacoes.find_one({"call_sid": "CB3"}), xml)

    await DB.voz_config.update_one({"tenant_id": TENANT}, {"$set": {"ativo": True}})
    await rv.receber_ligacao(_Req("/api/webhooks/voz", _ligacao("CB4", "+5585999990004")))
    bg = _BG()
    xml = _xml(await rv.receber_tecla(
        _Req("/api/webhooks/voz/tecla", {**_ligacao("CB4", "+5585999990004"), "Digits": "7"},
             query="tentativa=1"), bg))
    check("tecla errada ganha uma segunda chance", "<Gather" in xml and not bg.tarefas, xml)


async def etapa_tecla_1_modelo():
    print("\n[tecla 1, janela fechada: sai o modelo]")
    _conectar_fake()
    await semear()

    req = _ligacao("CC1", "+5585999998888")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    xml = _xml(await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg))
    check("a pessoa ouve a confirmação e a ligação acaba", "<Hangup/>" in xml
          and "Gather" not in xml, xml)
    check("o envio fica para depois da resposta ao Twilio", len(bg.tarefas) == 1)
    await bg.rodar()

    check("saiu um modelo, porque ninguém falou com a empresa hoje",
          len(ENVIOS) == 1 and ENVIOS[0]["tipo"] == "modelo"
          and ENVIOS[0]["nome"] == "retorno_ligacao", ENVIOS)
    check("para o número de quem ligou, sem dígito inventado",
          ENVIOS[0]["numero"] == "5585999998888", ENVIOS)
    check("com a variável preenchida com o nome da empresa",
          ENVIOS[0]["componentes"][0]["parameters"][0]["text"] == "Refrigeração Polar", ENVIOS)

    lig = await DB.ligacoes.find_one({"call_sid": "CC1"})
    check("a ligação termina como enviada", lig["status"] == "enviada"
          and lig["mensagem_tipo"] == "modelo", lig)
    contato = await DB.contacts.find_one({"id": lig["contact_id"]})
    check("a ficha nasce com origem ligação", contato and contato["origem"] == "ligação", contato)
    sessao = await DB.conversation_sessions.find_one({"id": lig["session_id"]})
    check("a conversa é aberta por nós, marcada como de ligação",
          sessao["origem"] == "ligacao" and sessao["ligacao_id"] == lig["id"], sessao)
    check("no modo agente, sem a marca de primeira resposta (senão o agente não atende)",
          sessao["aguardando_primeira_resposta"] is False, sessao)
    msgs = await DB.messages_log.find({"session_id": sessao["id"]}).to_list(10)
    check("e o histórico mostra o texto que o contato leu",
          any("Recebemos sua ligação na Refrigeração Polar" in m["content"] for m in msgs),
          [m["content"] for m in msgs])

    # Retry do Twilio: a mesma tecla chega de novo.
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    check("a mesma tecla repetida não manda de novo", len(ENVIOS) == 1, ENVIOS)

    # A pessoa liga de novo logo em seguida.
    req2 = _ligacao("CC2", "+5585999998888")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req2))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req2, "Digits": "1"}), bg)
    await bg.rodar()
    check("ligou de novo em seguida: não recebe outra mensagem", len(ENVIOS) == 1, ENVIOS)
    lig2 = await DB.ligacoes.find_one({"call_sid": "CC2"})
    check("e a segunda ligação fica registrada como repetida", lig2["status"] == "repetida", lig2)

    # Passou da janela de repetição: recebe de novo.
    antiga = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    await DB.ligacoes.update_many({"call_sid": {"$in": ["CC1", "CC2"]}},
                                  {"$set": {"created_at": antiga}})
    req3 = _ligacao("CC3", "+5585999998888")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req3))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req3, "Digits": "1"}), bg)
    await bg.rodar()
    check("depois de meia hora, nova ligação recebe nova mensagem", len(ENVIOS) == 2, ENVIOS)
    check("na mesma conversa, sem abrir outra",
          await DB.conversation_sessions.count_documents({"tenant_id": TENANT}) == 1)


async def etapa_janela_aberta_e_sem_modelo():
    print("\n[janela aberta: texto livre; sem modelo: motivo no histórico]")
    _conectar_fake()
    await semear()

    # Contato que já escreveu hoje, gravado sem o nono dígito, como o wa_id
    # da Meta chega.
    await DB.contacts.insert_one({"id": "c-antigo", "tenant_id": TENANT,
                                  "numero_whatsapp": "558599997777", "wa_id": "558599997777",
                                  "nome": "Maria"})
    aberta = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    await DB.conversation_sessions.insert_one({
        "id": "s-aberta", "tenant_id": TENANT, "contact_id": "c-antigo",
        "whatsapp_connection_id": "conn-1", "status": "ativa", "status_atendimento": "bot",
        "janela_expira_em": aberta, "variables": {}, "unread_count": 0})

    req = _ligacao("CD1", "+5585999997777")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    check("quem falou com a empresa hoje recebe texto livre, que não custa modelo",
          len(ENVIOS) == 1 and ENVIOS[0]["tipo"] == "texto", ENVIOS)
    check("e vai para o wa_id que a Meta conhece, não para um número reconstruído",
          ENVIOS[0]["numero"] == "558599997777", ENVIOS)
    check("o contato existente é reaproveitado, nas duas grafias do número",
          await DB.contacts.count_documents({"tenant_id": TENANT}) == 1)
    lig = await DB.ligacoes.find_one({"call_sid": "CD1"})
    check("a conversa existente é reaproveitada", lig["session_id"] == "s-aberta", lig)

    await DB.voz_config.update_one({"tenant_id": TENANT},
                                   {"$set": {"template": {"nome": "", "variaveis": []}}})
    req = _ligacao("CD2", "+5585999996666")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    lig = await DB.ligacoes.find_one({"call_sid": "CD2"})
    check("sem modelo e com a janela fechada, não sai nada", len(ENVIOS) == 1
          and lig["status"] == "sem_modelo", (ENVIOS, lig))
    sistema = await DB.messages_log.find({"session_id": lig["session_id"],
                                          "direction": "sistema"}).to_list(5)
    check("e o motivo fica no histórico da conversa",
          any("modelo aprovado" in m["content"] for m in sistema),
          [m["content"] for m in sistema])

    await DB.whatsapp_connections.delete_many({})
    req = _ligacao("CD3", "+5585999995555")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    lig = await DB.ligacoes.find_one({"call_sid": "CD3"})
    check("sem conexão de WhatsApp, a falha fica gravada com o motivo (e não levanta)",
          lig["status"] == "falha" and "conexão" in lig["erro"], lig)


async def etapa_resposta_do_contato():
    print("\n[a resposta do contato]")
    _conectar_fake()
    await semear()

    req = _ligacao("CE1", "+5585988887777")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    lig = await DB.ligacoes.find_one({"call_sid": "CE1"})

    await flow_runtime.handle_incoming_message(
        TENANT, "5585988887777", "minha geladeira parou", "wamid.in-1", connection_id="conn-1")
    lig = await DB.ligacoes.find_one({"call_sid": "CE1"})
    check("a resposta do contato é marcada na ligação", lig["respondeu_em"] is not None, lig)
    sessao = await DB.conversation_sessions.find_one({"id": lig["session_id"]})
    check("sem agente de IA, a conversa vai para a fila em vez de ficar muda",
          sessao["status_atendimento"] == "aguardando", sessao["status_atendimento"])
    check("e a marca sai da conversa depois de usada", not sessao.get("ligacao_id"), sessao)
    sistema = await DB.messages_log.find({"session_id": sessao["id"],
                                          "direction": "sistema"}).to_list(5)
    check("o motivo diz que veio de uma ligação, não 'bot indisponível' nem 'campanha'",
          any("depois de uma ligação" in m["content"] for m in sistema)
          and not any("campanha" in m["content"] or "indisponível" in m["content"]
                      for m in sistema), [m["content"] for m in sistema])

    # Modo fila: a marca de primeira resposta segura a conversa na fila.
    await DB.voz_config.update_one({"tenant_id": TENANT}, {"$set": {"resposta_modo": "fila"}})
    req = _ligacao("CE2", "+5585977776666")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    lig = await DB.ligacoes.find_one({"call_sid": "CE2"})
    sessao = await DB.conversation_sessions.find_one({"id": lig["session_id"]})
    check("no modo fila a conversa nasce esperando a primeira resposta",
          sessao["aguardando_primeira_resposta"] is True and sessao["bot_id"] is None, sessao)

    r = await ligacoes.resumo(DB, TENANT, None, None)
    check("o resumo conta pediram, enviadas e responderam",
          r["recebidas"] == 2 and r["pediram"] == 2 and r["enviadas"] == 2
          and r["responderam"] == 1, r)

    await DB.appointments.insert_one({
        "id": "ag-1", "tenant_id": TENANT, "contact_id": lig["contact_id"],
        "created_at": datetime.now(timezone.utc).isoformat()})
    r = await ligacoes.resumo(DB, TENANT, None, None)
    check("agendamento feito depois da ligação conta como agendou", r["agendaram"] == 1, r)


async def etapa_credenciais():
    print("\n[conectar a conta Twilio]")
    _conectar_fake()
    await semear()
    await DB.voz_config.delete_many({"tenant_id": TENANT})

    chamadas = []

    async def fake_request(metodo, caminho, sid, token, data=None, params=None):
        chamadas.append((metodo, caminho, token, data, params))
        if token != TOKEN:
            raise twilio_voz.TwilioError("Account SID ou Auth Token incorretos")
        if caminho.endswith("IncomingPhoneNumbers.json"):
            achou = params.get("PhoneNumber") == NUMERO
            return {"incoming_phone_numbers": [{"sid": "PN1", "phone_number": NUMERO}]
                    if achou else []}
        return {"status": "active"}

    original = twilio_voz._request
    twilio_voz._request = fake_request
    try:
        cfg = await rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid=SID, auth_token=TOKEN, numero="+55 (85) 3333-4444"),
            user=ADMIN)
        check("conta validada e número gravado em E.164",
              cfg["numero"] == NUMERO and cfg["numero_configurado"], cfg)
        check("o Auth Token não volta para a tela", "auth_token" not in cfg, list(cfg))
        apontar = [c for c in chamadas if c[0] == "POST"]
        check("o número é apontado para o webhook, sem o cliente colar URL",
              apontar and apontar[0][3]["VoiceUrl"] == f"{BASE}/api/webhooks/voz", apontar)
        guardado = await DB.voz_config.find_one({"tenant_id": TENANT})
        check("e fica cifrado no banco", guardado["auth_token"]["cifrada"] != TOKEN
              and cripto.decifrar(guardado["auth_token"]) == TOKEN)

        st, det = await _erro(rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid=SID, auth_token="errado", numero=NUMERO), user=ADMIN))
        check("token errado é recusado antes de gravar", st == 400 and "incorretos" in det, det)
        st, det = await _erro(rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid=SID, auth_token=TOKEN, numero="+5585900000000"),
            user=ADMIN))
        check("número que não está na conta é recusado dizendo isso",
              st == 400 and "não foi encontrado" in det, det)
        st, _ = await _erro(rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid="xyz", auth_token=TOKEN, numero=NUMERO), user=ADMIN))
        check("Account SID com formato errado nem sai para a rede", st == 400)
        st, _ = await _erro(rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid=SID, auth_token=TOKEN, numero=NUMERO_OUTRO),
            user=ADMIN))
        check("número de outra empresa é recusado com 409", st == 409, st)

        cfg = await rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid=SID, numero=NUMERO), user=ADMIN)
        check("salvar de novo sem o token reaproveita o guardado", cfg["numero_configurado"])
        st, _ = await _erro(rv.salvar_credenciais(
            rv.CredenciaisIn(account_sid="AC" + "c" * 32, numero=NUMERO), user=ADMIN))
        check("mas trocar de conta exige o token da conta nova", st == 400, st)
    finally:
        twilio_voz._request = original

    await DB.voz_config.update_one({"tenant_id": TENANT}, {"$set": {"numero_configurado": False}})
    st, _ = await _erro(rv.salvar_config(rv.ConfigIn(ativo=True), user=ADMIN))
    check("não liga o atendimento sem o número configurado", st == 400, st)
    st, _ = await _erro(rv.salvar_config(rv.ConfigIn(resposta_modo="bot"), user=ADMIN))
    check("modo robô exige escolher o robô", st == 400, st)


class _Upload:
    def __init__(self, nome, conteudo, tipo=""):
        self.filename, self.content_type = nome, tipo
        self._dados, self._pos = conteudo, 0

    async def read(self, n=-1):
        if n < 0:
            n = len(self._dados)
        bloco = self._dados[self._pos:self._pos + n]
        self._pos += len(bloco)
        return bloco


async def etapa_audio_e_retencao():
    print("\n[áudio da gravação]")
    _conectar_fake()
    await semear()

    st, det = await _erro(rv.enviar_audio("pergunta", _Upload("recado.ogg", b"x" * 10,
                                                              "audio/ogg"), user=ADMIN))
    check("áudio do WhatsApp (OGG) é recusado dizendo o que fazer",
          st == 400 and "MP3" in det, det)

    cfg = await rv.enviar_audio("pergunta", _Upload("recado.mp3", b"ID3" + b"x" * 100), user=ADMIN)
    primeiro = cfg["audio_pergunta"]["id"]
    doc = await DB.media_files.find_one({"id": primeiro})
    check("MP3 aceito e marcado como gravação de voz", doc and doc["uso"] == "voz", doc)

    resp = await rv.servir_audio(f"tok-{TENANT}-" + "x" * 20, "pergunta")
    check("o Twilio busca o áudio pelo token, sem login", resp.status_code == 200)
    st, _ = await _erro(rv.servir_audio("token-que-nao-existe-xxxxxx", "pergunta"))
    check("token errado não chega ao arquivo", st == 404, st)

    config = await DB.voz_config.find_one({"tenant_id": TENANT})
    xml = _xml(rv._pergunta(config, 1))
    check("com áudio, a ligação toca o arquivo em vez da voz sintética",
          "<Play>" in xml and "<Say" not in xml, xml)

    cfg = await rv.enviar_audio("pergunta", _Upload("novo.wav", b"RIFF" + b"y" * 50), user=ADMIN)
    check("trocar o áudio apaga o anterior",
          cfg["audio_pergunta"]["id"] != primeiro
          and not await DB.media_files.find_one({"id": primeiro}))

    # Retenção: o arquivo da gravação é "antigo" mas não pode sair.
    velho = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    await DB.media_files.update_many({}, {"$set": {"created_at": velho}})
    await DB.media_files.insert_one({"id": "m-conversa", "tenant_id": TENANT,
                                     "stored_name": "nao-existe.jpg", "created_at": velho,
                                     "purged_at": None})
    await media_retention._purge_window(DB, [TENANT], 90)
    gravacao = await DB.media_files.find_one({"id": cfg["audio_pergunta"]["id"]})
    conversa = await DB.media_files.find_one({"id": "m-conversa"})
    check("a retenção não apaga a gravação da ligação", not gravacao.get("purged_at"), gravacao)
    check("mas continua apagando mídia de conversa", conversa.get("purged_at"), conversa)

    cfg = await rv.remover_audio("pergunta", user=ADMIN)
    config = await DB.voz_config.find_one({"tenant_id": TENANT})
    check("sem áudio, volta para a voz sintética",
          cfg["audio_pergunta"] is None and "<Say" in _xml(rv._pergunta(config, 1)))


async def etapa_lgpd():
    print("\n[anonimizar, apagar e mesclar levam as ligações junto]")
    _conectar_fake()
    await semear()

    req = _ligacao("CF1", "+5585966665555")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    # Ligou de novo e desligou sem apertar nada: ficou só com o número.
    await rv.receber_ligacao(_Req("/api/webhooks/voz", _ligacao("CF2", "+5585966665555")))
    lig = await DB.ligacoes.find_one({"call_sid": "CF1"})
    contato = await DB.contacts.find_one({"id": lig["contact_id"]})

    await contatos.anonimizar(DB, TENANT, contato)
    restantes = await DB.ligacoes.find({"call_sid": {"$in": ["CF1", "CF2"]}}).to_list(5)
    check("anonimizar tira o número de todas as ligações da pessoa",
          len(restantes) == 2 and all(l["numero"] is None for l in restantes),
          [l["numero"] for l in restantes])

    await semear()
    req = _ligacao("CF3", "+5585955554444")
    await rv.receber_ligacao(_Req("/api/webhooks/voz", req))
    bg = _BG()
    await rv.receber_tecla(_Req("/api/webhooks/voz/tecla", {**req, "Digits": "1"}), bg)
    await bg.rodar()
    lig = await DB.ligacoes.find_one({"call_sid": "CF3"})
    contato = await DB.contacts.find_one({"id": lig["contact_id"]})
    await DB.contacts.insert_one({"id": "c-principal", "tenant_id": TENANT,
                                  "numero_whatsapp": "5585911112222", "nome": "Principal"})
    principal = await DB.contacts.find_one({"id": "c-principal"})
    await contatos.mesclar(DB, TENANT, principal, contato)
    lig = await DB.ligacoes.find_one({"call_sid": "CF3"})
    check("mesclar leva a ligação para a ficha que fica", lig["contact_id"] == "c-principal", lig)

    await contatos.apagar(DB, TENANT, principal)
    check("apagar o contato apaga as ligações dele",
          not await DB.ligacoes.find_one({"call_sid": "CF3"}))


async def etapa_permissao():
    print("\n[permissão]")

    def deps_de(fn):
        return [p.default.dependency for p in inspect.signature(fn).parameters.values()
                if hasattr(p.default, "dependency")]

    for fn in (rv.ler_config, rv.salvar_config, rv.salvar_credenciais, rv.enviar_audio,
               rv.remover_audio, rv.listar_ligacoes, rv.resumo):
        check(f"{fn.__name__} exige admin da empresa",
              auth.require_tenant_admin in deps_de(fn), deps_de(fn))
    for fn in (rv.receber_ligacao, rv.receber_tecla, rv.servir_audio):
        check(f"{fn.__name__} não tem login (quem chama é o Twilio)", not deps_de(fn))


async def _tudo():
    await etapa_assinatura()
    await etapa_roteamento()
    await etapa_tentativas_e_casos()
    await etapa_tecla_1_modelo()
    await etapa_janela_aberta_e_sem_modelo()
    await etapa_resposta_do_contato()
    await etapa_credenciais()
    await etapa_audio_e_retencao()
    await etapa_lgpd()
    await etapa_permissao()
    print(f"\n{ok} verificações passaram")


def test_suite():
    asyncio.run(_tudo())


if __name__ == "__main__":
    test_suite()
