"""Agendamento: grade de disponibilidade, horários livres e a marcação em si.

Existe porque parte dos clientes vende **hora**, não produto: clínica, salão,
oficina, consultório. Para eles a conversa no WhatsApp não termina num pedido,
termina num horário reservado, e um horário reservado é o único dado deste
sistema que **duas pessoas não podem ter ao mesmo tempo**.

Cinco decisões moldam o módulo:

  - **Horário livre é calculado na leitura, nunca materializado.** A alternativa
    seria gravar um documento por slot de cada profissional para os próximos N
    dias: uma coleção enorme, que precisaria ser regerada toda vez que alguém
    mudasse a grade ou tirasse férias, e que ficaria errada entre a mudança e a
    regeração. O que se guarda é a **grade** (poucas linhas) e o que já foi
    **marcado**; o livre é a subtração de um pelo outro, sobre um dia e um
    profissional de cada vez. Mesmo raciocínio de `atividades.com_atraso`.

  - **O fuso é da empresa e fica gravado, e aqui a regra do resto do sistema
    se inverte.** Em atividades e relatórios o corte de "hoje" vem do navegador,
    porque quem olha a tela é quem define o dia. Aqui não: "segunda das 9h às
    18h" é o horário de funcionamento *da empresa*, e quem consulta a agenda com
    mais frequência é o bot, que roda no servidor, sem navegador nenhum. Sem um
    fuso gravado, um atendimento marcado às 14h sairia às 17h para quem está no
    UTC. Por isso `scheduling_settings.fuso`.

  - **A grade é hora local de parede; o agendamento é instante em UTC.** A grade
    diz "09:00" e continua dizendo "09:00" quando o horário de verão entra; o
    agendamento diz o momento exato, no mesmo formato ISO-UTC que o resto do
    sistema grava e compara como string.

  - **Contra dupla marcação: insere, confere, e quem vê conflito recua.** O
    Mongo aqui não tem transação, e a janela entre "calculei que 14h está livre"
    e "gravei as 14h" é suficiente para duas conversas simultâneas marcarem o
    mesmo horário com o mesmo profissional. Um índice único não resolve, porque
    o conflito é de **intervalo** (um serviço de 2h às 14h colide com um de 30min
    às 15h, e as chaves seriam diferentes). Então a marcação é gravada e
    **imediatamente reconferida**; quem enxergar outra marcação sobreposta
    desfaz a sua e devolve 409. No pior caso (as duas conferem depois de as
    duas gravarem), as duas recuam e ninguém marca: o contato ouve "esse
    horário acabou de ser ocupado" e escolhe outro. É o erro que se aceita, porque o
    outro erro é duas pessoas na cadeira às 14h. Desempatar por id não serviria:
    quem confere primeiro pode passar antes de o segundo existir, e o relógio do
    Windows anda de 15ms em 15ms, então `created_at` empata.

  - **Cancelar não apaga.** O horário volta a ficar livre porque a consulta
    filtra por status, e o registro fica: é dele que sai a taxa de falta, o
    motivo do cancelamento e o histórico do contato.
"""
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

logger = logging.getLogger("zappzen.agenda")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

FUSO_PADRAO = "America/Sao_Paulo"

# Estados de um agendamento. `agendado` é o que nasce; `confirmado` é o que o
# contato respondeu ao lembrete. Os dois, mais `concluido`, ocupam o horário;
# `cancelado` e `faltou` o liberam (faltou porque o horário já passou, e mantê-lo
# ocupado não muda nada, mas contá-lo como ocupação estragaria um remarcamento
# no mesmo dia).
STATUS_AGENDADO = "agendado"
STATUS_CONFIRMADO = "confirmado"
STATUS_CONCLUIDO = "concluido"
STATUS_CANCELADO = "cancelado"
STATUS_FALTOU = "faltou"
STATUS = (STATUS_AGENDADO, STATUS_CONFIRMADO, STATUS_CONCLUIDO,
          STATUS_CANCELADO, STATUS_FALTOU)
OCUPAM = (STATUS_AGENDADO, STATUS_CONFIRMADO, STATUS_CONCLUIDO)

ORIGENS = ("manual", "bot", "ia")

TIPOS_RECURSO = ("pessoa", "sala", "equipamento")

# Dia da semana no formato de `date.weekday()`: 0 = segunda.
DIAS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")

# Padrões de uma empresa que acabou de ativar o módulo. Existem para a primeira
# tela já vir preenchida com algo plausível: configuração em branco é
# configuração que ninguém termina.
PADROES = {
    "fuso": FUSO_PADRAO,
    # De quanto em quanto tempo um horário pode começar. 30 min é o passo de
    # quase todo comércio de serviço; 15 atende quem trabalha com encaixe.
    "passo_min": 30,
    # Folga entre um atendimento e o seguinte (limpeza, sala, deslocamento).
    "intervalo_min": 0,
    # O contato não marca para daqui a cinco minutos: ninguém chega a tempo.
    "antecedencia_min_horas": 2,
    # Nem para daqui a dois anos: a agenda ficaria cheia de fantasmas.
    "antecedencia_max_dias": 60,
    "cancelamento_min_horas": 2,
    "lembrete_ativo": True,
    "lembrete_horas": 24,
}

# Teto de dias varridos quando alguém pede "o próximo horário livre". Sem ele,
# uma empresa sem nenhuma grade configurada faria a varredura percorrer o
# `antecedencia_max_dias` inteiro, um dia por consulta, para devolver lista vazia.
MAX_DIAS_VARREDURA = 45

# Teto de horários devolvidos numa consulta de um dia. Uma grade de 12 horas com
# passo de 15 min dá 48 horários: mandar isso para o WhatsApp é ilegível, e para
# o modelo de IA é token pago sem retorno.
MAX_HORARIOS_DIA = 40

# Grade que um recurso novo recebe: comercial, de segunda a sexta.
GRADE_PADRAO = [
    [{"inicio": "09:00", "fim": "12:00"}, {"inicio": "13:00", "fim": "18:00"}],
    [{"inicio": "09:00", "fim": "12:00"}, {"inicio": "13:00", "fim": "18:00"}],
    [{"inicio": "09:00", "fim": "12:00"}, {"inicio": "13:00", "fim": "18:00"}],
    [{"inicio": "09:00", "fim": "12:00"}, {"inicio": "13:00", "fim": "18:00"}],
    [{"inicio": "09:00", "fim": "12:00"}, {"inicio": "13:00", "fim": "18:00"}],
    [],
    [],
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    """Instante no formato que o resto do sistema grava e compara como string.

    Sem microssegundos de propósito: os horários da grade são minutos redondos,
    e a comparação lexicográfica entre `...:00+00:00` e `...:00.123456+00:00`
    funciona mas é uma armadilha desnecessária num campo que é ordenado no banco.
    """
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Fuso e conversão
# ---------------------------------------------------------------------------

def fuso_de(config: dict | None) -> ZoneInfo:
    nome = (config or {}).get("fuso") or FUSO_PADRAO
    try:
        return ZoneInfo(nome)
    except (ZoneInfoNotFoundError, ValueError):
        # Fuso inválido no banco não pode derrubar a agenda inteira: o efeito
        # visível seria a tela de horários vazia, sem explicação nenhuma.
        logger.warning("Fuso desconhecido em scheduling_settings: %r, usando %s",
                       nome, FUSO_PADRAO)
        return ZoneInfo(FUSO_PADRAO)


def _hhmm(valor) -> time:
    try:
        h, m = str(valor).split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Horário inválido: {valor!r} (use HH:MM)")


def _dia(valor) -> date:
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Data inválida: {valor!r} (use AAAA-MM-DD)")


def local(iso_utc: str, tz: ZoneInfo) -> datetime:
    """O instante gravado, visto no fuso da empresa."""
    return datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00")).astimezone(tz)


def _combina(d: date, hhmm: time, tz: ZoneInfo) -> datetime:
    """Hora de parede daquele dia, no fuso da empresa.

    Numa virada de horário de verão a hora pode não existir (ou existir duas
    vezes); o `zoneinfo` resolve escolhendo uma delas. É o comportamento certo
    aqui: recusar a grade inteira uma vez por ano seria pior que deslocar um
    horário em sessenta minutos num único dia.
    """
    return datetime.combine(d, hhmm, tzinfo=tz)


def rotulo(iso_utc: str, tz: ZoneInfo) -> str:
    """26/08 às 14:30, como o horário aparece para o contato no WhatsApp."""
    dt = local(iso_utc, tz)
    return f"{dt.day:02d}/{dt.month:02d} às {dt.hour:02d}:{dt.minute:02d}"


def rotulo_completo(iso_utc: str, tz: ZoneInfo) -> str:
    dt = local(iso_utc, tz)
    return (f"{DIAS[dt.weekday()]}, {dt.day:02d}/{dt.month:02d}/{dt.year} "
            f"às {dt.hour:02d}:{dt.minute:02d}")


# ---------------------------------------------------------------------------
# Configuração da empresa
# ---------------------------------------------------------------------------

async def configuracao(db, tenant_id: str) -> dict:
    """As preferências de agendamento da empresa, com os padrões preenchidos.

    Empresa que nunca abriu a tela não tem documento, e devolver `None` faria
    cada chamador inventar o próprio default. Aqui ela recebe os padrões sem
    que nada seja gravado.
    """
    doc = await db.scheduling_settings.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
    saida = {"tenant_id": tenant_id, **PADROES,
             **{k: v for k, v in doc.items() if v is not None}}
    saida["bloqueios"] = doc.get("bloqueios") or []
    return saida


def bloqueado(config: dict, d: date) -> str | None:
    """Feriado ou fechamento que vale para a empresa toda. Devolve o motivo."""
    alvo = d.isoformat()
    for b in config.get("bloqueios") or []:
        if (b.get("data") or "")[:10] == alvo:
            return b.get("motivo") or "Fechado"
    return None


# ---------------------------------------------------------------------------
# Grade do recurso
# ---------------------------------------------------------------------------

def janelas_do_dia(recurso: dict, d: date, config: dict) -> list[dict]:
    """Os intervalos em que este profissional atende naquele dia.

    Ordem de precedência: bloqueio da empresa (feriado) derruba tudo; exceção do
    recurso (folga ou horário especial) ganha da grade semanal; sem nenhuma das
    duas, vale a grade.
    """
    if bloqueado(config, d):
        return []

    alvo = d.isoformat()
    for e in recurso.get("excecoes") or []:
        if (e.get("data") or "")[:10] != alvo:
            continue
        if e.get("fechado", True):
            return []
        return _normaliza_janelas(e.get("janelas") or [])

    grade = recurso.get("grade") or []
    if len(grade) != 7:
        return []
    return _normaliza_janelas(grade[d.weekday()] or [])


def _normaliza_janelas(janelas: list) -> list[dict]:
    """Descarta janela invertida ou vazia e devolve em ordem.

    Janela com fim <= início é erro de digitação (`18:00` às `08:00`), e deixá-la
    passar produziria um laço que nunca gera horário nenhum: sintoma idêntico
    ao de "não configurei a grade", que manda o suporte procurar no lugar errado.
    """
    saida = []
    for j in janelas:
        try:
            ini, fim = _hhmm(j.get("inicio")), _hhmm(j.get("fim"))
        except HTTPException:
            continue
        if fim > ini:
            saida.append({"inicio": ini, "fim": fim})
    return sorted(saida, key=lambda j: j["inicio"])


def validar_grade(grade) -> list:
    """A grade como ela vai para o banco: 7 dias, horários em HH:MM, sem inversão."""
    if not isinstance(grade, list) or len(grade) != 7:
        raise HTTPException(status_code=400,
                            detail="A grade precisa ter os 7 dias da semana")
    saida = []
    for i, dia in enumerate(grade):
        limpo = []
        for j in (dia or []):
            ini, fim = _hhmm(j.get("inicio")), _hhmm(j.get("fim"))
            if fim <= ini:
                raise HTTPException(
                    status_code=400,
                    detail=f"{DIAS[i]}: o fim ({j.get('fim')}) não pode vir "
                           f"antes do início ({j.get('inicio')})")
            limpo.append({"inicio": f"{ini.hour:02d}:{ini.minute:02d}",
                          "fim": f"{fim.hour:02d}:{fim.minute:02d}"})
        limpo.sort(key=lambda x: x["inicio"])
        # Janelas encavaladas no mesmo dia gerariam o mesmo horário duas vezes na
        # lista que o contato recebe.
        for a, b in zip(limpo, limpo[1:]):
            if b["inicio"] < a["fim"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"{DIAS[i]}: os intervalos {a['inicio']}-{a['fim']} e "
                           f"{b['inicio']}-{b['fim']} se sobrepõem")
        saida.append(limpo)
    return saida


# ---------------------------------------------------------------------------
# Ocupação
# ---------------------------------------------------------------------------

async def ocupacao(db, tenant_id: str, recurso_ids: list,
                   de_iso: str, ate_iso: str) -> dict:
    """O que já está marcado na janela, por recurso.

    Uma consulta para todos os recursos de uma vez, não uma por profissional: a
    tela da agenda mostra a semana inteira de uma equipe, e o custo aqui é a ida
    e volta pelo túnel, não o volume. Mesma razão de
    `atividades.negocios_sem_proximo_passo`.

    O filtro é `fim > de` **e** `inicio < ate`, não `inicio` dentro da janela: um
    atendimento de duas horas que começou às 17h do dia anterior ocupa a primeira
    hora deste dia, e procurar só pelo início o deixaria invisível.
    """
    if not recurso_ids:
        return {}
    cursor = db.appointments.find(
        {"tenant_id": tenant_id, "resource_id": {"$in": list(recurso_ids)},
         "status": {"$in": list(OCUPAM)},
         "fim": {"$gt": de_iso}, "inicio": {"$lt": ate_iso}},
        {"_id": 0, "resource_id": 1, "inicio": 1, "fim": 1},
    )
    por_recurso = {r: [] for r in recurso_ids}
    async for a in cursor:
        por_recurso.setdefault(a["resource_id"], []).append((a["inicio"], a["fim"]))
    return por_recurso


def _colide(ini: datetime, fim: datetime, ocupados: list,
            folga: timedelta) -> bool:
    """Este intervalo esbarra em algo já marcado, contando a folga entre eles.

    A folga estica o candidato **dos dois lados**, e não só o fim. Esticar um
    lado só cobre o atendimento que vem depois e deixa passar o que vem antes:
    com um corte marcado das 10h às 10h30 e 15 min de folga, as 10h30 ficariam
    livres, que é exatamente o encavalamento que a folga existe para impedir.
    Comparar contra os intervalos guardados como estão (em vez de esticá-los
    também) evita reconstruir datetime a partir do texto para cada um deles.
    """
    a_ini, a_fim = _iso(ini - folga), _iso(fim + folga)
    for o_ini, o_fim in ocupados:
        if a_ini < o_fim and o_ini < a_fim:
            return True
    return False


# Quanto a busca de ocupação estende a janela do dia, para os dois lados. É o
# teto do intervalo configurável (240 min): sem essa margem, um atendimento que
# terminou na véspera não seria lido, e a folga que ele projeta sobre a
# madrugada seguinte sumiria, só morde quem atende de madrugada, que é
# justamente quem não teria como descobrir o problema.
MARGEM_OCUPACAO = timedelta(hours=4)


# ---------------------------------------------------------------------------
# Horários livres
# ---------------------------------------------------------------------------

def _folga(recurso: dict, config: dict) -> timedelta:
    v = recurso.get("intervalo_min")
    if v is None:
        v = config.get("intervalo_min") or 0
    return timedelta(minutes=max(0, int(v)))


async def horarios_livres(db, tenant_id: str, *, recurso: dict, servico: dict,
                          dia: str, config: dict, agora: datetime = None,
                          ocupados: list = None) -> list:
    """Os horários em que este profissional pode atender este serviço neste dia.

    `ocupados` pode vir pronto de `ocupacao()` quando o chamador já varreu vários
    dias ou vários recursos de uma vez: é o que evita uma consulta por dia numa
    tela de semana.
    """
    tz = fuso_de(config)
    d = _dia(dia)
    janelas = janelas_do_dia(recurso, d, config)
    if not janelas:
        return []

    duracao = timedelta(minutes=int(servico.get("duracao_min") or 30))
    passo = timedelta(minutes=max(5, int(config.get("passo_min") or 30)))
    folga = _folga(recurso, config)
    agora = agora or _agora()
    piso = agora + timedelta(hours=float(config.get("antecedencia_min_horas") or 0))
    teto = agora + timedelta(days=int(config.get("antecedencia_max_dias") or 365))

    if ocupados is None:
        inicio_dia = _combina(d, time(0, 0), tz)
        mapa = await ocupacao(db, tenant_id, [recurso["id"]],
                              _iso(inicio_dia - MARGEM_OCUPACAO),
                              _iso(inicio_dia + timedelta(days=1) + MARGEM_OCUPACAO))
        ocupados = mapa.get(recurso["id"], [])

    livres = []
    for j in janelas:
        cursor = _combina(d, j["inicio"], tz)
        fim_janela = _combina(d, j["fim"], tz)
        while cursor + duracao <= fim_janela:
            fim = cursor + duracao
            if piso <= cursor <= teto and not _colide(cursor, fim, ocupados, folga):
                hora_local = cursor.astimezone(tz)
                livres.append({
                    "inicio": _iso(cursor),
                    "fim": _iso(fim),
                    "hora": f"{hora_local.hour:02d}:{hora_local.minute:02d}",
                    "resource_id": recurso["id"],
                    "resource_nome": recurso.get("nome"),
                })
                if len(livres) >= MAX_HORARIOS_DIA:
                    return livres
            cursor += passo
    return livres


async def horarios_do_dia(db, tenant_id: str, *, recursos: list, servico: dict,
                          dia: str, config: dict, agora: datetime = None) -> list:
    """Os horários livres do dia somando a equipe inteira, sem repetir a hora.

    Quando o contato não escolheu profissional, 14h aparece **uma vez**, já
    apontando para quem vai atender. Mostrar "14h com a Ana / 14h com o Bruno /
    14h com a Carla" transforma uma pergunta simples numa lista ilegível, e a
    escolha de quem atende, quando o contato não fez questão, é da empresa.

    Quem aparece é o primeiro da lista com aquele horário livre; a lista chega
    ordenada por nome, então a distribuição é estável e previsível para quem
    olha a agenda depois.
    """
    if not recursos:
        return []
    tz = fuso_de(config)
    d = _dia(dia)
    inicio_dia = _combina(d, time(0, 0), tz)
    mapa = await ocupacao(db, tenant_id, [r["id"] for r in recursos],
                          _iso(inicio_dia - MARGEM_OCUPACAO),
                          _iso(inicio_dia + timedelta(days=1) + MARGEM_OCUPACAO))

    por_hora = {}
    for r in recursos:
        for h in await horarios_livres(db, tenant_id, recurso=r, servico=servico,
                                       dia=dia, config=config, agora=agora,
                                       ocupados=mapa.get(r["id"], [])):
            por_hora.setdefault(h["inicio"], h)
    return [por_hora[k] for k in sorted(por_hora)][:MAX_HORARIOS_DIA]


async def proximos_dias(db, tenant_id: str, *, recursos: list, servico: dict,
                        config: dict, a_partir_de: str = None,
                        limite_dias: int = 7, agora: datetime = None) -> list:
    """Os próximos dias que têm pelo menos um horário livre.

    É a primeira pergunta de qualquer agendamento por conversa ("que dia?"), e
    oferecer um dia sem vaga é o jeito mais rápido de fazer o contato desistir:
    ele escolhe, não tem nada, e volta para o começo.

    Varre no máximo `MAX_DIAS_VARREDURA` dias e para assim que junta
    `limite_dias`: uma empresa que atende só às terças gastaria a varredura
    inteira se o corte fosse só pelo teto.
    """
    if not recursos:
        return []
    tz = fuso_de(config)
    agora = agora or _agora()
    inicio = _dia(a_partir_de) if a_partir_de else agora.astimezone(tz).date()
    teto_dias = min(MAX_DIAS_VARREDURA, int(config.get("antecedencia_max_dias") or 60))

    saida = []
    for n in range(teto_dias + 1):
        d = inicio + timedelta(days=n)
        horarios = await horarios_do_dia(db, tenant_id, recursos=recursos,
                                         servico=servico, dia=d.isoformat(),
                                         config=config, agora=agora)
        if horarios:
            saida.append({
                "dia": d.isoformat(),
                "rotulo": f"{DIAS[d.weekday()]} {d.day:02d}/{d.month:02d}",
                "vagas": len(horarios),
                "primeiro": horarios[0]["inicio"],
            })
            if len(saida) >= limite_dias:
                break
    return saida


# ---------------------------------------------------------------------------
# Catálogo (serviços e profissionais)
# ---------------------------------------------------------------------------

async def servicos_ativos(db, tenant_id: str) -> list:
    return await db.services.find(
        {"tenant_id": tenant_id, "ativo": True}, {"_id": 0}
    ).sort([("ordem", 1), ("nome", 1)]).to_list(200)


async def recursos_ativos(db, tenant_id: str, servico: dict = None) -> list:
    """Quem pode atender. Com o serviço informado, só quem atende aquele serviço.

    `servico.recursos` vazio significa "todos": é o padrão, pelo mesmo motivo
    que `ai_agents.agente_da_conexao` trata `conexoes` vazio como todas: criar um
    profissional novo não pode deixá-lo silenciosamente fora de todos os serviços.
    """
    recursos = await db.resources.find(
        {"tenant_id": tenant_id, "ativo": True}, {"_id": 0}
    ).sort("nome", 1).to_list(200)
    permitidos = set((servico or {}).get("recursos") or [])
    if permitidos:
        recursos = [r for r in recursos if r["id"] in permitidos]
    return recursos


# ---------------------------------------------------------------------------
# Marcação
# ---------------------------------------------------------------------------

def _instante(valor, rotulo_campo: str = "Horário") -> datetime:
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{rotulo_campo} inválido: {valor!r}")
    if dt.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail=f"{rotulo_campo} sem fuso. Informe o instante completo "
                   "(ex.: 2026-09-01T14:00:00-03:00)")
    return dt.astimezone(timezone.utc).replace(microsecond=0)


async def _conflitos(db, tenant_id: str, resource_id: str, ini: datetime,
                     fim: datetime, folga: timedelta, exceto: str) -> list:
    cursor = db.appointments.find(
        {"tenant_id": tenant_id, "resource_id": resource_id,
         "status": {"$in": list(OCUPAM)},
         # A folga vale dos dois lados, como em `_colide`: sem o `- folga` no
         # início, um encaixe colado no fim do atendimento anterior passaria
         # pela reconferência mesmo violando o intervalo configurado.
         "fim": {"$gt": _iso(ini - folga)}, "inicio": {"$lt": _iso(fim + folga)}},
        {"_id": 0, "id": 1, "inicio": 1, "fim": 1},
    )
    return [a async for a in cursor if a["id"] != exceto]


def _ocupado(tz, ini, recurso) -> str:
    return (f"{rotulo_completo(_iso(ini), tz)} já está ocupado na agenda de "
            f"{recurso.get('nome')}. Escolha outro horário.")


def _dentro_da_grade(recurso: dict, ini: datetime, fim: datetime,
                     config: dict, tz: ZoneInfo) -> bool:
    """O atendimento inteiro cabe numa janela de atendimento daquele dia.

    Confere o dia do **início** em hora local: um atendimento que atravessasse a
    meia-noite não caberia em janela nenhuma e seria recusado, que é o
    comportamento certo, quem trabalha virando o dia configura duas janelas.
    """
    ini_local, fim_local = ini.astimezone(tz), fim.astimezone(tz)
    for j in janelas_do_dia(recurso, ini_local.date(), config):
        abre = _combina(ini_local.date(), j["inicio"], tz)
        fecha = _combina(ini_local.date(), j["fim"], tz)
        if abre <= ini_local and fim_local <= fecha:
            return True
    return False


async def agendar(db, tenant_id: str, *, recurso: dict, servico: dict, contato: dict,
                  inicio: str, config: dict, origem: str = "manual",
                  criado_por: str = None, session_id: str = None,
                  connection_id: str = None, observacoes: str = None,
                  forcar: bool = False, agora: datetime = None) -> dict:
    """Reserva o horário. Levanta 409 se ele não estiver (ou não continuar) livre.

    `forcar` é o encaixe feito à mão na tela: dispensa a grade e a antecedência
    mínima, porque quem está olhando a agenda sabe que vai atender fora do
    expediente. **Não** dispensa a checagem de sobreposição: encaixar alguém em
    cima de outro atendimento nunca é intenção, é engano.
    """
    if origem not in ORIGENS:
        raise HTTPException(status_code=400, detail=f"Origem desconhecida: {origem}")
    if not recurso.get("ativo", True):
        raise HTTPException(status_code=400,
                            detail=f"{recurso.get('nome')} não está disponível para agendamento")
    if not servico.get("ativo", True):
        raise HTTPException(status_code=400,
                            detail=f"O serviço {servico.get('nome')} está desativado")

    agora = agora or _agora()
    ini = _instante(inicio)
    duracao = int(servico.get("duracao_min") or 30)
    fim = ini + timedelta(minutes=duracao)
    tz = fuso_de(config)
    folga = _folga(recurso, config)

    if not forcar:
        piso = agora + timedelta(hours=float(config.get("antecedencia_min_horas") or 0))
        if ini < piso:
            raise HTTPException(
                status_code=400,
                detail=f"É preciso marcar com pelo menos "
                       f"{config.get('antecedencia_min_horas')}h de antecedência")
        teto = agora + timedelta(days=int(config.get("antecedencia_max_dias") or 365))
        if ini > teto:
            raise HTTPException(
                status_code=400,
                detail=f"A agenda só vai até {config.get('antecedencia_max_dias')} "
                       "dias à frente")
        if not _dentro_da_grade(recurso, ini, fim, config, tz):
            raise HTTPException(
                status_code=409,
                detail=f"{rotulo_completo(_iso(ini), tz)} está fora do horário de "
                       f"atendimento de {recurso.get('nome')}")

    if await _conflitos(db, tenant_id, recurso["id"], ini, fim, folga, exceto=""):
        raise HTTPException(status_code=409, detail=_ocupado(tz, ini, recurso))

    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "resource_id": recurso["id"],
        "resource_nome": recurso.get("nome"),
        "service_id": servico["id"],
        "service_nome": servico.get("nome"),
        "contact_id": contato["id"],
        "contact_nome": contato.get("nome"),
        "contact_numero": contato.get("numero_whatsapp"),
        "inicio": _iso(ini),
        "fim": _iso(fim),
        "duracao_min": duracao,
        "preco": servico.get("preco"),
        "status": STATUS_AGENDADO,
        "origem": origem,
        "observacoes": (observacoes or "").strip() or None,
        "session_id": session_id,
        "whatsapp_connection_id": connection_id,
        "criado_por": criado_por,
        "confirmado_em": None,
        "cancelado_em": None,
        "cancelado_por": None,
        "motivo_cancelamento": None,
        "lembrete_enviado_em": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.appointments.insert_one(dict(doc))
    doc.pop("_id", None)

    # A reconferência. Ver o cabeçalho do módulo: quem enxerga conflito recua,
    # sem desempate. Duas conversas que gravem no mesmo instante recuam as duas e
    # ninguém fica com o horário, o que se recusa a aceitar é a outra ponta,
    # duas pessoas marcadas com o mesmo profissional às 14h.
    if await _conflitos(db, tenant_id, recurso["id"], ini, fim, folga, exceto=doc["id"]):
        await db.appointments.delete_one({"id": doc["id"], "tenant_id": tenant_id})
        raise HTTPException(status_code=409, detail=_ocupado(tz, ini, recurso))

    return doc


async def cancelar(db, tenant_id: str, appointment_id: str, *, por: str = None,
                   motivo: str = None) -> dict:
    """Libera o horário sem apagar o registro.

    O horário volta a aparecer como livre porque a consulta de ocupação filtra
    por status. O documento fica: é dele que sai a taxa de cancelamento, o motivo
    e o histórico do contato, e um `delete_one` os levaria junto.
    """
    doc = await db.appointments.find_one(
        {"id": appointment_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    if doc["status"] == STATUS_CANCELADO:
        return doc
    if doc["status"] in (STATUS_CONCLUIDO, STATUS_FALTOU):
        raise HTTPException(status_code=409,
                            detail="Esse atendimento já aconteceu e não pode ser cancelado")
    campos = {"status": STATUS_CANCELADO, "cancelado_em": _now(), "cancelado_por": por,
              "motivo_cancelamento": (motivo or "").strip() or None, "updated_at": _now()}
    await db.appointments.update_one(
        {"id": appointment_id, "tenant_id": tenant_id}, {"$set": campos})
    doc.update(campos)
    return doc


async def mudar_status(db, tenant_id: str, appointment_id: str, status: str) -> dict:
    if status not in STATUS:
        raise HTTPException(status_code=400, detail=f"Status desconhecido: {status}")
    if status == STATUS_CANCELADO:
        return await cancelar(db, tenant_id, appointment_id)
    doc = await db.appointments.find_one(
        {"id": appointment_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    campos = {"status": status, "updated_at": _now()}
    if status == STATUS_CONFIRMADO and not doc.get("confirmado_em"):
        campos["confirmado_em"] = _now()
    await db.appointments.update_one(
        {"id": appointment_id, "tenant_id": tenant_id}, {"$set": campos})
    doc.update(campos)
    return doc


async def agendamentos_do_contato(db, tenant_id: str, contact_id: str, *,
                                  futuros: bool = True, limite: int = 20) -> list:
    filtro = {"tenant_id": tenant_id, "contact_id": contact_id}
    if futuros:
        filtro["inicio"] = {"$gte": _iso(_agora())}
        filtro["status"] = {"$in": [STATUS_AGENDADO, STATUS_CONFIRMADO]}
    return await db.appointments.find(filtro, {"_id": 0}) \
        .sort([("inicio", 1 if futuros else -1), ("_id", 1)]).to_list(limite)
