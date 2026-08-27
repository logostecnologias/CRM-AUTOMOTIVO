"""Teste da credencial de IA: cifra, validacao antes de gravar, resolucao
(chave do agente x chave da plataforma), cota do plano e permissoes.

A credencial e do AGENTE, nao da empresa — um cliente pode ter uma chave da
Anthropic no agente de suporte e uma da OpenAI no de vendas.

O provedor nunca e chamado de verdade aqui — `ai_client.validar` e substituido.
O que se testa e a regra em volta dele, que e onde moram os erros: gravar uma
chave que nao funciona, vazar o segredo para a tela, deixar a empresa B
alcancar o agente da empresa A, ou contar consumo errado.
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

from cryptography.fernet import Fernet

# A chave mestra precisa existir antes de qualquer cifra. Gerada aqui para o
# teste nao depender do .env da maquina.
os.environ["CREDENTIALS_KEY"] = Fernet.generate_key().decode()

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import ai_client
import ai_credentials
import ai_runtime
import routes.ai as rai

_MODULOS_FAKE = (rai,)


def _conectar_fake():
    db_mod.get_db = lambda: DB
    for _m in _MODULOS_FAKE:
        _m.get_db = lambda: DB


TENANT_A, TENANT_B = "t-a", "t-b"
ADMIN_A = {"id": "u-a", "tenant_id": TENANT_A, "role": "tenant_admin",
           "name": "Ana", "email": "ana@x.com"}
ADMIN_B = {"id": "u-b", "tenant_id": TENANT_B, "role": "tenant_admin",
           "name": "Bruno", "email": "bruno@x.com"}

CHAVE_ANTHROPIC = "sk-ant-api03-" + "K" * 40
CHAVE_OPENAI = "sk-proj-" + "Z" * 40

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


class _ValidacaoFalsa:
    """Substitui `ai_client.validar`. Guarda com que foi chamada, para o teste
    poder afirmar que a validacao aconteceu *antes* da gravacao."""

    def __init__(self):
        self.chamadas = []
        self.erro = None

    async def __call__(self, provedor, chave, modelo):
        self.chamadas.append((provedor, chave, modelo))
        if self.erro:
            raise ai_client.IAError(self.erro)
        return ai_client.Resposta(texto="ok", modelo=modelo, tokens_entrada=10,
                                  tokens_saida=2)


VALIDAR = _ValidacaoFalsa()


async def semear():
    DB._cols.clear()
    VALIDAR.chamadas.clear()
    VALIDAR.erro = None
    os.environ.pop("AI_PLATFORM_KEY", None)
    await DB.tenants.insert_one({"id": TENANT_A})
    await DB.tenants.insert_one({"id": TENANT_B})


# ---------------------------------------------------------------------------

async def etapa_cifra():
    print("\n[cifra da credencial]")
    bloco = ai_credentials.cifrar(CHAVE_ANTHROPIC)
    check("round-trip devolve a chave original",
          ai_credentials.decifrar(bloco) == CHAVE_ANTHROPIC)
    check("o segredo nao aparece no bloco gravado",
          CHAVE_ANTHROPIC not in str(bloco), bloco)
    check("a mascara mostra so prefixo e 4 finais",
          bloco["mascara"] == "sk-ant-…KKKK", bloco["mascara"])
    check("a versao da chave mestra fica gravada",
          bloco["chave_versao"] == ai_credentials.CHAVE_VERSAO)

    # Chave mestra trocada: tem que dizer o que houve, nao devolver lixo.
    original = os.environ["CREDENTIALS_KEY"]
    os.environ["CREDENTIALS_KEY"] = Fernet.generate_key().decode()
    try:
        ai_credentials.decifrar(bloco)
        check("chave mestra errada e recusada", False, "decifrou o que nao devia")
    except ai_credentials.CredencialError as e:
        check("chave mestra errada da erro explicito", "CREDENTIALS_KEY" in str(e), e)
    os.environ["CREDENTIALS_KEY"] = original

    # Versao antiga: pede reconexao em vez de falhar como "credencial invalida".
    antigo = {**bloco, "chave_versao": 0}
    try:
        ai_credentials.decifrar(antigo)
        check("versao anterior e recusada", False)
    except ai_credentials.CredencialError as e:
        # A mensagem serve as duas credenciais que passam por aqui (chave de IA
        # e token da Cloud API), entao ela pede para cadastrar de novo em vez de
        # falar em "reconectar a conta de IA".
        check("versao anterior pede cadastro de novo", "cadastrá-la de novo" in str(e), e)


async def etapa_salvar():
    print()
    print("[gravar credencial do agente]")
    await semear()
    # Provedor desconhecido nem chega perto da rede.
    st, det = await erro(rai.criar_agente(
        rai.AgenteIn(nome="X", provedor="deepseek", chave_api="sk-x"), ADMIN_A))
    check("provedor desconhecido e recusado", st == 400, (st, det))

    # Chave com o prefixo do outro provedor e barrada ANTES da chamada.
    VALIDAR.chamadas.clear()
    st, det = await erro(rai.criar_agente(
        rai.AgenteIn(nome="X", provedor="anthropic", chave_api=CHAVE_OPENAI), ADMIN_A))
    check("chave da openai no campo da anthropic e recusada", st == 400, (st, det))
    check("sem gastar chamada no provedor", VALIDAR.chamadas == [], VALIDAR.chamadas)

    # Caminho feliz: valida antes de gravar.
    VALIDAR.chamadas.clear()
    agente = await rai.criar_agente(rai.AgenteIn(
        nome="Bia", tipo="suporte", provedor="anthropic",
        modelo="claude-haiku-4-5", chave_api=CHAVE_ANTHROPIC), ADMIN_A)
    check("validou antes de gravar", len(VALIDAR.chamadas) == 1, VALIDAR.chamadas)
    check("gravou como ok", agente["credencial_status"] == "ok", agente)
    check("a chave em claro nao volta para a tela",
          CHAVE_ANTHROPIC not in str(agente), agente)
    check("so a mascara volta", agente["mascara"].startswith("sk-ant-")
          and agente["mascara"].endswith("KKKK"), agente["mascara"])

    # Chave recusada pelo provedor nao pode ser gravada.
    VALIDAR.erro = ai_client.IAError("Chave de API recusada pelo provedor.")
    st, det = await erro(rai.criar_agente(rai.AgenteIn(
        nome="Ruim", provedor="openai", chave_api=CHAVE_OPENAI), ADMIN_A))
    check("chave recusada nao e gravada", st == 400, (st, det))
    check("com o motivo do provedor", "recusada" in det, det)
    VALIDAR.erro = None
    restantes = await DB.ai_agents.find({"tenant_id": TENANT_A}).to_list(10)
    check("e o agente ruim nao ficou no banco", len(restantes) == 1, len(restantes))

    globals()["AGENTE_A"] = agente


async def etapa_isolamento():
    print()
    print("[uma empresa nao alcanca o agente da outra]")
    agente_b = await rai.criar_agente(rai.AgenteIn(
        nome="Do Bruno", provedor="openai", modelo="gpt-5-nano",
        chave_api=CHAVE_OPENAI), ADMIN_B)

    vistos_b = await rai.listar_agentes(ADMIN_B)
    check("B ve so o agente dele", [a["id"] for a in vistos_b] == [agente_b["id"]], vistos_b)
    vistos_a = await rai.listar_agentes(ADMIN_A)
    check("A ve so o dele", [a["id"] for a in vistos_a] == [AGENTE_A["id"]], vistos_a)

    # B nao alcanca o agente de A por id — o tenant_id entra no filtro de todas.
    st, _ = await erro(rai.ver_prompt(AGENTE_A["id"], ADMIN_B))
    check("B nao le o prompt do agente de A", st == 404, st)
    st, _ = await erro(rai.atualizar_agente(
        AGENTE_A["id"], rai.AgenteIn(nome="invadido"), ADMIN_B))
    check("B nao edita o agente de A", st == 404, st)
    st, _ = await erro(rai.remover_agente(AGENTE_A["id"], ADMIN_B))
    check("B nao apaga o agente de A", st == 404, st)
    st, _ = await erro(rai.testar_agente(
        AGENTE_A["id"], rai.TesteIn(mensagens=[{"role": "user", "content": "oi"}]), ADMIN_B))
    check("B nao testa (nem gasta a chave de) A", st == 404, st)

    sobrou = await DB.ai_agents.find_one({"id": AGENTE_A["id"]})
    check("o agente de A segue intacto", sobrou and sobrou["nome"] == "Bia", sobrou)


async def etapa_teste_de_conexao():
    print()
    print("[a chave pode morrer depois de salva]")

    async def responder_ok(db, tenant_id, agente, instrucoes, historico, **kw):
        return ai_client.Resposta(texto="ok", modelo="claude-haiku-4-5")

    async def responder_morto(db, tenant_id, agente, instrucoes, historico, **kw):
        raise ai_client.IAError("A conta no provedor esta sem saldo.")

    original = ai_runtime.responder_por_agente
    rai.ai_runtime.responder_por_agente = responder_ok
    try:
        msg = rai.TesteIn(mensagens=[{"role": "user", "content": "oi"}])
        r = await rai.testar_agente(AGENTE_A["id"], msg, ADMIN_A)
        check("teste responde quando a chave funciona", r["texto"] == "ok", r)

        rai.ai_runtime.responder_por_agente = responder_morto
        st, det = await erro(rai.testar_agente(AGENTE_A["id"], msg, ADMIN_A))
        check("chave morta devolve 400 com o motivo", st == 400 and "saldo" in det, (st, det))
        doc = await DB.ai_agents.find_one({"id": AGENTE_A["id"]})
        check("e o agente fica marcado como quebrado",
              doc["credencial_status"] == "erro", doc.get("credencial_status"))
        check("guardando o motivo para a tela", "saldo" in (doc.get("credencial_erro") or ""))

        rai.ai_runtime.responder_por_agente = responder_ok
        await rai.testar_agente(AGENTE_A["id"], msg, ADMIN_A)
        doc = await DB.ai_agents.find_one({"id": AGENTE_A["id"]})
        check("e desmarca quando volta a funcionar",
              doc["credencial_status"] == "ok", doc.get("credencial_status"))
    finally:
        rai.ai_runtime.responder_por_agente = original


async def etapa_resolucao_de_credencial():
    print("\n[de quem e a conta]")
    agente_a = await DB.ai_agents.find_one({"id": AGENTE_A["id"]}, {"_id": 0})
    sem_chave = {"id": "ag-sem", "nome": "Sem chave", "tenant_id": TENANT_B}

    # O agente de A tem chave propria: e a dela que responde.
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A, agente_a)
    check("empresa com conexao usa a conta dela",
          cred["origem"] == ai_runtime.ORIGEM_CLIENTE, cred["origem"])
    check("e a chave decifrada e a certa", cred["chave"] == CHAVE_ANTHROPIC)

    # Agente sem chave e sem chave de plataforma: erro claro.
    st, det = await erro(ai_runtime.resolver_credencial(DB, TENANT_B, sem_chave))
    check("sem chave e sem plataforma da 400", st == 400, (st, det))
    check("dizendo qual agente esta sem chave", "Sem chave" in det, det)

    # Com chave de plataforma configurada, a B passa a ter rede de seguranca.
    os.environ["AI_PLATFORM_KEY"] = "sk-plataforma"
    os.environ["AI_PLATFORM_PROVIDER"] = "openai"
    cred = await ai_runtime.resolver_credencial(DB, TENANT_B, sem_chave)
    check("sem chave propria cai na plataforma",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA, cred)
    check("com o modelo padrao do provedor da plataforma",
          cred["modelo"] == ai_client.modelo_padrao("openai"), cred["modelo"])

    # A chave do agente continua tendo precedencia sobre a plataforma.
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A, agente_a)
    check("chave do agente tem precedencia",
          cred["origem"] == ai_runtime.ORIGEM_CLIENTE, cred["origem"])

    # Credencial marcada como quebrada nao e usada: cai na plataforma em vez de
    # insistir numa chave que ja se sabe que nao funciona.
    cred = await ai_runtime.resolver_credencial(
        DB, TENANT_A, {**agente_a, "credencial_status": "erro"})
    check("credencial marcada como quebrada nao e reusada",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA, cred["origem"])

    os.environ.pop("AI_PLATFORM_PROVIDER", None)


async def etapa_medicao():
    print("\n[medicao de consumo]")
    resposta = ai_client.Resposta(
        texto="oi", modelo="claude-haiku-4-5",
        tokens_entrada=330, tokens_saida=120,
        tokens_cache_leitura=1500, tokens_cache_escrita=0)

    await ai_runtime.registrar_uso(DB, TENANT_A, ai_runtime.ORIGEM_CLIENTE,
                                   "anthropic", "claude-haiku-4-5", resposta)
    consumo = await ai_runtime.consumo_do_mes(DB, TENANT_A)
    check("uma chamada registrada", consumo["chamadas"] == 1, consumo)
    check("tokens somados de todas as categorias",
          consumo["tokens"] == 330 + 120 + 1500, consumo)
    esperado = round((330 * 1.00 + 120 * 5.00 + 1500 * 0.10) / 1_000_000, 4)
    check("custo bate com a tabela de precos",
          abs(consumo["custo_usd"] - esperado) < 1e-6, (consumo["custo_usd"], esperado))

    # Segunda chamada acumula no mesmo documento do dia.
    await ai_runtime.registrar_uso(DB, TENANT_A, ai_runtime.ORIGEM_CLIENTE,
                                   "anthropic", "claude-haiku-4-5", resposta)
    consumo = await ai_runtime.consumo_do_mes(DB, TENANT_A)
    check("segunda chamada acumula", consumo["chamadas"] == 2, consumo)
    check("um documento por dia/modelo, nao um por chamada",
          await DB.ai_usage.count_documents({"tenant_id": TENANT_A}) == 1)

    # O consumo de A nao vaza para B.
    check("consumo e por empresa",
          (await ai_runtime.consumo_do_mes(DB, TENANT_B))["chamadas"] == 0)

    # Falha ao medir nao pode derrubar a resposta ao contato.
    await ai_runtime.registrar_uso(DB, TENANT_A, ai_runtime.ORIGEM_CLIENTE,
                                   "provedor-que-nao-existe", "modelo-x", resposta)
    check("medicao com modelo desconhecido nao levanta", True)


async def etapa_cota_do_plano():
    print("\n[cota do plano]")
    await DB.plans.insert_one({"id": "p-1", "nome": "Essencial", "max_tokens_ia_mes": 1000})
    await DB.tenants.update_one({"id": TENANT_B}, {"$set": {"plan_id": "p-1"}})
    os.environ["AI_PLATFORM_KEY"] = "sk-plataforma"
    # Agente sem chave propria: e ele que consome a cota do plano.
    sem_chave = {"id": "ag-sem", "nome": "Sem chave", "tenant_id": TENANT_B}
    agente_a = await DB.ai_agents.find_one({"id": AGENTE_A["id"]}, {"_id": 0})

    # Abaixo do teto: passa.
    cred = await ai_runtime.resolver_credencial(DB, TENANT_B, sem_chave)
    check("abaixo do teto a plataforma responde",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA)

    # Estoura o teto.
    grande = ai_client.Resposta(texto="x", modelo="gpt-5-nano",
                                tokens_entrada=2000, tokens_saida=0)
    await ai_runtime.registrar_uso(DB, TENANT_B, ai_runtime.ORIGEM_PLATAFORMA,
                                   "openai", "gpt-5-nano", grande)
    st, det = await erro(ai_runtime.resolver_credencial(DB, TENANT_B, sem_chave))
    check("acima do teto o plano barra", st == 403, (st, det))
    check("a mensagem sugere usar chave propria", "chave de IA propria" in det.replace("ó", "o"), det)

    # Agente com chave propria nao tem teto nosso, mesmo com a empresa estourada.
    await DB.tenants.update_one({"id": TENANT_A}, {"$set": {"plan_id": "p-1"}})
    await ai_runtime.registrar_uso(DB, TENANT_A, ai_runtime.ORIGEM_CLIENTE,
                                   "openai", "gpt-5-nano", grande)
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A, agente_a)
    check("chave propria nao tem teto do plano",
          cred["origem"] == ai_runtime.ORIGEM_CLIENTE, cred["origem"])

    # Teto 0 = ilimitado.
    await DB.plans.update_one({"id": "p-1"}, {"$set": {"max_tokens_ia_mes": 0}})
    cred = await ai_runtime.resolver_credencial(DB, TENANT_B, sem_chave)
    check("teto 0 significa ilimitado",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA, cred)

    os.environ.pop("AI_PLATFORM_KEY", None)


async def etapa_barreira_de_permissao():
    print("\n[barreira de permissao]")
    # Chamar a funcao da rota direto NAO executa o Depends — a guarda so pode
    # ser conferida onde ela e declarada, na assinatura do endpoint.
    import auth
    endpoints = [rai.listar_provedores, rai.consumo, rai.catalogo_de_agentes,
                 rai.listar_agentes, rai.criar_agente, rai.atualizar_agente,
                 rai.remover_agente, rai.testar_agente, rai.ver_prompt]
    for fn in endpoints:
        deps = [p.default.dependency for p in inspect.signature(fn).parameters.values()
                if hasattr(p.default, "dependency")]
        check(f"{fn.__name__} exige tenant_admin",
              auth.require_tenant_admin in deps, deps)

    # E a guarda em si funciona.
    st, _ = await erro(auth.require_tenant_admin(
        {"id": "x", "role": "agent", "tenant_id": TENANT_A}))
    check("atendente e barrado por require_tenant_admin", st == 403, st)
    st, _ = await erro(auth.require_tenant_admin({"id": "x", "role": "tenant_admin"}))
    check("admin sem tenant e barrado", st == 403, st)


async def etapa_catalogo():
    print("\n[catalogo]")
    cat = ai_client.catalogo_publico()
    check("os dois provedores aparecem", {c["id"] for c in cat} == {"anthropic", "openai"}, cat)
    for prov in cat:
        check(f"{prov['id']} tem link do console", prov["console_url"].startswith("https://"))
        for m in prov["modelos"]:
            check(f"{m['id']} expoe preco de cache", "cache_leitura" in m, m)
            check(f"{m['id']} tem preco de cache menor que o de entrada",
                  m["cache_leitura"] < m["entrada"], m)
    check("o catalogo nao carrega segredo nenhum",
          "prefixo_chave" not in str(cat) and "chave" not in str(cat).lower())


# ---------------------------------------------------------------------------

def test_suite():
    _conectar_fake()
    ai_client.validar = VALIDAR

    async def _tudo():
        await etapa_cifra()
        await etapa_salvar()
        await etapa_isolamento()
        await etapa_teste_de_conexao()
        await etapa_resolucao_de_credencial()
        await etapa_medicao()
        await etapa_cota_do_plano()
        await etapa_barreira_de_permissao()
        await etapa_catalogo()
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())
