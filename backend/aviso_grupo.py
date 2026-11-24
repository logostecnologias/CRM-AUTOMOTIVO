"""Aviso no grupo de WhatsApp da equipe quando um negócio entra numa etapa.

Nasceu do Atalaia (24/11/2026): a equipe da loja vive num grupo de WhatsApp, e
quem marca a visita é quase sempre o agente de IA, de madrugada ou no meio de
outra conversa. Sem aviso, a visita de terça às 10h só era descoberta abrindo
o funil. Agora, quando um negócio entra numa etapa escolhida ("Visita
agendada"), sai uma mensagem no grupo com cliente, carro, valor e horário.

- **O gatilho é `deals.registrar_evento`**, o mesmo da Conversions API: todo
  caminho que muda etapa (tela, agente de IA, formulário, botão da Central)
  passa por ali depois de gravar. Um gatilho por caminho esqueceria algum.
- **É mensagem do sistema, não a IA conversando no grupo.** Uma IA lendo e
  respondendo o grupo da equipe gastaria a cada mensagem dos vendedores para
  entregar o que um texto montado entrega.
- **Só no canal WuzAPI**: a Cloud API não envia para grupo comum. O número da
  conexão precisa ser membro do grupo, e entrar é pelo link de convite.
- **Nunca levanta**, como o envio ao Meta: o aviso falhar não pode impedir o
  negócio de andar. O último erro fica gravado na configuração, e a tela de
  Ajustes mostra.
- Uma vez por (negócio, etapa): o agente que chama a ferramenta de novo com a
  mesma etapa não muda nada, mas um negócio que volta e entra outra vez na
  etapa avisaria duas vezes a mesma visita. `avisados` guarda o par.
"""
import asyncio
import logging
from datetime import datetime, timezone

import agenda
import whatsapp_client as whatsapp

logger = logging.getLogger(__name__)

_tarefas: set = set()
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _now():
    return datetime.now(timezone.utc).isoformat()


async def configuracao(db, tenant_id: str) -> dict:
    doc = await db.avisos_grupo.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
    return {
        "ativo": bool(doc.get("ativo")),
        "connection_id": doc.get("connection_id"),
        "grupo_jid": doc.get("grupo_jid"),
        "grupo_nome": doc.get("grupo_nome"),
        "etapas": doc.get("etapas") or [],
        "ultimo_envio": doc.get("ultimo_envio"),
        "ultimo_erro": doc.get("ultimo_erro"),
    }


def _reais(n) -> str:
    return "R$ " + f"{float(n or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _telefone(numero: str) -> str:
    d = "".join(c for c in (numero or "") if c.isdigit())
    if d.startswith("55") and len(d) in (12, 13):
        local = d[4:]
        return f"({d[2:4]}) {local[:-4]}-{local[-4:]}"
    return d


async def _quando(db, tenant_id: str, contato_id: str) -> str | None:
    """O próximo horário marcado do contato na Agenda, no fuso da empresa."""
    if not contato_id:
        return None
    ag = await db.appointments.find({
        "tenant_id": tenant_id, "contact_id": contato_id,
        "status": {"$in": list(agenda.OCUPAM)}, "inicio": {"$gte": _now()},
    }, {"_id": 0, "inicio": 1}).sort("inicio", 1).limit(1).to_list(1)
    if not ag:
        return None
    tz = agenda.fuso_de(await agenda.configuracao(db, tenant_id))
    dt = agenda.local(ag[0]["inicio"], tz)
    return f"{DIAS[dt.weekday()]}, {dt:%d/%m} às {dt:%H:%M}"


async def montar(db, deal: dict, etapa_nome: str, autor_nome: str | None) -> str:
    tenant_id = deal["tenant_id"]
    contato = await db.contacts.find_one(
        {"id": deal.get("contact_id"), "tenant_id": tenant_id},
        {"_id": 0, "nome": 1, "numero_whatsapp": 1}) or {}
    linhas = [f"📅 *{etapa_nome}*"]
    nome = contato.get("nome") or ""
    tel = _telefone(contato.get("numero_whatsapp"))
    if nome and nome != contato.get("numero_whatsapp"):
        linhas.append(f"Cliente: {nome}" + (f" · {tel}" if tel else ""))
    elif tel:
        linhas.append(f"Cliente: {tel}")
    carro = deal.get("titulo") or ""
    if deal.get("valor"):
        carro = f"{carro} · {_reais(deal['valor'])}" if carro else _reais(deal["valor"])
    if carro:
        linhas.append(f"Negócio: {carro}")
    quando = await _quando(db, tenant_id, deal.get("contact_id"))
    if quando:
        linhas.append(f"Quando: {quando}")
    if deal.get("responsavel_id"):
        r = await db.users.find_one({"id": deal["responsavel_id"], "tenant_id": tenant_id},
                                    {"_id": 0, "name": 1})
        if r and r.get("name"):
            linhas.append(f"Responsável: {r['name']}")
    if autor_nome:
        linhas.append(f"Registrado por: {autor_nome}")
    return "\n".join(linhas)


async def enviar(db, tenant_id: str, cfg: dict, texto: str) -> None:
    """Manda ao grupo configurado. Levanta: quem chama decide o que fazer."""
    conn = await db.whatsapp_connections.find_one(
        {"id": cfg.get("connection_id"), "tenant_id": tenant_id}, {"_id": 0})
    if not conn or conn.get("canal") != whatsapp.CANAL_WUZAPI:
        raise RuntimeError("A conexão escolhida não existe mais ou não é do canal WuzAPI")
    cred = whatsapp.credencial(conn)
    if not cred:
        raise RuntimeError("A conexão escolhida não está pareada")
    if not cfg.get("grupo_jid"):
        raise RuntimeError("Nenhum grupo escolhido")
    await whatsapp.send_text(cred, cfg["grupo_jid"], texto)


async def ao_entrar_na_etapa(db, deal_id: str, tenant_id: str, autor_nome: str | None) -> None:
    try:
        cfg = await configuracao(db, tenant_id)
        if not cfg["ativo"] or not cfg["grupo_jid"]:
            return
        deal = await db.deals.find_one({"id": deal_id, "tenant_id": tenant_id}, {"_id": 0})
        if not deal or deal.get("etapa_id") not in cfg["etapas"]:
            return
        chave = f"{deal_id}:{deal['etapa_id']}"
        # Claim atômico: dois eventos do mesmo movimento (ou duas tarefas) não
        # mandam o mesmo aviso duas vezes.
        r = await db.avisos_grupo.update_one(
            {"tenant_id": tenant_id, "avisados": {"$ne": chave}},
            {"$push": {"avisados": chave}})
        if not r.modified_count:
            return
        funil = await db.pipelines.find_one(
            {"id": deal.get("pipeline_id"), "tenant_id": tenant_id}, {"_id": 0, "etapas": 1}) or {}
        etapa = next((e for e in funil.get("etapas") or [] if e["id"] == deal["etapa_id"]), {})
        texto = await montar(db, deal, etapa.get("nome") or "Negócio atualizado", autor_nome)
        try:
            await enviar(db, tenant_id, cfg, texto)
            await db.avisos_grupo.update_one({"tenant_id": tenant_id},
                                             {"$set": {"ultimo_envio": _now(), "ultimo_erro": None}})
        except Exception as e:
            logger.warning("Aviso no grupo falhou (empresa %s): %s", tenant_id, e)
            await db.avisos_grupo.update_one(
                {"tenant_id": tenant_id},
                {"$set": {"ultimo_erro": f"{_now()[:16].replace('T', ' ')} · {str(e)[:300]}"},
                 "$pull": {"avisados": chave}})
    except Exception as e:
        logger.exception("Falha ao preparar aviso no grupo do negócio %s: %s", deal_id, e)


def agendar(db, deal: dict, autor: dict | None) -> None:
    """Fora do caminho de quem moveu o negócio, como `meta_conversoes.agendar`."""
    try:
        tarefa = asyncio.get_running_loop().create_task(ao_entrar_na_etapa(
            db, deal["id"], deal["tenant_id"],
            (autor or {}).get("name") or (autor or {}).get("email")))
    except RuntimeError:
        return
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)


async def aguardar_pendentes() -> None:
    """Para testes."""
    while _tarefas:
        await asyncio.gather(*list(_tarefas), return_exceptions=True)
