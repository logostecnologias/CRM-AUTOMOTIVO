"""Teste do formulário de site: o lead da landing page vira contato.

O que precisa ficar provado é o que falha em silêncio, ou falha caro:

  - **O endereço é público e a chave está no código da página.** Quem tem a
    chave não pode sobrescrever a ficha de ninguém, nem mandar de um domínio
    fora da lista, nem despejar envios sem freio. Robô do campo-isca não grava.

  - **Nenhum lead some.** Campo com nome que não é o nosso é reconhecido ou
    guardado; envio sem telefone fica registrado como recusado, com o motivo;
    valor ruim num campo personalizado derruba o campo, não o lead.

  - **Clique duplo não vira dois negócios**, e quem volta com negócio aberto
    não ganha um segundo cartão.

  - **A origem chega à venda**: o resumo diz quanto cada campanha vendeu.

  - **O WhatsApp segue a regra da janela**, e sai uma vez por pessoa.

Nada sai para a rede: o envio de WhatsApp é dublado.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste",
             "CREDENTIALS_KEY": "VlKvCmSGH9QsR1bwg10fq1e4oiOZ_0MP3B-YxhSL1oo=",
             "CORS_ORIGINS": "https://painel.exemplo.com"}.items():
    os.environ.setdefault(k, v)
os.environ["PUBLIC_BASE_URL"] = "https://zz.exemplo.com"

from fastapi import HTTPException

from fakedb import FakeDB

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import contatos
import cripto
import flow_runtime
import formularios
import routes.formularios as rf

TENANT = "t-r3"
OUTRO = "t-outro"
ADMIN = {"id": "u-admin", "tenant_id": TENANT, "role": "tenant_admin",
         "name": "Dona", "email": "d@r3.com"}
VENDEDOR = "u-vendas"

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
    ENVIOS.append({"tipo": "texto", "numero": numero, "texto": texto, "canal": cred.canal})
    return f"wamid.T{len(ENVIOS)}"


async def fake_send_template(cred, numero, nome, idioma, componentes, *a, **kw):
    ENVIOS.append({"tipo": "modelo", "numero": numero, "nome": nome,
                   "componentes": componentes})
    return f"wamid.M{len(ENVIOS)}"


def _conectar_fake():
    """(Re)aponta `get_db` e o envio para este arquivo a cada etapa: o pytest
    importa todas as suítes no mesmo processo."""
    db_mod.get_db = lambda: DB
    rf.get_db = lambda: DB
    flow_runtime.get_db = lambda: DB
    flow_runtime.whatsapp.send_text = fake_send_text
    flow_runtime.whatsapp.send_template = fake_send_template
    formularios._reset_para_testes()


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _Cliente:
    def __init__(self, host):
        self.host = host


class _Req:
    """Um POST de site: corpo cru, cabeçalhos e IP."""

    def __init__(self, corpo, tipo="application/json", origem=None, ip="200.1.1.1",
                 accept="*/*"):
        if isinstance(corpo, dict) and tipo in ("application/json", "text/plain;charset=UTF-8"):
            corpo = json.dumps(corpo).encode()
        elif isinstance(corpo, str):
            corpo = corpo.encode()
        self._corpo = corpo
        self.headers = {"content-type": tipo, "content-length": str(len(corpo)),
                        "accept": accept}
        if origem:
            self.headers["origin"] = origem
        self.client = _Cliente(ip)

    async def stream(self):
        yield self._corpo


class _BG:
    def __init__(self):
        self.tarefas = []

    def add_task(self, fn, *a, **kw):
        self.tarefas.append((fn, a, kw))

    async def rodar(self):
        for fn, a, kw in self.tarefas:
            await fn(*a, **kw)
        self.tarefas = []


async def _erro(coro):
    try:
        await coro
    except HTTPException as e:
        return e.status_code, e.detail
    return None, None


async def _enviar(chave, corpo, **kw):
    bg = _BG()
    resp = await rf.receber(chave, _Req(corpo, **kw), bg)
    await bg.rodar()
    return resp


ETAPAS = [{"id": "e-novo", "nome": "Novo lead", "tipo": "aberta", "ordem": 0, "cor": "#000"},
          {"id": "e-prop", "nome": "Proposta", "tipo": "aberta", "ordem": 1, "cor": "#000"},
          {"id": "e-ganho", "nome": "Ganho", "tipo": "ganho", "ordem": 2, "cor": "#000"}]


async def semear():
    DB.__init__()
    ENVIOS.clear()
    await DB.tenants.insert_one({"id": TENANT, "name": "R3 Imóveis"})
    await DB.tenants.insert_one({"id": OUTRO, "name": "Outra"})
    await DB.users.insert_one({"id": ADMIN["id"], "tenant_id": TENANT, "role": "tenant_admin"})
    await DB.users.insert_one({"id": VENDEDOR, "tenant_id": TENANT, "role": "agent"})
    await DB.users.insert_one({"id": "u-alheio", "tenant_id": OUTRO, "role": "agent"})
    await DB.pipelines.insert_one({"id": "p-1", "tenant_id": TENANT, "nome": "Vendas",
                                   "etapas": ETAPAS})
    await DB.contact_field_defs.insert_one({"id": "cf-renda", "tenant_id": TENANT,
                                            "nome": "Renda", "tipo": "numero"})
    await DB.contact_field_defs.insert_one({"id": "cf-bairro", "tenant_id": TENANT,
                                            "nome": "Bairro de interesse", "tipo": "texto"})


def _config(**extra) -> rf.FormularioIn:
    base = {
        "nome": "LP Lançamento",
        "tags": ["lançamento", "site"],
        "responsavel_id": VENDEDOR,
        "negocio": {"ativo": True, "pipeline_id": "p-1", "valor": 350000,
                    "titulo": "Apto — {nome}"},
        "tarefa": {"ativo": True, "prazo_min": 15},
    }
    base.update(extra)
    return rf.FormularioIn(**base)


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------

async def etapa_leitura():
    print("\n[leitura dos campos do site]")
    defs = [{"id": "cf-renda", "nome": "Renda"}]
    sep = formularios.separar(formularios.limpar({
        "Primeiro nome": "Ana", "Sobrenome": "Souza", "Celular": "(85) 99999-1111",
        "E-mail": "ana@x.com", "renda": "8.500,00", "Mensagem": "Quero 3 quartos",
        "utm_source": "instagram", "UTM_Campaign": "lancamento", "fbclid": "abc",
        "_pagina": "https://r3.com.br/lp", "_hp": "", "interesses": ["piscina", "academia"],
    }), defs)
    check("nome e sobrenome em campos separados viram um nome só",
          sep["contato"].get("nome") == "Ana Souza", sep["contato"])
    check("'Celular' e 'E-mail' são reconhecidos pelos sinônimos",
          sep["contato"].get("numero_whatsapp") == "(85) 99999-1111"
          and sep["contato"].get("email") == "ana@x.com", sep["contato"])
    check("campo com o nome de um campo personalizado vai para ele",
          sep["campos"] == {"cf-renda": "8.500,00"}, sep["campos"])
    check("UTM e clique de anúncio são separados, sem depender da caixa",
          sep["utm"] == {"utm_source": "instagram", "utm_campaign": "lancamento"}
          and sep["clique"] == {"fbclid": "abc"}, (sep["utm"], sep["clique"]))
    check("o resto fica guardado, inclusive checkbox múltiplo",
          sep["extras"] == {"Mensagem": "Quero 3 quartos", "interesses": "piscina, academia"},
          sep["extras"])
    check("a página vem do campo do script", sep["pagina"] == "https://r3.com.br/lp")

    grande = formularios.limpar({f"c{i}": "x" * 5000 for i in range(200)})
    check("envio forjado é aparado: no máximo 60 campos de 2.000 caracteres",
          len(grande) == formularios.MAX_CAMPOS
          and all(len(v) == formularios.MAX_VALOR for v in grande.values()))

    check("domínio: subdomínio passa, parecido não",
          formularios.dominio_permitido(["r3.com.br"], "https://lp.r3.com.br")
          and formularios.dominio_permitido(["r3.com.br"], "https://www.r3.com.br/x")
          and not formularios.dominio_permitido(["r3.com.br"], "https://r3.com.br.golpe.io")
          and not formularios.dominio_permitido(["r3.com.br"], "https://outror3.com.br")
          and not formularios.dominio_permitido(["r3.com.br"], None))
    check("sem domínio configurado, aceita até sem Origin (n8n, servidor)",
          formularios.dominio_permitido([], None))


async def etapa_configuracao():
    print("\n[configuração]")
    _conectar_fake()
    await semear()

    f = await rf.criar(_config(dominios=["https://www.R3.com.br/lp", "r3.com.br"]), ADMIN)
    check("a chave é gerada pelo servidor, com prefixo",
          f["chave"].startswith("zzf_") and len(f["chave"]) > 20, f["chave"])
    check("domínio é normalizado e sem repetição", f["dominios"] == ["r3.com.br"], f["dominios"])

    st, _ = await _erro(rf.criar(_config(), ADMIN))
    check("nome repetido na empresa é recusado com 409", st == 409, st)
    st, _ = await _erro(rf.criar(_config(nome="B", responsavel_id="u-alheio"), ADMIN))
    check("responsável de outra empresa é recusado", st == 400, st)
    st, det = await _erro(rf.criar(_config(nome="C", responsavel_id=None), ADMIN))
    check("tarefa sem responsável é recusada dizendo por quê",
          st == 400 and "responsável" in det, det)
    st, _ = await _erro(rf.criar(_config(nome="D", negocio={"ativo": True, "pipeline_id": "nao"}), ADMIN))
    check("funil inexistente é recusado", st == 400, st)
    st, _ = await _erro(rf.criar(_config(nome="E", redirecionar_para="javascript:alert(1)"), ADMIN))
    check("redirecionamento que não é http(s) é recusado", st == 400, st)

    antiga = f["chave"]
    nova = await rf.trocar_chave(f["id"], ADMIN)
    check("trocar a chave invalida a anterior",
          nova["chave"] != antiga
          and not await DB.formularios.find_one({"chave": antiga})
          and await DB.formularios.find_one({"chave": nova["chave"]}))

    st, _ = await _erro(rf.detalhe(f["id"], {**ADMIN, "tenant_id": OUTRO}))
    check("outra empresa não enxerga o formulário", st == 404, st)


async def etapa_lead_novo():
    print("\n[lead novo vira contato, negócio e tarefa]")
    _conectar_fake()
    await semear()
    f = await rf.criar(_config(), ADMIN)

    resp = await _enviar(f["chave"], {
        "nome": "Bruno Lima", "whatsapp": "85 98888-2222", "email": "bruno@x.com",
        "renda": "12000", "Bairro de interesse": "Aldeota", "mensagem": "Tem 3 quartos?",
        "utm_source": "instagram", "utm_campaign": "lancamento", "gclid": "g-1",
        "_pagina": "https://r3.com.br/lp",
    })
    check("o site recebe ok", resp == {"ok": True}, resp)

    c = await DB.contacts.find_one({"tenant_id": TENANT, "numero_whatsapp": "5585988882222"})
    check("o contato nasce com o número normalizado, nome e e-mail",
          c and c["nome"] == "Bruno Lima" and c["email"] == "bruno@x.com", c)
    check("origem, etiquetas e responsável vêm da configuração",
          c["origem"] == "formulário: LP Lançamento" and c["tags"] == ["lançamento", "site"]
          and c["responsavel_id"] == VENDEDOR, c)
    check("os campos personalizados entram já validados",
          c["campos"] == {"cf-renda": 12000.0, "cf-bairro": "Aldeota"}, c["campos"])

    r = await DB.formulario_respostas.find_one({"tenant_id": TENANT, "contact_id": c["id"]})
    check("a resposta guarda a origem do lead",
          r["utm"] == {"utm_source": "instagram", "utm_campaign": "lancamento"}
          and r["clique"] == {"gclid": "g-1"} and r["pagina"] == "https://r3.com.br/lp"
          and r["contato_novo"] and r["status"] == "recebida", r)
    check("e o envio inteiro, inclusive o que a ficha não tem onde pôr",
          r["dados"].get("mensagem") == "Tem 3 quartos?", r["dados"])

    d = await DB.deals.find_one({"id": r["deal_id"]})
    check("o negócio nasce na primeira etapa, com valor, título e dono",
          d and d["etapa_id"] == "e-novo" and d["status"] == "aberto" and d["valor"] == 350000
          and d["titulo"] == "Apto — Bruno Lima" and d["responsavel_id"] == VENDEDOR, d)
    check("o negócio carrega a origem e o vínculo com a resposta",
          d["origem"] == "Formulário LP Lançamento · instagram / lancamento"
          and d["formulario_resposta_id"] == r["id"], d)
    check("o histórico do negócio registra a criação",
          await DB.deal_events.count_documents({"deal_id": d["id"], "tipo": "criado"}) == 1)

    a = await DB.activities.find_one({"id": r["atividade_id"]})
    vence = datetime.fromisoformat(a["vence_em"])
    check("a tarefa de retorno vai para a agenda do responsável, no prazo",
          a and a["responsavel_id"] == VENDEDOR and a["contact_id"] == c["id"]
          and a["deal_id"] == d["id"] and a["concluida_em"] is None
          and timedelta(minutes=14) < vence - datetime.now(timezone.utc) <= timedelta(minutes=15), a)

    nota = await DB.contact_notes.find_one({"contact_id": c["id"]})
    check("o atendente lê na ficha o que a pessoa escreveu",
          nota and "mensagem: Tem 3 quartos?" in nota["texto"]
          and "source=instagram" in nota["texto"], nota)


async def etapa_existente_e_repeticao():
    print("\n[contato existente, clique duplo, volta]")
    _conectar_fake()
    await semear()
    f = await rf.criar(_config(), ADMIN)
    # Já é cliente, cadastrado sem o nono dígito (como o WhatsApp o entregou).
    await DB.contacts.insert_one({
        "id": "c-velho", "tenant_id": TENANT, "numero_whatsapp": "558577776666",
        "nome": "Carla Mendes", "email": None, "empresa": "Padaria", "origem": "mensagem recebida",
        "responsavel_id": None, "tags": ["cliente"], "campos": {"cf-bairro": "Centro"}})

    await _enviar(f["chave"], {"nome": "Golpista", "telefone": "(85) 97777-6666",
                               "email": "carla@x.com", "empresa": "Outra",
                               "Bairro de interesse": "Meireles"})
    c = await DB.contacts.find_one({"id": "c-velho"})
    check("o número com nono dígito acha a ficha sem ele (não cria outra)",
          await DB.contacts.count_documents({"tenant_id": TENANT}) == 1)
    check("quem envia não sobrescreve nome, empresa nem campo preenchido",
          c["nome"] == "Carla Mendes" and c["empresa"] == "Padaria"
          and c["campos"]["cf-bairro"] == "Centro", c)
    check("mas completa o que estava vazio e soma etiquetas",
          c["email"] == "carla@x.com" and c["responsavel_id"] == VENDEDOR
          and c["tags"] == ["cliente", "lançamento", "site"], c)
    check("a origem de quem já era contato continua a de antes",
          c["origem"] == "mensagem recebida", c["origem"])

    # O botão clicado duas vezes.
    await _enviar(f["chave"], {"nome": "Carla", "telefone": "85977776666"})
    respostas = await DB.formulario_respostas.find(
        {"contact_id": "c-velho"}).sort("created_at", 1).to_list(10)
    check("o segundo envio em seguida é marcado como repetido",
          [r["status"] for r in respostas] == ["recebida", "repetida"], respostas)
    check("e não cria segundo negócio nem segunda tarefa",
          await DB.deals.count_documents({"contact_id": "c-velho"}) == 1
          and await DB.activities.count_documents({"contact_id": "c-velho"}) == 1)

    # Volta dias depois, com o negócio ainda aberto.
    for r in respostas:
        await DB.formulario_respostas.update_one(
            {"id": r["id"]}, {"$set": {"created_at": "2026-01-01T00:00:00+00:00"}})
    await _enviar(f["chave"], {"nome": "Carla", "telefone": "85977776666",
                               "utm_source": "google"})
    check("quem volta com negócio aberto não ganha outro cartão",
          await DB.deals.count_documents({"contact_id": "c-velho"}) == 1)
    deal = await DB.deals.find_one({"contact_id": "c-velho"})
    check("o negócio existente registra que a pessoa voltou",
          await DB.deal_events.count_documents({"deal_id": deal["id"], "tipo": "formulario"}) == 1)
    ultima = await DB.formulario_respostas.find(
        {"contact_id": "c-velho"}).sort("created_at", -1).limit(1).to_list(1)
    check("e a resposta nova aponta para ele",
          ultima[0]["deal_id"] == deal["id"] and ultima[0]["utm"]["utm_source"] == "google")


async def etapa_nenhum_lead_some():
    print("\n[nenhum lead some]")
    _conectar_fake()
    await semear()
    f = await rf.criar(_config(), ADMIN)

    resp = await _enviar(f["chave"], {"nome": "Sem Fone", "email": "a@b.com"})
    check("sem telefone, o site recebe 422 com o motivo",
          resp.status_code == 422 and json.loads(resp.body)["erro"] == "O envio não trouxe telefone",
          getattr(resp, "body", resp))
    resp = await _enviar(f["chave"], {"nome": "Curto", "celular": "9999"})
    check("telefone curto demais é recusado dizendo por quê",
          resp.status_code == 422 and "curto" in json.loads(resp.body)["erro"])
    check("as duas ficam registradas como recusadas, sem contato",
          await DB.formulario_respostas.count_documents({"status": "recusada"}) == 2
          and await DB.contacts.count_documents({}) == 0)

    await _enviar(f["chave"], {"nome": "Davi", "celular": "85966665555",
                               "renda": "muito", "email": "isso-nao-e-email"})
    c = await DB.contacts.find_one({"numero_whatsapp": "5585966665555"})
    r = await DB.formulario_respostas.find_one({"contact_id": c["id"]})
    check("valor ruim em campo personalizado derruba o campo, não o lead",
          c and "cf-renda" not in (c.get("campos") or {}), c)
    check("e-mail torto não entra na ficha", c["email"] is None, c["email"])
    check("os dois avisos ficam na resposta",
          len(r["avisos"]) == 2 and r["dados"]["renda"] == "muito", r["avisos"])

    resp = await _enviar(f["chave"], {"nome": "Robô", "celular": "85955554444", "_hp": "spam"})
    check("robô do campo-isca recebe ok e não grava nada",
          resp == {"ok": True}
          and not await DB.contacts.find_one({"numero_whatsapp": "5585955554444"})
          and await DB.formulario_respostas.count_documents({"nome": "Robô"}) == 0)


async def etapa_portas():
    print("\n[o endereço público]")
    _conectar_fake()
    await semear()
    f = await rf.criar(_config(dominios=["r3.com.br"]), ADMIN)
    corpo = {"nome": "Eva", "celular": "85944443333"}

    st, _ = await _erro(_enviar("zzf_naoexiste", corpo, origem="https://r3.com.br"))
    check("chave desconhecida é 404", st == 404, st)
    st, _ = await _erro(_enviar("qualquer", corpo, origem="https://r3.com.br"))
    check("chave sem o prefixo nem chega ao banco", st == 404, st)
    st, _ = await _erro(_enviar(f["chave"], corpo, origem="https://golpe.io"))
    check("domínio fora da lista é 403", st == 403, st)
    st, _ = await _erro(_enviar(f["chave"], corpo))
    check("sem Origin, com domínio configurado, é 403", st == 403, st)
    check("nada disso gravou resposta", await DB.formulario_respostas.count_documents({}) == 0)

    resp = await _enviar(f["chave"], corpo, tipo="text/plain;charset=UTF-8",
                         origem="https://lp.r3.com.br")
    check("o JSON em text/plain (o do script) é aceito", resp == {"ok": True}, resp)

    await rf.salvar(f["id"], _config(dominios=[], redirecionar_para="https://r3.com.br/obrigado"),
                    ADMIN)
    resp = await _enviar(f["chave"], "nome=Fabio&celular=%2885%29+93333-2222&utm_source=google",
                         tipo="application/x-www-form-urlencoded", accept="text/html")
    check("<form> puro é aceito e redireciona para a página escolhida",
          resp.status_code == 303 and resp.headers["location"] == "https://r3.com.br/obrigado",
          getattr(resp, "status_code", resp))
    check("com os campos lidos do urlencoded",
          await DB.contacts.find_one({"numero_whatsapp": "5585933332222", "nome": "Fabio"}))

    st, _ = await _erro(_enviar(f["chave"], b"x" * (formularios.MAX_BYTES + 1),
                                tipo="text/plain"))
    check("corpo acima do teto é 413", st == 413, st)
    st, _ = await _erro(_enviar(f["chave"], "[1, 2]"))
    check("JSON que não é objeto é 400", st == 400, st)

    await rf.salvar(f["id"], _config(ativo=False), ADMIN)
    st, _ = await _erro(_enviar(f["chave"], corpo))
    check("formulário desativado é 403", st == 403, st)

    await rf.salvar(f["id"], _config(), ADMIN)
    formularios._reset_para_testes()
    for i in range(formularios.MAX_POR_IP):
        await _enviar(f["chave"], {"celular": f"8591111{i:04d}"}, ip="9.9.9.9")
    st, _ = await _erro(_enviar(f["chave"], corpo, ip="9.9.9.9"))
    check(f"o {formularios.MAX_POR_IP + 1}º envio do mesmo IP em 10 min é 429", st == 429, st)
    resp = await _enviar(f["chave"], {"celular": "85922221111"}, ip="9.9.9.10")
    check("outro IP continua passando", resp == {"ok": True}, resp)


async def etapa_cors():
    print("\n[CORS aberto só para /api/f/]")
    _conectar_fake()
    await semear()
    from starlette.testclient import TestClient
    import server
    cliente = TestClient(server.app)

    r = cliente.options("/api/f/zzf_qualquer", headers={
        "Origin": "https://r3.com.br", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    check("o preflight de qualquer site é aceito",
          r.status_code == 204 and r.headers.get("access-control-allow-origin") == "*", r.headers)
    r = cliente.post("/api/f/zzf_naoexiste", content=b"{}",
                     headers={"Origin": "https://painel.exemplo.com"})
    check("até o erro volta legível para o site, e sem credencial",
          r.status_code == 404 and r.headers.get("access-control-allow-origin") == "*"
          and "access-control-allow-credentials" not in r.headers, r.headers)
    r = cliente.options("/api/formularios", headers={
        "Origin": "https://r3.com.br", "Access-Control-Request-Method": "GET"})
    check("o resto da API continua fechado para outra origem",
          r.headers.get("access-control-allow-origin") != "*", r.headers)

    r = cliente.get("/api/f/zzf_abc123/script.js")
    check("o script aponta para o endereço público da chave",
          r.status_code == 200 and "https://zz.exemplo.com/api/f/zzf_abc123" in r.text
          and "application/javascript" in r.headers["content-type"], r.text[:200])


async def etapa_whatsapp():
    print("\n[WhatsApp para quem preencheu]")
    _conectar_fake()
    await semear()
    await DB.whatsapp_connections.insert_one({
        "id": "conn-cloud", "tenant_id": TENANT, "phone_number_id": "pn-1",
        "waba_id": "waba-1", "status": "conectado", "departamento_padrao_id": None})
    await DB.whatsapp_connections.insert_one({
        "id": "conn-wuz", "tenant_id": TENANT, "canal": "wuzapi", "wuzapi_id": "w-1",
        "token_cifrado": cripto.cifrar("tok-wuz"), "status": "conectado",
        "departamento_padrao_id": None})

    # Canal não oficial: não há janela, sai texto.
    f = await rf.criar(_config(nome="Wuz", whatsapp={
        "ativo": True, "connection_id": "conn-wuz", "resposta_modo": "fila",
        "mensagem": "Oi {primeiro_nome}, aqui é da {empresa}!"}), ADMIN)
    await _enviar(f["chave"], {"nome": "Gil Souza", "celular": "85911112222"})
    check("na WuzAPI sai texto, com o primeiro nome e a empresa",
          len(ENVIOS) == 1 and ENVIOS[0]["tipo"] == "texto" and ENVIOS[0]["canal"] == "wuzapi"
          and "Oi Gil, aqui é da R3 Imóveis!" in ENVIOS[0]["texto"], ENVIOS)
    r = await DB.formulario_respostas.find_one({"nome": "Gil Souza"})
    s = await DB.conversation_sessions.find_one({"id": r["session_id"]})
    check("a resposta registra o envio e a conversa nasce como de formulário",
          r["whatsapp_status"] == "enviada" and s["origem"] == "formulario"
          and s["aguardando_primeira_resposta"] and s["formulario_resposta_id"] == r["id"], (r, s))

    await formularios.marcar_resposta(DB, TENANT, s)
    r = await DB.formulario_respostas.find_one({"id": r["id"]})
    s = await DB.conversation_sessions.find_one({"id": s["id"]})
    check("a resposta do lead é contada e a marca sai da conversa",
          r["respondeu_em"] and s["formulario_resposta_id"] is None)

    # Preencheu de novo meia hora depois do primeiro, e outro formulário.
    await DB.formulario_respostas.update_one(
        {"id": r["id"]}, {"$set": {"created_at": (datetime.now(timezone.utc)
                                                  - timedelta(minutes=5)).isoformat()}})
    f2 = await rf.criar(_config(nome="Outro form", whatsapp={
        "ativo": True, "connection_id": "conn-wuz", "resposta_modo": "agente"}), ADMIN)
    await _enviar(f2["chave"], {"nome": "Gil", "celular": "85911112222"})
    check("uma mensagem por pessoa em 30 minutos, mesmo em outro formulário",
          len(ENVIOS) == 1, ENVIOS)
    r2 = await DB.formulario_respostas.find_one({"formulario_id": f2["id"]})
    check("e o motivo fica na resposta", r2["whatsapp_status"] == "repetida", r2)

    # Cloud API, lead novo: janela fechada.
    ENVIOS.clear()
    f3 = await rf.criar(_config(nome="Cloud sem modelo", whatsapp={
        "ativo": True, "connection_id": "conn-cloud"}), ADMIN)
    await _enviar(f3["chave"], {"nome": "Hugo", "celular": "85922223333"})
    r3 = await DB.formulario_respostas.find_one({"formulario_id": f3["id"]})
    check("na Cloud API, sem modelo, nada sai e o motivo fica",
          not ENVIOS and r3["whatsapp_status"] == "sem_modelo", (ENVIOS, r3))
    hist = await DB.messages_log.find({"session_id": r3["session_id"]}).to_list(10)
    check("e aparece no histórico da conversa",
          any("janela de 24h" in (m.get("content") or "") for m in hist), hist)

    f4 = await rf.criar(_config(nome="Cloud com modelo", whatsapp={
        "ativo": True, "connection_id": "conn-cloud",
        "template": {"nome": "boas_vindas_lead", "idioma": "pt_BR",
                     "variaveis": ["{primeiro_nome}"]}}), ADMIN)
    await _enviar(f4["chave"], {"nome": "Iara Reis", "celular": "85933334444"})
    check("com modelo, sai o modelo com a variável preenchida",
          len(ENVIOS) == 1 and ENVIOS[0]["tipo"] == "modelo"
          and ENVIOS[0]["nome"] == "boas_vindas_lead"
          and "Iara" in json.dumps(ENVIOS[0]["componentes"], ensure_ascii=False), ENVIOS)

    check("rodar o envio de novo não manda outra vez (claim)",
          await formularios.enviar_whatsapp(DB, TENANT, r3["id"]) == "ignorada")


async def etapa_resumo_e_lgpd():
    print("\n[resumo por campanha e LGPD]")
    _conectar_fake()
    await semear()
    f = await rf.criar(_config(), ADMIN)
    leads = [("85900000001", "instagram", "lancamento"), ("85900000002", "instagram", "lancamento"),
             ("85900000003", "google", "marca"), ("85900000004", None, None)]
    for numero, fonte, campanha in leads:
        corpo = {"celular": numero, "nome": f"Lead {numero[-1]}"}
        if fonte:
            corpo.update(utm_source=fonte, utm_campaign=campanha)
        await _enviar(f["chave"], corpo)
    await _enviar(f["chave"], {"celular": "1"})

    # Um do Instagram fechou.
    r = await DB.formulario_respostas.find_one({"numero": "5585900000001"})
    await DB.deals.update_one({"id": r["deal_id"]},
                              {"$set": {"status": "ganho", "valor": 420000}})

    res = await rf.resumo(None, None, None, ADMIN)
    t = res["total"]
    check("o total conta respostas válidas, recusadas à parte",
          t["respostas"] == 4 and t["recusadas"] == 1 and t["contatos_novos"] == 4
          and t["negocios"] == 4, t)
    check("a venda é contada com o valor fechado", t["ganhos"] == 1 and t["valor_ganho"] == 420000, t)
    insta = next(l for l in res["por_origem"] if l["utm_source"] == "instagram")
    check("a quebra por origem diz quanto o Instagram vendeu",
          insta["respostas"] == 2 and insta["ganhos"] == 1 and insta["valor_ganho"] == 420000, insta)
    check("e vem primeiro, porque vendeu mais",
          res["por_origem"][0]["utm_source"] == "instagram", res["por_origem"])
    check("lead sem UTM aparece como origem vazia, não some",
          any(l["utm_source"] is None and l["respostas"] == 1 for l in res["por_origem"]))

    lista = await rf.listar(ADMIN)
    check("a grade mostra quantas respostas e a última",
          lista[0]["respostas"] == 4 and lista[0]["ultima_resposta"], lista[0])

    contato = await DB.contacts.find_one({"numero_whatsapp": "5585900000001"})
    await contatos.anonimizar(DB, TENANT, contato)
    r = await DB.formulario_respostas.find_one({"id": r["id"]})
    check("anonimizar tira o que a pessoa digitou e mantém a origem",
          r["dados"] == {} and r["numero"] is None and r["nome"] is None
          and r["utm"]["utm_source"] == "instagram", r)
    res2 = await rf.resumo(None, None, None, ADMIN)
    check("e a venda continua contando para a campanha",
          res2["total"]["valor_ganho"] == 420000, res2["total"])

    contato = await DB.contacts.find_one({"numero_whatsapp": "5585900000002"})
    await contatos.apagar(DB, TENANT, contato)
    check("apagar o contato leva as respostas dele",
          await DB.formulario_respostas.count_documents({"contact_id": contato["id"]}) == 0)

    await rf.excluir(f["id"], ADMIN)
    check("excluir o formulário mantém as respostas (são a origem das vendas)",
          await DB.formulario_respostas.count_documents({"formulario_id": f["id"]}) > 0)


async def _tudo():
    await etapa_leitura()
    await etapa_configuracao()
    await etapa_lead_novo()
    await etapa_existente_e_repeticao()
    await etapa_nenhum_lead_some()
    await etapa_portas()
    await etapa_whatsapp()
    await etapa_resumo_e_lgpd()
    print(f"\n{ok} verificações OK")


def test_suite():
    asyncio.run(_tudo())
    # O TestClient roda o próprio laço de eventos: fora do `asyncio.run`.
    asyncio.run(etapa_cors())


if __name__ == "__main__":
    test_suite()
