"""Teste da conexao de IA: cifra da credencial, validacao antes de gravar,
resolucao de credencial (empresa x plataforma), cota do plano e permissoes.

O provedor nunca e chamado de verdade aqui — `ai_client.validar` e substituido.
O que se testa e a regra em volta dele, que e onde moram os erros: gravar uma
chave que nao funciona, vazar o segredo para a tela, deixar a empresa B ver a
conexao da empresa A, ou contar consumo errado.
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, r"c:\Projetos DEV\LOGOS - ZappZen\ZappZen-BotsWpp\backend")
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "WUZAPI_GATEWAY_URL": "http://x"}.items():
    os.environ.setdefault(k, v)

from cryptography.fernet import Fernet

# A chave mestra precisa existir antes de qualquer cifra. Gerada aqui para o
# teste nao depender do .env da maquina.
os.environ["AI_CREDENTIALS_KEY"] = Fernet.generate_key().decode()

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
    original = os.environ["AI_CREDENTIALS_KEY"]
    os.environ["AI_CREDENTIALS_KEY"] = Fernet.generate_key().decode()
    try:
        ai_credentials.decifrar(bloco)
        check("chave mestra errada e recusada", False, "decifrou o que nao devia")
    except ai_credentials.CredencialError as e:
        check("chave mestra errada da erro explicito", "AI_CREDENTIALS_KEY" in str(e), e)
    os.environ["AI_CREDENTIALS_KEY"] = original

    # Versao antiga: pede reconexao em vez de falhar como "credencial invalida".
    antigo = {**bloco, "chave_versao": 0}
    try:
        ai_credentials.decifrar(antigo)
        check("versao anterior e recusada", False)
    except ai_credentials.CredencialError as e:
        check("versao anterior pede reconexao", "reconectar" in str(e), e)


async def etapa_salvar():
    print("\n[salvar conexao]")
    await semear()

    # Prefixo errado nao chega a gastar uma chamada no provedor.
    st, det = await erro(rai.salvar_conexao(
        rai.ConexaoIn(provedor="anthropic", chave_api=CHAVE_OPENAI), ADMIN_A))
    check("chave do provedor errado e recusada", st == 400, (st, det))
    check("e nem chamou o provedor", len(VALIDAR.chamadas) == 0, VALIDAR.chamadas)

    # Provedor recusa a chave: nada pode ser gravado.
    VALIDAR.erro = "Chave de API recusada pelo provedor."
    st, det = await erro(rai.salvar_conexao(
        rai.ConexaoIn(provedor="anthropic", chave_api=CHAVE_ANTHROPIC), ADMIN_A))
    check("chave recusada devolve 400 com o motivo", st == 400 and "recusada" in det, (st, det))
    check("nada foi gravado quando a validacao falhou",
          await DB.ai_connections.find_one({"tenant_id": TENANT_A}) is None)

    # Caminho feliz.
    VALIDAR.erro = None
    antes = len(VALIDAR.chamadas)
    dados = await rai.salvar_conexao(
        rai.ConexaoIn(provedor="anthropic", chave_api=CHAVE_ANTHROPIC), ADMIN_A)
    check("conexao gravada como conectada", dados["status"] == "conectada", dados)
    check("modelo cai no padrao do provedor",
          dados["modelo"] == ai_client.modelo_padrao("anthropic"), dados["modelo"])
    check("a validacao rodou antes de gravar",
          len(VALIDAR.chamadas) == antes + 1, VALIDAR.chamadas)

    # O que a tela recebe nao pode conter o segredo.
    serializado = str(dados)
    check("a resposta da rota nao traz a chave", CHAVE_ANTHROPIC not in serializado)
    check("nem o texto cifrado", "cifrada" not in serializado, serializado)
    check("mas traz a mascara", dados["mascara"] == "sk-ant-…KKKK", dados["mascara"])

    # No banco a chave esta cifrada, nao em texto puro.
    guardado = await DB.ai_connections.find_one({"tenant_id": TENANT_A})
    check("no banco a chave esta cifrada",
          CHAVE_ANTHROPIC not in str(guardado), "chave em texto puro no banco!")

    # Trocar so o modelo, sem reenviar a chave (a tela nunca a devolveu).
    dados = await rai.salvar_conexao(
        rai.ConexaoIn(provedor="anthropic", modelo="claude-sonnet-5"), ADMIN_A)
    check("troca de modelo sem reenviar a chave", dados["modelo"] == "claude-sonnet-5", dados)
    check("e reaproveitou a chave guardada",
          VALIDAR.chamadas[-1][1] == CHAVE_ANTHROPIC, VALIDAR.chamadas[-1])

    # Trocar de provedor sem chave nova nao tem como funcionar.
    st, det = await erro(rai.salvar_conexao(rai.ConexaoIn(provedor="openai"), ADMIN_A))
    check("trocar de provedor exige chave nova", st == 400, (st, det))

    # Modelo inexistente.
    st, det = await erro(rai.salvar_conexao(
        rai.ConexaoIn(provedor="anthropic", modelo="claude-inventado"), ADMIN_A))
    check("modelo fora do catalogo e recusado", st == 400, (st, det))

    # Uma conexao por empresa: o segundo salvamento atualiza, nao duplica.
    check("nao duplicou documento",
          await DB.ai_connections.count_documents({"tenant_id": TENANT_A}) == 1)


async def etapa_isolamento():
    print("\n[isolamento entre empresas]")
    # A empresa B nao enxerga a conexao da A, mesmo sendo admin da propria.
    visto = await rai.obter_conexao(ADMIN_B)
    check("empresa B nao ve a conexao da empresa A", visto["conexao"] is None, visto)

    st, det = await erro(rai.testar_conexao(ADMIN_B))
    check("testar sem conexao propria da 404", st == 404, (st, det))

    # E o delete da B nao pode apagar a da A.
    await rai.remover_conexao(ADMIN_B)
    check("delete da B nao apagou a conexao da A",
          await DB.ai_connections.find_one({"tenant_id": TENANT_A}) is not None)


async def etapa_teste_de_conexao():
    print("\n[reteste da conexao]")
    # Chave revogada no console do provedor: o status tem que refletir isso.
    VALIDAR.erro = "Chave de API recusada pelo provedor."
    r = await rai.testar_conexao(ADMIN_A)
    check("reteste com falha devolve ok=False", r["ok"] is False, r)
    guardado = await DB.ai_connections.find_one({"tenant_id": TENANT_A})
    check("status vira erro", guardado["status"] == "erro", guardado["status"])
    check("o motivo fica gravado", "recusada" in (guardado["ultimo_erro"] or ""), guardado)

    # Voltou a funcionar: limpa o erro.
    VALIDAR.erro = None
    r = await rai.testar_conexao(ADMIN_A)
    check("reteste bem-sucedido devolve ok=True", r["ok"] is True, r)
    guardado = await DB.ai_connections.find_one({"tenant_id": TENANT_A})
    check("status volta a conectada", guardado["status"] == "conectada")
    check("o erro anterior e limpo", guardado["ultimo_erro"] is None, guardado)


async def etapa_resolucao_de_credencial():
    print("\n[de quem e a conta]")
    # A empresa A tem conexao propria: e a dela que responde.
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A)
    check("empresa com conexao usa a conta dela",
          cred["origem"] == ai_runtime.ORIGEM_CLIENTE, cred["origem"])
    check("e a chave decifrada e a certa", cred["chave"] == CHAVE_ANTHROPIC)

    # A empresa B nao tem conexao e nao ha chave de plataforma: erro claro.
    st, det = await erro(ai_runtime.resolver_credencial(DB, TENANT_B))
    check("sem conexao e sem plataforma da 400", st == 400, (st, det))
    check("com texto que a tela pode mostrar", "Conecte a conta" in det, det)

    # Com chave de plataforma configurada, a B passa a ter rede de seguranca.
    os.environ["AI_PLATFORM_KEY"] = "sk-plataforma"
    os.environ["AI_PLATFORM_PROVIDER"] = "openai"
    cred = await ai_runtime.resolver_credencial(DB, TENANT_B)
    check("sem conexao propria cai na plataforma",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA, cred)
    check("com o modelo padrao do provedor da plataforma",
          cred["modelo"] == ai_client.modelo_padrao("openai"), cred["modelo"])

    # Conexao propria continua tendo precedencia sobre a plataforma.
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A)
    check("conexao propria tem precedencia",
          cred["origem"] == ai_runtime.ORIGEM_CLIENTE, cred["origem"])

    # Conexao em erro nao e usada: cai na plataforma em vez de tentar uma
    # chave que ja se sabe que nao funciona.
    await DB.ai_connections.update_one({"tenant_id": TENANT_A}, {"$set": {"status": "erro"}})
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A)
    check("conexao com erro nao e usada",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA, cred["origem"])
    await DB.ai_connections.update_one({"tenant_id": TENANT_A}, {"$set": {"status": "conectada"}})

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

    # Abaixo do teto: passa.
    cred = await ai_runtime.resolver_credencial(DB, TENANT_B)
    check("abaixo do teto a plataforma responde",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA)

    # Estoura o teto.
    grande = ai_client.Resposta(texto="x", modelo="gpt-5-nano",
                                tokens_entrada=2000, tokens_saida=0)
    await ai_runtime.registrar_uso(DB, TENANT_B, ai_runtime.ORIGEM_PLATAFORMA,
                                   "openai", "gpt-5-nano", grande)
    st, det = await erro(ai_runtime.resolver_credencial(DB, TENANT_B))
    check("acima do teto o plano barra", st == 403, (st, det))
    check("a mensagem sugere conectar a conta propria", "Conecte a conta" in det, det)

    # Empresa com conta propria nao tem teto nosso, mesmo estourada.
    await DB.tenants.update_one({"id": TENANT_A}, {"$set": {"plan_id": "p-1"}})
    await ai_runtime.registrar_uso(DB, TENANT_A, ai_runtime.ORIGEM_CLIENTE,
                                   "openai", "gpt-5-nano", grande)
    cred = await ai_runtime.resolver_credencial(DB, TENANT_A)
    check("conta propria nao tem teto do plano",
          cred["origem"] == ai_runtime.ORIGEM_CLIENTE, cred["origem"])

    # Teto 0 = ilimitado.
    await DB.plans.update_one({"id": "p-1"}, {"$set": {"max_tokens_ia_mes": 0}})
    cred = await ai_runtime.resolver_credencial(DB, TENANT_B)
    check("teto 0 significa ilimitado",
          cred["origem"] == ai_runtime.ORIGEM_PLATAFORMA, cred)

    os.environ.pop("AI_PLATFORM_KEY", None)


async def etapa_barreira_de_permissao():
    print("\n[barreira de permissao]")
    # Chamar a funcao da rota direto NAO executa o Depends — a guarda so pode
    # ser conferida onde ela e declarada, na assinatura do endpoint.
    import auth
    endpoints = [rai.listar_provedores, rai.obter_conexao, rai.salvar_conexao,
                 rai.testar_conexao, rai.remover_conexao, rai.consumo]
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
