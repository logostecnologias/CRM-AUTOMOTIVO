"""Teste do módulo de agendamento, com Mongo falso.

O que este arquivo cobre é o que falha em silêncio: horário que continua
aparecendo depois de marcado, dois contatos na mesma cadeira, feriado que não
fecha a agenda, e a resposta ao lembrete cancelando a consulta errada.

O que ele **não** cobre, e continua exigindo teste de fumaça com o banco no ar
é o que só o Mongo real decide: se os índices de `appointments` são aceitos e
se a agregação do resumo devolve o mesmo que o falso.
"""
import asyncio
import os
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste"}.items():
    os.environ.setdefault(k, v)

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import agenda as dominio
import agenda_flow
import agenda_worker
import ai_tools
import routes.scheduling as rs

_MODULOS_FAKE = (rs, agenda_worker, agenda_flow)


def _conectar_fake():
    """(Re)aponta o `get_db` de cada módulo para o Mongo falso DESTE arquivo.

    Chamado no início do teste, não só no import: o pytest importa todos os
    módulos de teste no mesmo processo, e `get_db` é atributo de módulo
    compartilhado, sem isto o último arquivo importado ficaria com o banco de
    todos.
    """
    db_mod.get_db = lambda: DB
    for m in _MODULOS_FAKE:
        m.get_db = lambda: DB


TENANT = "t-1"
OUTRO = "t-2"
ADMIN = {"id": "u-admin", "tenant_id": TENANT, "role": "tenant_admin",
         "name": "Dona da Clínica", "email": "a@x.com"}
ATENDENTE = {"id": "u-rec", "tenant_id": TENANT, "role": "agent",
             "name": "Recepção", "email": "r@x.com"}

TZ = ZoneInfo("America/Sao_Paulo")
ok = 0


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        raise AssertionError(nome)


async def erro(coro, status=None):
    """Roda esperando HTTPException. Devolve o detalhe."""
    try:
        await coro
    except HTTPException as e:
        if status is not None and e.status_code != status:
            raise AssertionError(f"esperava {status}, veio {e.status_code}: {e.detail}")
        return e.detail
    raise AssertionError("esperava HTTPException e não veio")


# ---------------------------------------------------------------------------
# Datas de referência
# ---------------------------------------------------------------------------
#
# Todas as datas do teste caem numa segunda-feira futura: dia útil na grade
# padrão. Datas relativas ao dia da execução fariam o teste passar numa terça e
# falhar num sábado.
#
# Quatro semanas, e não oito: a antecedência máxima padrão é de 60 dias, e
# "oito semanas + alinhar na segunda" chega a 62 quando o teste roda numa
# terça: a agenda recusaria o horário e a falha apareceria como "grade sem
# horário nenhum", que manda procurar no lugar errado.

def _segunda_futura(semanas: int = 4):
    d = datetime.now(TZ).date() + timedelta(weeks=semanas)
    return d + timedelta(days=(0 - d.weekday()) % 7)


SEGUNDA = _segunda_futura()
TERCA = SEGUNDA + timedelta(days=1)
SABADO = SEGUNDA + timedelta(days=5)


def instante(d, hh, mm=0) -> str:
    return dominio._iso(datetime.combine(d, time(hh, mm), tzinfo=TZ))


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------

async def etapa_semear():
    _conectar_fake()
    await DB.tenants.insert_one({"id": TENANT, "nome": "Clínica Teste"})
    await DB.users.insert_one(dict(ADMIN))
    await DB.users.insert_one(dict(ATENDENTE))
    await DB.contacts.insert_one({
        "id": "c-1", "tenant_id": TENANT, "nome": "Maria Souza",
        "numero_whatsapp": "5511999990001"})
    await DB.contacts.insert_one({
        "id": "c-2", "tenant_id": TENANT, "nome": "João Lima",
        "numero_whatsapp": "5511999990002"})

    corte = await rs.criar_servico(rs.ServicoIn(
        nome="Corte masculino", duracao_min=30, preco=50.0), ADMIN)
    coloracao = await rs.criar_servico(rs.ServicoIn(
        nome="Coloração", duracao_min=120, preco=250.0), ADMIN)
    ana = await rs.criar_recurso(rs.RecursoIn(nome="Ana"), ADMIN)
    bruno = await rs.criar_recurso(rs.RecursoIn(nome="Bruno"), ADMIN)

    check("serviço nasce com id e duração", corte["duracao_min"] == 30)
    check("recurso nasce com a grade comercial padrão",
          len(ana["grade"]) == 7 and ana["grade"][0] and not ana["grade"][5],
          ana["grade"])
    return {"corte": corte, "coloracao": coloracao, "ana": ana, "bruno": bruno}


async def etapa_horarios_basicos(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    check("config sem documento devolve os padrões",
          config["passo_min"] == 30 and config["fuso"] == "America/Sao_Paulo")

    livres = await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
        dia=SEGUNDA.isoformat(), config=config)
    horas = [h["hora"] for h in livres]
    check("grade 9-12 e 13-18 com passo de 30 gera 16 horários",
          len(livres) == 16, horas)
    check("o primeiro é 09:00 e o último 17:30",
          horas[0] == "09:00" and horas[-1] == "17:30", horas)
    check("não gera horário no intervalo de almoço", "12:00" not in horas, horas)

    # Serviço de 2h: o último começo possível de manhã é 10:00 (termina 12:00).
    longos = await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["coloracao"],
        dia=SEGUNDA.isoformat(), config=config)
    manha = [h["hora"] for h in longos if h["hora"] < "12:00"]
    check("serviço de 2h não começa às 10:30 (não caberia antes do almoço)",
          manha == ["09:00", "09:30", "10:00"], manha)

    fds = await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
        dia=SABADO.isoformat(), config=config)
    check("sábado sem grade não oferece horário", fds == [])


async def etapa_marcar_ocupa(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    contato = await DB.contacts.find_one({"id": "c-1"})

    doc = await dominio.agendar(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"], contato=contato,
        inicio=instante(SEGUNDA, 14), config=config, origem="manual",
        criado_por=ADMIN["id"])
    check("agendamento nasce em 'agendado'", doc["status"] == dominio.STATUS_AGENDADO)
    check("fim é início + duração do serviço",
          doc["fim"] == instante(SEGUNDA, 14, 30), doc["fim"])

    livres = await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
        dia=SEGUNDA.isoformat(), config=config)
    horas = [h["hora"] for h in livres]
    check("o horário marcado deixa de ser oferecido", "14:00" not in horas, horas)
    check("os vizinhos continuam livres",
          "13:30" in horas and "14:30" in horas, horas)

    # É este o ponto do módulo inteiro: um serviço longo que *atravessa* o
    # horário marcado também some, mesmo começando noutro minuto.
    longos = [h["hora"] for h in await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["coloracao"],
        dia=SEGUNDA.isoformat(), config=config)]
    check("serviço de 2h não é oferecido às 13:00 (invadiria as 14h)",
          "13:00" not in longos and "13:30" not in longos, longos)
    ctx["marcado"] = doc


async def etapa_conflito(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    outro = await DB.contacts.find_one({"id": "c-2"})

    detalhe = await erro(dominio.agendar(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"], contato=outro,
        inicio=instante(SEGUNDA, 14), config=config), 409)
    check("mesmo horário e mesmo profissional é recusado", "ocupado" in detalhe, detalhe)

    # Sobreposição parcial: coloração às 13h terminaria às 15h, em cima do corte.
    await erro(dominio.agendar(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["coloracao"], contato=outro,
        inicio=instante(SEGUNDA, 13), config=config), 409)
    check("sobreposição parcial também é recusada", True)

    # Nenhum dos dois deixou registro para trás: recusar tem que ser limpo,
    # senão o horário fica ocupado por um agendamento que não existe.
    n = await DB.appointments.count_documents({"tenant_id": TENANT, "contact_id": "c-2"})
    check("tentativa recusada não deixa agendamento gravado", n == 0, n)

    doc = await dominio.agendar(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"], contato=outro,
        inicio=instante(SEGUNDA, 14), config=config)
    check("o mesmo horário com outro profissional é aceito",
          doc["resource_id"] == ctx["bruno"]["id"])
    await dominio.cancelar(DB, TENANT, doc["id"], por=ADMIN["id"])


async def etapa_equipe(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    horarios = await dominio.horarios_do_dia(
        DB, TENANT, recursos=[ctx["ana"], ctx["bruno"]], servico=ctx["corte"],
        dia=SEGUNDA.isoformat(), config=config)
    catorze = [h for h in horarios if h["hora"] == "14:00"]
    check("14h aparece uma vez só mesmo com dois profissionais livres",
          len(catorze) == 1, catorze)
    check("14h aponta para quem está livre (Ana está ocupada)",
          catorze[0]["resource_id"] == ctx["bruno"]["id"], catorze)

    horas = [h["hora"] for h in horarios]
    check("a lista da equipe vem ordenada e sem repetição",
          horas == sorted(set(horas)), horas)


async def etapa_cancelar_libera(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    doc = await dominio.cancelar(DB, TENANT, ctx["marcado"]["id"],
                                 por=ADMIN["id"], motivo="Cliente remarcou")
    check("cancelar muda o status", doc["status"] == dominio.STATUS_CANCELADO)

    guardado = await DB.appointments.find_one({"id": ctx["marcado"]["id"]})
    check("cancelar NÃO apaga o registro", guardado is not None)
    check("o motivo fica gravado", guardado["motivo_cancelamento"] == "Cliente remarcou")

    horas = [h["hora"] for h in await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
        dia=SEGUNDA.isoformat(), config=config)]
    check("o horário cancelado volta a ser oferecido", "14:00" in horas, horas)


async def etapa_folga_e_feriado(ctx):
    _conectar_fake()
    # Folga do profissional num dia.
    await rs.editar_recurso(ctx["ana"]["id"], rs.RecursoIn(
        nome="Ana", grade=ctx["ana"]["grade"],
        excecoes=[{"data": TERCA.isoformat(), "fechado": True, "motivo": "Folga"}]), ADMIN)
    ana = await DB.resources.find_one({"id": ctx["ana"]["id"]}, {"_id": 0})
    config = await dominio.configuracao(DB, TENANT)
    check("folga do profissional zera o dia dele",
          await dominio.horarios_livres(DB, TENANT, recurso=ana, servico=ctx["corte"],
                                        dia=TERCA.isoformat(), config=config) == [])
    check("o outro profissional continua atendendo nesse dia",
          len(await dominio.horarios_livres(DB, TENANT, recurso=ctx["bruno"],
                                            servico=ctx["corte"],
                                            dia=TERCA.isoformat(), config=config)) > 0)

    # Horário especial num dia: exceção com janela, em vez de fechamento.
    await rs.editar_recurso(ctx["ana"]["id"], rs.RecursoIn(
        nome="Ana", grade=ctx["ana"]["grade"],
        excecoes=[{"data": TERCA.isoformat(), "fechado": False,
                   "janelas": [{"inicio": "08:00", "fim": "10:00"}]}]), ADMIN)
    ana = await DB.resources.find_one({"id": ctx["ana"]["id"]}, {"_id": 0})
    horas = [h["hora"] for h in await dominio.horarios_livres(
        DB, TENANT, recurso=ana, servico=ctx["corte"],
        dia=TERCA.isoformat(), config=config)]
    check("exceção com janela substitui a grade do dia",
          horas == ["08:00", "08:30", "09:00", "09:30"], horas)

    # Feriado da empresa fecha todo mundo.
    await rs.salvar_config(rs.ConfigIn(
        bloqueios=[{"data": TERCA.isoformat(), "motivo": "Feriado"}]), ADMIN)
    config = await dominio.configuracao(DB, TENANT)
    check("feriado da empresa ganha da exceção do profissional",
          await dominio.horarios_livres(DB, TENANT, recurso=ana, servico=ctx["corte"],
                                        dia=TERCA.isoformat(), config=config) == [])
    check("feriado fecha também quem não tem exceção",
          await dominio.horarios_livres(DB, TENANT, recurso=ctx["bruno"],
                                        servico=ctx["corte"],
                                        dia=TERCA.isoformat(), config=config) == [])

    await rs.salvar_config(rs.ConfigIn(bloqueios=[]), ADMIN)
    await rs.editar_recurso(ctx["ana"]["id"], rs.RecursoIn(
        nome="Ana", grade=ctx["ana"]["grade"]), ADMIN)
    ctx["ana"] = await DB.resources.find_one({"id": ctx["ana"]["id"]}, {"_id": 0})


async def etapa_intervalo_e_antecedencia(ctx):
    _conectar_fake()
    await rs.salvar_config(rs.ConfigIn(intervalo_min=15), ADMIN)
    config = await dominio.configuracao(DB, TENANT)
    contato = await DB.contacts.find_one({"id": "c-1"})

    doc = await dominio.agendar(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"], contato=contato,
        inicio=instante(SEGUNDA, 10), config=config)
    horas = [h["hora"] for h in await dominio.horarios_livres(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"],
        dia=SEGUNDA.isoformat(), config=config)]
    check("a folga de 15 min também bloqueia o horário seguinte",
          "10:30" not in horas, horas)
    check("com a folga cumprida, 11:00 continua livre", "11:00" in horas, horas)
    check("o horário anterior respeita a folga do que vem depois",
          "09:30" not in horas, horas)
    await dominio.cancelar(DB, TENANT, doc["id"])
    await rs.salvar_config(rs.ConfigIn(intervalo_min=0), ADMIN)

    config = await dominio.configuracao(DB, TENANT)
    ontem = dominio._agora() - timedelta(days=1)
    detalhe = await erro(dominio.agendar(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"], contato=contato,
        inicio=dominio._iso(ontem), config=config), 400)
    check("marcar no passado é recusado pela antecedência mínima",
          "antecedência" in detalhe, detalhe)

    # `forcar` é o encaixe da recepção: passa por cima da grade...
    forcado = await dominio.agendar(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"], contato=contato,
        inicio=instante(SEGUNDA, 20), config=config, forcar=True)
    check("encaixe fora do expediente é aceito com forcar", forcado["id"])
    # ...mas nunca por cima de outro atendimento.
    await erro(dominio.agendar(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"],
        contato=await DB.contacts.find_one({"id": "c-2"}),
        inicio=instante(SEGUNDA, 20), config=config, forcar=True), 409)
    check("forcar NÃO dispensa a checagem de sobreposição", True)
    await dominio.cancelar(DB, TENANT, forcado["id"])

    fora = await erro(dominio.agendar(
        DB, TENANT, recurso=ctx["bruno"], servico=ctx["corte"], contato=contato,
        inicio=instante(SABADO, 10), config=config), 409)
    check("sem forcar, sábado (sem grade) é recusado",
          "fora do horário" in fora, fora)


async def etapa_proximos_dias(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    dias = await dominio.proximos_dias(
        DB, TENANT, recursos=[ctx["ana"], ctx["bruno"]], servico=ctx["corte"],
        config=config, a_partir_de=SABADO.isoformat(), limite_dias=3)
    check("a varredura pula sábado e domingo",
          [d["dia"] for d in dias][0] == (SABADO + timedelta(days=2)).isoformat(), dias)
    check("cada dia vem com a contagem de vagas", all(d["vagas"] > 0 for d in dias))


async def etapa_isolamento(ctx):
    _conectar_fake()
    await DB.services.insert_one({"id": "s-outro", "tenant_id": OUTRO,
                                  "nome": "De outra empresa", "duracao_min": 30,
                                  "ativo": True, "ordem": 0, "recursos": []})
    servicos = await dominio.servicos_ativos(DB, TENANT)
    check("serviço de outra empresa não aparece",
          all(s["id"] != "s-outro" for s in servicos))
    await erro(rs.editar_servico("s-outro", rs.ServicoIn(nome="x", duracao_min=30),
                                 ADMIN), 404)
    check("editar serviço de outra empresa dá 404", True)

    contato = await DB.contacts.find_one({"id": "c-1"})
    config = await dominio.configuracao(DB, TENANT)
    doc = await dominio.agendar(DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
                                contato=contato, inicio=instante(SEGUNDA, 15),
                                config=config)
    await erro(dominio.cancelar(DB, OUTRO, doc["id"]), 404)
    check("cancelar agendamento de outra empresa dá 404", True)
    await dominio.cancelar(DB, TENANT, doc["id"])


async def etapa_exclusao_protegida(ctx):
    _conectar_fake()
    contato = await DB.contacts.find_one({"id": "c-1"})
    config = await dominio.configuracao(DB, TENANT)
    doc = await dominio.agendar(DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
                                contato=contato, inicio=instante(SEGUNDA, 16),
                                config=config)

    detalhe = await erro(rs.remover_servico(ctx["corte"]["id"], ADMIN), 409)
    check("excluir serviço com horário marcado é recusado, dizendo quantos",
          "1 horário" in detalhe, detalhe)
    await erro(rs.remover_recurso(ctx["ana"]["id"], ADMIN), 409)
    check("excluir profissional com horário marcado é recusado", True)

    await dominio.cancelar(DB, TENANT, doc["id"])
    servico = await rs.criar_servico(rs.ServicoIn(nome="Descartável", duracao_min=15),
                                     ADMIN)
    await rs.remover_servico(servico["id"], ADMIN)
    check("serviço sem agendamento é excluído normalmente",
          await DB.services.find_one({"id": servico["id"]}) is None)


async def etapa_rotas(ctx):
    _conectar_fake()
    dia = await rs.horarios(ctx["corte"]["id"], SEGUNDA.isoformat(), None, ATENDENTE)
    check("a rota de horários devolve o fuso junto",
          dia["fuso"] == "America/Sao_Paulo" and len(dia["horarios"]) > 0)

    marcado = await rs.marcar(rs.AgendamentoIn(
        service_id=ctx["corte"]["id"], resource_id=ctx["ana"]["id"],
        inicio=instante(SEGUNDA, 11), contact_id="c-1", avisar=False), ATENDENTE)
    check("o atendente marca (não é rota de admin)", marcado["status"] == "agendado")
    check("a origem manual fica registrada", marcado["origem"] == "manual")

    # Contato novo criado na hora, pelo número, sem passar por outra tela.
    novo = await rs.marcar(rs.AgendamentoIn(
        service_id=ctx["corte"]["id"], resource_id=ctx["bruno"]["id"],
        inicio=instante(SEGUNDA, 11), contact_nome="Carlos",
        contact_numero="(11) 98888-7777", avisar=False), ATENDENTE)
    contato = await DB.contacts.find_one({"id": novo["contact_id"]})
    check("número do contato novo passa por normaliza_numero",
          contato["numero_whatsapp"] == "5511988887777", contato["numero_whatsapp"])

    # O mesmo número de novo reaproveita a ficha, não cria uma segunda.
    await rs.marcar(rs.AgendamentoIn(
        service_id=ctx["corte"]["id"], resource_id=ctx["bruno"]["id"],
        inicio=instante(SEGUNDA, 15), contact_nome="Carlos S.",
        contact_numero="11988887777", avisar=False), ATENDENTE)
    n = await DB.contacts.count_documents({"tenant_id": TENANT,
                                           "numero_whatsapp": "5511988887777"})
    check("o mesmo número não cria uma segunda ficha", n == 1, n)

    lista = await rs.listar_agendamentos(
        de=instante(SEGUNDA, 0), ate=instante(TERCA, 0), user=ATENDENTE)
    check("a listagem da janela vem ordenada por início",
          [a["inicio"] for a in lista["items"]] == sorted(a["inicio"] for a in lista["items"]))

    resumo = await rs.resumo(de=instante(SEGUNDA, 0), ate=instante(TERCA, 0),
                             user=ADMIN)
    check("o resumo conta por status numa agregação só",
          resumo["agendado"] == lista["total"] - resumo["cancelado"],
          (resumo, lista["total"]))

    await rs.mudar_status(marcado["id"], rs.StatusIn(status="faltou"), ATENDENTE)
    doc = await DB.appointments.find_one({"id": marcado["id"]})
    check("marcar falta é registrado por gente, não deduzido do relógio",
          doc["status"] == "faltou")


async def etapa_guardas():
    _conectar_fake()
    import inspect
    from auth import require_tenant_admin, require_tenant_member

    # O `Depends` não roda ao chamar a função da rota direto: a guarda é
    # conferida onde ela é declarada.
    def guarda(fn):
        for p in inspect.signature(fn).parameters.values():
            dep = getattr(p.default, "dependency", None)
            if dep in (require_tenant_admin, require_tenant_member):
                return dep
        return None

    so_admin = [rs.salvar_config, rs.criar_servico, rs.editar_servico,
                rs.remover_servico, rs.criar_recurso, rs.editar_recurso,
                rs.remover_recurso]
    equipe = [rs.ver_config, rs.listar_servicos, rs.listar_recursos, rs.horarios,
              rs.dias_com_vaga, rs.listar_agendamentos, rs.resumo, rs.marcar,
              rs.cancelar_agendamento, rs.mudar_status]
    check("configurar a agenda é só do admin",
          all(guarda(f) is require_tenant_admin for f in so_admin),
          [f.__name__ for f in so_admin if guarda(f) is not require_tenant_admin])
    check("marcar e cancelar é de quem atende",
          all(guarda(f) is require_tenant_member for f in equipe),
          [f.__name__ for f in equipe if guarda(f) is not require_tenant_member])

    await erro(require_tenant_admin(ATENDENTE), 403)
    check("require_tenant_admin recusa o atendente de verdade", True)


# ---------------------------------------------------------------------------
# Lembrete
# ---------------------------------------------------------------------------

async def etapa_lembrete(ctx):
    _conectar_fake()
    config = await dominio.configuracao(DB, TENANT)
    contato = await DB.contacts.find_one({"id": "c-1"})

    # Um horário para daqui a 10h: dentro da janela padrão de 24h de lembrete.
    perto = dominio._agora() + timedelta(hours=10)
    doc = await dominio.agendar(DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
                                contato=contato, inicio=dominio._iso(perto),
                                config=config, forcar=True)
    # E um para daqui a 5 dias: fora dela.
    longe = await dominio.agendar(DB, TENANT, recurso=ctx["ana"], servico=ctx["corte"],
                                  contato=contato,
                                  inicio=dominio._iso(dominio._agora() + timedelta(days=5)),
                                  config=config, forcar=True)

    pendentes = await agenda_worker._pendentes(DB, dominio._agora())
    ids = [a["id"] for a in pendentes]
    check("a varredura pega o horário dentro da janela", doc["id"] in ids, ids)
    check("e também vê o distante, que é filtrado pela janela da empresa",
          longe["id"] in ids, ids)

    # A filtragem por empresa acontece no laço, com a config dela.
    dentro = [a for a in pendentes
              if a["inicio"] <= dominio._iso(dominio._agora() + timedelta(hours=24))]
    check("só o de 10h cabe na janela de 24h configurada",
          [a["id"] for a in dentro] == [doc["id"]], dentro)

    texto = agenda_worker.texto_de("lembrete", doc, config)
    check("o lembrete traz serviço, dia e o que responder",
          "Corte masculino" in texto and "CONFIRMAR" in texto, texto)
    check("o placeholder do nome usa o primeiro nome", "Maria" in texto, texto)

    modelo = agenda_worker.montar("Oi {contato}, {inexistente} às {hora}", doc, config)
    check("placeholder desconhecido fica como está, sem derrubar o envio",
          "{inexistente}" in modelo, modelo)
    ctx["lembrado"] = doc
    ctx["longe"] = longe


async def etapa_resposta_do_lembrete(ctx):
    _conectar_fake()
    session = {"id": "sess-1", "tenant_id": TENANT, "contact_id": "c-1",
               "agenda_aguardando": ctx["lembrado"]["id"]}
    await DB.conversation_sessions.insert_one(dict(session))

    enviados = []

    async def _fake_send(tenant_id, session_id, content):
        enviados.append(content)
        return True

    import flow_runtime
    original = flow_runtime.send_human_message
    flow_runtime.send_human_message = _fake_send
    try:
        # Mensagem que **contém** "cancelar" mas não é uma resposta ao lembrete.
        r = await agenda_worker.responder_lembrete(
            DB, TENANT, dict(session), "quero cancelar meu pedido de ontem")
        check("cotejo é com a mensagem inteira, nunca 'contém'", r is None, r)
        atual = await DB.appointments.find_one({"id": ctx["lembrado"]["id"]})
        check("e o agendamento continua de pé", atual["status"] == "agendado")

        r = await agenda_worker.responder_lembrete(DB, TENANT, dict(session), "Confirmar")
        check("CONFIRMAR confirma a presença", r == "confirmado", r)
        atual = await DB.appointments.find_one({"id": ctx["lembrado"]["id"]})
        check("o status vira confirmado e a data fica registrada",
              atual["status"] == "confirmado" and atual["confirmado_em"])
        check("o contato recebe a resposta", enviados and "confirmada" in enviados[-1],
              enviados)

        sessao = await DB.conversation_sessions.find_one({"id": "sess-1"})
        check("a espera é limpa depois de respondida",
              sessao.get("agenda_aguardando") is None)

        # Sem a marca na conversa, "sim" não pode cancelar nada: é justamente o
        # contexto que torna a palavra curta segura.
        r = await agenda_worker.responder_lembrete(
            DB, TENANT, {"id": "sess-1", "tenant_id": TENANT}, "sim")
        check("sem lembrete pendente, 'sim' não faz nada", r is None, r)

        session2 = {"id": "sess-2", "tenant_id": TENANT, "contact_id": "c-1",
                    "agenda_aguardando": ctx["longe"]["id"]}
        await DB.conversation_sessions.insert_one(dict(session2))
        r = await agenda_worker.responder_lembrete(DB, TENANT, dict(session2), "cancelar")
        check("CANCELAR cancela o horário", r == "cancelado", r)
        atual = await DB.appointments.find_one({"id": ctx["longe"]["id"]})
        check("e o horário volta a ficar livre para outra pessoa",
              atual["status"] == "cancelado")
    finally:
        flow_runtime.send_human_message = original


# ---------------------------------------------------------------------------
# Ferramentas do agente de IA
# ---------------------------------------------------------------------------

async def etapa_resposta_solta_ao_lembrete(ctx):
    """O contato responde ao lembrete outra coisa que não CONFIRMAR/CANCELAR.

    A conversa aberta pelo aviso nasce sem bot, então ela cai no mesmo ramo em
    que caía a resposta de campanha. Dizer "bot indisponível" ali descreveria um
    defeito onde não há nenhum: é o que este teste tranca.
    """
    _conectar_fake()
    import flow_runtime

    enviadas = []

    async def fake_send(token, numero, texto, *a, **kw):
        enviadas.append(texto)
        return {"ok": True}

    originais = (flow_runtime.get_db, flow_runtime.whatsapp.send_text)
    flow_runtime.get_db = lambda: DB
    flow_runtime.whatsapp.send_text = fake_send
    try:
        await DB.whatsapp_connections.insert_one({
            "id": "conn-ag", "tenant_id": TENANT, "phone_number_id": "pn-teste", "waba_id": "waba-teste",
            "status": "conectado"})
        await DB.conversation_sessions.insert_one({
            "id": "sess-ag", "tenant_id": TENANT, "contact_id": "c-1",
            "whatsapp_connection_id": "conn-ag", "status": "ativa",
            "status_atendimento": "bot", "bot_id": None, "flow_id": None,
            "origem": "agenda", "awaiting": None, "variables": {},
            "ia_respostas": 0, "unread_count": 0,
            "aguardando_primeira_resposta": False})

        await flow_runtime.handle_incoming_message(
            TENANT, "5511999990001", "posso remarcar?", "msg-ag-1",
            connection_id="conn-ag")

        sistema = await DB.messages_log.find(
            {"session_id": "sess-ag", "direction": "sistema"}).to_list(10)
        textos = [m["content"] for m in sistema]
        check("resposta solta a um lembrete vai para a fila humana",
              any("atendimento humano" in t for t in textos), textos)
        check("e o motivo diz que foi um aviso de agendamento, não 'bot indisponível'",
              any("aviso de agendamento" in t for t in textos)
              and not any("Bot da conversa indisponível" in t for t in textos), textos)
        sessao = await DB.conversation_sessions.find_one({"id": "sess-ag"})
        check("a conversa entra na fila em vez de ficar muda",
              sessao["status_atendimento"] == "aguardando", sessao["status_atendimento"])
    finally:
        (flow_runtime.get_db, flow_runtime.whatsapp.send_text) = originais


async def etapa_duplicata(ctx):
    """Nome repetido é recusado, que é a trava contra o duplo clique.

    A tela também impede o clique repetido, mas ela não cobre duas abas abertas
    nem um retry de rede: nesses casos chegam duas requisições idênticas, e sem
    esta checagem nascem dois cadastros. Foi o bug relatado.
    """
    _conectar_fake()
    detalhe = await erro(rs.criar_servico(rs.ServicoIn(
        nome="Corte masculino", duracao_min=30), ADMIN), 409)
    check("serviço com nome repetido é recusado com 409",
          "Já existe" in detalhe, detalhe)

    detalhe = await erro(rs.criar_servico(rs.ServicoIn(
        nome="  corte MASCULINO  ", duracao_min=30), ADMIN), 409)
    check("a comparação ignora caixa e espaço em volta",
          "Já existe" in detalhe, detalhe)

    await erro(rs.criar_recurso(rs.RecursoIn(nome="Ana"), ADMIN), 409)
    check("profissional com nome repetido é recusado", True)

    # Nome com parêntese vai para dentro de uma regex do Mongo: sem escape a
    # consulta quebraria em vez de comparar.
    especial = await rs.criar_servico(rs.ServicoIn(
        nome="Corte (infantil)", duracao_min=20), ADMIN)
    await erro(rs.criar_servico(rs.ServicoIn(
        nome="Corte (infantil)", duracao_min=20), ADMIN), 409)
    check("nome com caractere de regex é comparado, não executado", True)

    # Renomear para o próprio nome continua valendo: senão editar o preço de um
    # serviço sem mexer no nome passaria a devolver 409.
    editado = await rs.editar_servico(especial["id"], rs.ServicoIn(
        nome="Corte (infantil)", duracao_min=25), ADMIN)
    check("salvar o mesmo registro sem trocar o nome continua funcionando",
          editado["duracao_min"] == 25)

    await erro(rs.editar_servico(especial["id"], rs.ServicoIn(
        nome="Corte masculino", duracao_min=25), ADMIN), 409)
    check("renomear para o nome de outro é recusado", True)

    outra = await rs.criar_servico(rs.ServicoIn(nome="Corte masculino", duracao_min=30),
                                   {"id": "u-x", "tenant_id": OUTRO, "role": "tenant_admin"})
    check("o mesmo nome noutra empresa é permitido", outra["id"])
    await DB.services.delete_one({"id": outra["id"]})
    await DB.services.delete_one({"id": especial["id"]})


async def etapa_corrida_de_mensagens(ctx):
    """Uma conversa é processada uma mensagem por vez.

    Foi o bug que quebrou um agendamento real: o nó gravou `awaiting` na etapa
    do dia e, um segundo depois, uma mensagem que tinha chegado antes terminou
    de ser processada ainda enxergando o Menu anterior, respondeu "resposta
    inválida" e regravou o `awaiting` do Menu por cima. O contato escolheu o dia
    e não deu em nada.

    O teste mira o **mecanismo**, não uma corrida encenada. Encenar não funciona
    aqui: o Mongo falso nunca suspende a execução, então duas tasks passadas ao
    `gather` rodam uma inteira depois da outra e a corrida jamais acontece. Um
    teste assim passaria com a trava desligada, que foi exatamente o que ele fez
    na primeira versão.
    """
    _conectar_fake()
    import flow_runtime

    dentro, pico = [], 0

    async def tarefa(chave):
        nonlocal pico
        async with flow_runtime._uma_por_vez(chave):
            dentro.append(chave)
            pico = max(pico, len(dentro))
            await asyncio.sleep(0.01)
            dentro.pop()

    await asyncio.gather(*(tarefa("conversa-a") for _ in range(4)))
    check("na mesma conversa, uma mensagem por vez", pico == 1, pico)

    pico = 0
    await asyncio.gather(*(tarefa(f"conversa-{i}") for i in range(4)))
    check("conversas diferentes continuam andando em paralelo", pico == 4, pico)
    check("o dicionário de travas não vaza uma entrada por contato",
          flow_runtime._travas_por_conversa == {}, flow_runtime._travas_por_conversa)

    # E o webhook realmente passa por ela, com a chave da conversa.
    chaves = []
    original = flow_runtime._uma_por_vez

    def espiao(chave):
        chaves.append(chave)
        return original(chave)

    async def fake_send(token, numero, texto, *a, **kw):
        return {"ok": True}

    guardados = (flow_runtime.get_db, flow_runtime.whatsapp.send_text)
    flow_runtime._uma_por_vez = espiao
    flow_runtime.get_db = lambda: DB
    flow_runtime.whatsapp.send_text = fake_send
    try:
        await DB.whatsapp_connections.insert_one({
            "id": "conn-corrida", "tenant_id": TENANT, "phone_number_id": "pn-teste", "waba_id": "waba-teste",
            "status": "conectado"})
        await flow_runtime.handle_incoming_message(
            TENANT, "5511977776666", "oi", "corrida-1", connection_id="conn-corrida")
        check("o webhook entra na trava, com a chave da conversa",
              chaves == [f"{TENANT}:conn-corrida:5511977776666"], chaves)
    finally:
        flow_runtime._uma_por_vez = original
        (flow_runtime.get_db, flow_runtime.whatsapp.send_text) = guardados


async def etapa_ferramentas_ia(ctx):
    _conectar_fake()
    contato = await DB.contacts.find_one({"id": "c-2"}, {"_id": 0})
    executar = ai_tools.executor(DB, TENANT, contato, {"id": "s-ia"})

    r = await executar("consultar_horarios", {"servico": "corte"})
    check("nome parcial casa com o serviço cadastrado", "Corte masculino" in r, r)
    check("sem dia, devolve os próximos dias com vaga", "Próximos dias" in r, r)

    r = await executar("consultar_horarios", {"servico": "manicure"})
    check("serviço inexistente devolve a lista dos que existem",
          "Corte masculino" in r and "Coloração" in r, r)

    r = await executar("consultar_horarios",
                       {"servico": "Corte masculino", "dia": SEGUNDA.isoformat()})
    check("com dia, devolve as horas e quem atende", "09:00 com" in r, r)

    r = await executar("consultar_horarios",
                       {"servico": "Corte masculino", "profissional": "Zezinho"})
    check("profissional inexistente devolve quem atende",
          "Ana" in r and "Bruno" in r, r)

    r = await executar("agendar", {"servico": "Corte masculino",
                                   "dia": SEGUNDA.isoformat(), "hora": "16:30"})
    check("agendar marca de verdade e manda confirmar", r.startswith("MARCADO"), r)
    doc = await DB.appointments.find_one({"tenant_id": TENANT, "contact_id": "c-2",
                                          "origem": "ia"})
    check("o agendamento da IA fica com origem 'ia'", doc is not None)
    check("e amarrado à conversa em que aconteceu", doc["session_id"] == "s-ia")

    # O mesmo horário de novo **não** é recusado enquanto sobrar alguém na
    # equipe: é o desenho do módulo, e a marcação vai para o outro profissional.
    r = await executar("agendar", {"servico": "Corte masculino",
                                   "dia": SEGUNDA.isoformat(), "hora": "16:30"})
    check("com dois profissionais, o mesmo horário ainda cabe, no outro",
          r.startswith("MARCADO") and doc["resource_nome"] not in r, r)
    segundo = await DB.appointments.find_one(
        {"tenant_id": TENANT, "contact_id": "c-2", "origem": "ia",
         "resource_id": {"$ne": doc["resource_id"]}, "status": "agendado"})

    r = await executar("agendar", {"servico": "Corte masculino",
                                   "dia": SEGUNDA.isoformat(), "hora": "16:30"})
    check("com a equipe toda ocupada, aí sim é recusado",
          "não está disponível" in r, r)
    check("e a resposta já oferece alternativas concretas do mesmo dia",
          "O que resta nesse dia" in r and "09:00" in r, r)

    r = await executar("agendar", {"servico": "Corte masculino",
                                   "dia": SABADO.isoformat(), "hora": "10:00"})
    check("dia sem grade devolve alternativa, não erro cru",
          "nenhum horário" in r or "Consulte outro dia" in r, r)

    r = await executar("cancelar_agendamento", {})
    check("com mais de um horário marcado, cancelar pergunta qual em vez de chutar",
          "mais de um horário" in r, r)
    await dominio.cancelar(DB, TENANT, segundo["id"])

    r = await executar("cancelar_agendamento", {"motivo": "mudou de ideia"})
    check("com um só, cancelar age sobre o horário do próprio contato",
          r.startswith("CANCELADO"), r)
    atual = await DB.appointments.find_one({"id": doc["id"]})
    check("o cancelamento é gravado com o motivo",
          atual["status"] == "cancelado" and "mudou de ideia" in atual["motivo_cancelamento"])

    r = await executar("cancelar_agendamento", {})
    check("sem horário marcado, cancelar avisa em vez de estourar",
          "não tem nenhum horário" in r, r)

    r = await executar("ferramenta_inventada", {})
    check("ferramenta desconhecida vira texto, nunca exceção",
          r.startswith("ERRO"), r)


async def etapa_ia_simulada(ctx):
    _conectar_fake()
    contato = await DB.contacts.find_one({"id": "c-2"}, {"_id": 0})
    executar = ai_tools.executor(DB, TENANT, contato, None, simulado=True)
    antes = await DB.appointments.count_documents({"tenant_id": TENANT})
    r = await executar("agendar", {"servico": "Corte masculino",
                                   "dia": TERCA.isoformat(), "hora": "10:00"})
    depois = await DB.appointments.count_documents({"tenant_id": TENANT})
    check("no chat de teste a consulta roda e a marcação não grava",
          "simulação" in r and antes == depois, (r, antes, depois))


async def etapa_prompt_da_ia(ctx):
    _conectar_fake()
    import ai_agents

    agente = {"nome": "Bia", "tipo": "agendamento", "empresa_nome": "Clínica Teste"}
    bloco, ferramentas, executar = await ai_agents.preparar_agenda(DB, TENANT, agente)
    check("agente sem agenda_ativa não recebe catálogo nem ferramentas",
          bloco == "" and ferramentas is None)

    instr = ai_agents.montar_instrucoes(agente)
    check("sem agenda, o agente de agendamento é avisado que não pode reservar",
          "NÃO tem acesso à agenda" in instr, instr[:400])

    agente["agenda_ativa"] = True
    bloco, ferramentas, executar = await ai_agents.preparar_agenda(
        DB, TENANT, agente, await DB.contacts.find_one({"id": "c-1"}, {"_id": 0}))
    check("com agenda ligada, o catálogo entra no prompt",
          "Corte masculino" in bloco and "Ana" in bloco, bloco[:300])
    check("e as três ferramentas são registradas",
          {f.nome for f in ferramentas} ==
          {"consultar_horarios", "agendar", "cancelar_agendamento"})

    instr = ai_agents.montar_instrucoes(agente, bloco)
    check("com agenda, some o aviso de que não pode reservar",
          "NÃO tem acesso à agenda" not in instr)
    check("o catálogo não carrega nada do contato (senão quebraria o cache)",
          "Maria" not in bloco and "c-1" not in bloco, bloco[:300])


# ---------------------------------------------------------------------------
# Nó de Agendamento do editor de fluxos
# ---------------------------------------------------------------------------

async def etapa_no_de_fluxo(ctx):
    _conectar_fake()
    no = {"id": "n-ag", "type": "schedule", "data": {
        "label": "Agendar", "modo_profissional": "qualquer",
        "dias_oferecidos": 5, "formato": "lista"}}
    session = {"id": "s-fluxo", "tenant_id": TENANT, "contact_id": "c-1",
               "whatsapp_connection_id": "conn-1", "variables": {}, "awaiting": None}

    outputs = []
    saida = await agenda_flow.avancar(no, session, outputs)
    check("a primeira pergunta é o serviço", saida is None and len(outputs) == 1)
    menu = outputs[0]
    check("a pergunta sai como Menu, pelo caminho de envio que já existe",
          menu["type"] == "menu" and menu["formato"] == "lista")
    check("as opções são os serviços ativos",
          {i["label"] for i in menu["itens"]} == {"Corte masculino", "Coloração"},
          menu["itens"])
    check("os rótulos ficam guardados para a resposta do botão ter texto",
          set(session["awaiting"]["rotulos"].values()) ==
          {"Corte masculino", "Coloração"})

    # O contato "toca" no serviço, pelo id, como um botão de verdade.
    outputs = []
    saida = await agenda_flow.avancar(no, session, outputs,
                                      escolha_id=ctx["corte"]["id"])
    check("depois do serviço vem o dia", session["awaiting"]["etapa"] == "dia")
    check("só dias com vaga são oferecidos, e a descrição diz a primeira hora",
          all(i["descricao"].startswith("a partir das") for i in outputs[0]["itens"]),
          [i["descricao"] for i in outputs[0]["itens"]])
    check("a contagem de vagas NÃO vai para o contato",
          not any("livre" in i["descricao"] for i in outputs[0]["itens"]),
          [i["descricao"] for i in outputs[0]["itens"]])

    # E digita o número em vez de tocar: o mesmo resolvedor do nó de Menu.
    dias = [i["id"] for i in outputs[0]["itens"]]
    outputs = []
    saida = await agenda_flow.avancar(no, session, outputs, resposta="1")
    check("responder pelo número funciona igual a tocar",
          session["awaiting"]["etapa"] == "hora", session["awaiting"])
    check("o dia escolhido é o primeiro da lista",
          session["awaiting"]["dados"]["dia"] == dias[0])

    check("com um profissional só, o nome dele não se repete em cada horário",
          all(i["descricao"] == "" for i in outputs[0]["itens"]),
          [i["descricao"] for i in outputs[0]["itens"]][:3])

    horas = [i["id"] for i in outputs[0]["itens"]]
    outputs = []
    saida = await agenda_flow.avancar(no, session, outputs, escolha_id=horas[0])
    check("escolhida a hora, o nó sai por 'agendado'", saida == agenda_flow.SAIDA_OK, saida)
    check("e o contato recebe a confirmação",
          any(o["type"] == "text" and "Corte masculino" in o["content"] for o in outputs),
          outputs)
    check("o awaiting é limpo ao terminar", session["awaiting"] is None)
    check("as variáveis do agendamento ficam disponíveis ao resto do fluxo",
          session["variables"]["agendamento_servico"] == "Corte masculino"
          and session["variables"]["agendamento_id"], session["variables"])

    doc = await DB.appointments.find_one({"id": session["variables"]["agendamento_id"]})
    check("o agendamento do bot fica com origem 'bot' e amarrado à conversa",
          doc["origem"] == "bot" and doc["session_id"] == "s-fluxo")


async def etapa_no_resposta_invalida(ctx):
    _conectar_fake()
    no = {"id": "n-ag", "type": "schedule", "data": {
        "modo_profissional": "qualquer", "formato": "lista"}}
    session = {"id": "s-inv", "tenant_id": TENANT, "contact_id": "c-1",
               "variables": {}, "awaiting": None}
    await agenda_flow.avancar(no, session, [])

    for i in range(agenda_flow.MAX_TENTATIVAS - 1):
        outputs = []
        saida = await agenda_flow.avancar(no, session, outputs, resposta="oi tudo bem?")
        check(f"resposta fora das opções repete a pergunta ({i + 1})",
              saida is None and outputs[0]["content"].startswith("Não entendi"),
              outputs)

    outputs = []
    saida = await agenda_flow.avancar(no, session, outputs, resposta="???")
    check("depois de insistir, o nó sai por 'não agendou' em vez de travar",
          saida == agenda_flow.SAIDA_FALHA, saida)
    check("o contato recebe o texto configurado, e o motivo vai para o histórico",
          any(o["type"] == "system" and "não escolheu" in o["content"] for o in outputs),
          outputs)
    check("o motivo também fica em variável, para o fluxo poder ramificar",
          "não escolheu" in session["variables"]["agendamento_falha"])


async def etapa_no_simulado(ctx):
    _conectar_fake()
    no = {"id": "n-ag", "type": "schedule", "data": {"modo_profissional": "qualquer"}}
    session = {"id": "s-teste", "tenant_id": TENANT, "variables": {},
               "awaiting": None, "simulado": True}
    antes = await DB.appointments.count_documents({"tenant_id": TENANT})

    await agenda_flow.avancar(no, session, [])
    await agenda_flow.avancar(no, session, [], escolha_id=ctx["corte"]["id"])
    outputs = []
    await agenda_flow.avancar(no, session, outputs, resposta="1")
    horas = [i["id"] for i in outputs[0]["itens"]]
    outputs = []
    saida = await agenda_flow.avancar(no, session, outputs, escolha_id=horas[0])

    depois = await DB.appointments.count_documents({"tenant_id": TENANT})
    check("o chat de teste do editor percorre o nó até o fim",
          saida == agenda_flow.SAIDA_OK, saida)
    check("mas não ocupa horário nenhum", antes == depois, (antes, depois))
    check("e diz que foi simulação",
          any("simulação" in o.get("content", "") for o in outputs), outputs)


async def etapa_validacao_do_no():
    _conectar_fake()
    check("nó com profissional fixo sem profissional é reprovado na publicação",
          any("exige escolher" in p
              for p in agenda_flow.validar({"modo_profissional": "fixo"})))
    check("botões não comportam agendamento",
          any("não cabe em botões" in p
              for p in agenda_flow.validar({"formato": "botoes"})))
    check("configuração válida passa",
          agenda_flow.validar({"modo_profissional": "qualquer", "formato": "lista",
                               "dias_oferecidos": 5}) == [])


async def etapa_grade_invalida():
    _conectar_fake()
    detalhe = await erro(rs.criar_recurso(rs.RecursoIn(
        nome="Torto", grade=[[{"inicio": "18:00", "fim": "08:00"}], [], [], [], [], [], []]),
        ADMIN), 400)
    check("janela invertida é recusada com o dia no texto",
          "Segunda" in detalhe, detalhe)

    detalhe = await erro(rs.criar_recurso(rs.RecursoIn(
        nome="Encavalado",
        grade=[[{"inicio": "09:00", "fim": "12:00"}, {"inicio": "11:00", "fim": "15:00"}],
               [], [], [], [], [], []]), ADMIN), 400)
    check("janelas sobrepostas no mesmo dia são recusadas",
          "sobrepõem" in detalhe, detalhe)

    await erro(rs.criar_recurso(rs.RecursoIn(nome="Curto", grade=[[], []]), ADMIN), 400)
    check("grade que não tem 7 dias é recusada", True)

    await erro(rs.salvar_config(rs.ConfigIn(fuso="Marte/Olympus"), ADMIN), 400)
    check("fuso desconhecido é recusado na entrada, não descoberto na agenda", True)


# ---------------------------------------------------------------------------

async def _suite():
    print("\n=== agenda ===")
    ctx = await etapa_semear()
    await etapa_horarios_basicos(ctx)
    await etapa_marcar_ocupa(ctx)
    await etapa_conflito(ctx)
    await etapa_equipe(ctx)
    await etapa_cancelar_libera(ctx)
    await etapa_folga_e_feriado(ctx)
    await etapa_intervalo_e_antecedencia(ctx)
    await etapa_proximos_dias(ctx)
    await etapa_isolamento(ctx)
    await etapa_exclusao_protegida(ctx)
    await etapa_rotas(ctx)
    await etapa_guardas()
    await etapa_lembrete(ctx)
    await etapa_resposta_do_lembrete(ctx)
    await etapa_resposta_solta_ao_lembrete(ctx)
    await etapa_duplicata(ctx)
    await etapa_corrida_de_mensagens(ctx)
    await etapa_ferramentas_ia(ctx)
    await etapa_ia_simulada(ctx)
    await etapa_prompt_da_ia(ctx)
    await etapa_no_de_fluxo(ctx)
    await etapa_no_resposta_invalida(ctx)
    await etapa_no_simulado(ctx)
    await etapa_validacao_do_no()
    await etapa_grade_invalida()
    print(f"\n{ok} verificações OK")


def test_suite():
    asyncio.run(_suite())


if __name__ == "__main__":
    test_suite()
