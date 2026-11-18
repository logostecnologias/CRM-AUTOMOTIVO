"""Conversões do funil devolvidas ao Meta (Conversions API).

O anúncio de "Clique para WhatsApp" otimiza, por padrão, para **conversa
iniciada**: o Meta procura gente que manda mensagem, não gente que compra. O
que muda isso é contar a ele o que aconteceu depois, e o único lugar do sistema
que sabe disso é o funil. Por isso cada etapa pode ter um evento do Meta
(`etapa.evento_meta`), e o negócio que entra nela dispara o evento.

Decisões que moldam o módulo:

  - **Um gatilho só: a mudança de etapa.** Ela já passa inteira por
    `deals.registrar_evento` (tela, agente de IA, formulário), então é ali que
    o envio é agendado. Pendurar o envio em cada rota deixaria uma delas de
    fora na primeira rota nova.

  - **O clique do anúncio manda no formato.** Contato que chegou por anúncio de
    WhatsApp tem `ctwa_clid` (vem no `referral` da primeira mensagem), e o
    evento sai como `business_messaging`, ligado ao clique: é a forma que o
    Meta usa para otimizar aquele anúncio. Sem o clique, sai como
    `system_generated` com telefone e e-mail em hash (e o `fbc` do formulário
    de site, quando houver): o Meta casa pela pessoa, e ainda serve para
    público semelhante e para a campanha que otimiza por lead de qualidade.

  - **Cada (negócio, evento) sai uma vez.** O `event_id` é fixo por negócio e
    evento, então o Meta deduplica, e o registro em `meta_eventos` impede o
    reenvio depois da janela de deduplicação dele. Arrastar o cartão de
    "Ganho" para trás e de volta não pode virar duas vendas no relatório do
    anunciante.

  - **Nunca atrapalha a venda.** O envio corre em tarefa própria e nunca
    levanta: o Meta fora do ar não pode impedir o cartão de mudar de coluna. A
    falha fica em `meta_eventos`, que é o que a tela mostra.

  - **Perdido não tem evento por padrão.** O Meta não tem sinal negativo que
    faça o leilão evitar um perfil; o que ensina a ele quem compra é o
    `Purchase` com valor. Quem quiser ainda pode marcar a etapa de perda com
    um evento (para montar público de exclusão), mas isso é escolha, não
    padrão.
"""
import asyncio
import hashlib
import logging
import re
import time
import uuid
from datetime import datetime, timezone

import cripto
import whatsapp_client as whatsapp

logger = logging.getLogger("zappzen.meta_conversoes")

# Eventos aceitos pela Conversions API para conversas de WhatsApp. Ficam numa
# lista fechada porque um nome fora dela é aceito pela API e simplesmente não
# entra na otimização — o pior tipo de erro, o que não aparece.
EVENTOS = {
    "LeadSubmitted": "Lead (novo contato)",
    "QualifiedLead": "Lead qualificado",
    "InitiateCheckout": "Proposta / checkout iniciado",
    "Purchase": "Compra (venda fechada)",
}

# Fora do canal de mensagens o nome padrão do lead é outro.
_NOME_FORA_DO_WHATSAPP = {"LeadSubmitted": "Lead"}

# Clique de anúncio vale por 7 dias para a atribuição do Meta; depois disso o
# evento ainda sai, mas casado pela pessoa e não pelo clique.
JANELA_CLIQUE_DIAS = 7

_tarefas: set[asyncio.Task] = set()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def evento_da_etapa(pipeline: dict, etapa: dict) -> str | None:
    """O evento que a etapa dispara.

    `evento_meta` gravado (mesmo vazio) é a escolha de quem configurou. Ausente
    é etapa de antes desta função, e aí vale o padrão: a primeira etapa é o
    lead, a de ganho é a compra. Assim a empresa que só liga a integração já
    ensina ao Meta o que importa, sem precisar abrir a configuração do funil.
    """
    if "evento_meta" in etapa:
        return etapa.get("evento_meta") or None
    if etapa.get("tipo") == "ganho":
        return "Purchase"
    primeira = min(pipeline.get("etapas") or [etapa], key=lambda e: e.get("ordem", 0))
    if etapa.get("tipo", "aberta") == "aberta" and primeira.get("id") == etapa.get("id"):
        return "LeadSubmitted"
    return None


def _clique_valido(anuncio: dict | None) -> bool:
    if not anuncio or not anuncio.get("ctwa_clid"):
        return False
    try:
        quando = datetime.fromisoformat(anuncio.get("em"))
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - quando).days < JANELA_CLIQUE_DIAS


def montar_evento(nome: str, deal: dict, contato: dict, resposta_form: dict | None,
                  teste: bool = False) -> dict:
    """O evento no formato da Conversions API. Função pura, para teste."""
    anuncio = contato.get("anuncio") or {}
    evento: dict = {
        "event_name": nome,
        "event_time": int(time.time()),
        "event_id": f"{deal['id']}:{nome}" if not teste else str(uuid.uuid4()),
    }
    if _clique_valido(anuncio) and anuncio.get("waba_id"):
        evento["action_source"] = "business_messaging"
        evento["messaging_channel"] = "whatsapp"
        evento["user_data"] = {
            "whatsapp_business_account_id": anuncio["waba_id"],
            "ctwa_clid": anuncio["ctwa_clid"],
        }
    else:
        evento["event_name"] = _NOME_FORA_DO_WHATSAPP.get(nome, nome)
        evento["action_source"] = "system_generated"
        user: dict = {"external_id": [_hash(contato["id"])]}
        digitos = re.sub(r"\D", "", contato.get("numero_whatsapp") or "")
        if digitos:
            user["ph"] = [_hash(digitos)]
        email = (contato.get("email") or "").strip().lower()
        if email:
            user["em"] = [_hash(email)]
        fbclid = ((resposta_form or {}).get("clique") or {}).get("fbclid")
        if fbclid:
            try:
                ms = int(datetime.fromisoformat(resposta_form["created_at"]).timestamp() * 1000)
            except (KeyError, TypeError, ValueError):
                ms = int(time.time() * 1000)
            user["fbc"] = f"fb.1.{ms}.{fbclid}"
        evento["user_data"] = user

    valor = float(deal.get("valor") or 0)
    if nome == "Purchase" or valor > 0:
        evento["custom_data"] = {"currency": "BRL", "value": round(valor, 2)}
    return evento


async def _token(db, tenant_id: str, config: dict) -> str | None:
    """Token próprio da integração ou, sem ele, o da conexão de WhatsApp.

    O token do WhatsApp só funciona se tiver a permissão de eventos
    (`whatsapp_business_manage_events`); quando não tem, o Meta recusa e o
    erro aparece no registro de envios, dizendo exatamente isso.
    """
    if config.get("token"):
        try:
            return cripto.decifrar(config["token"])
        except Exception as e:
            logger.error("Token da Conversions API ilegível (empresa %s): %s", tenant_id, e)
            return None
    async for conn in db.whatsapp_connections.find(
            {"tenant_id": tenant_id, "waba_id": {"$ne": None}}, {"_id": 0}):
        cred = whatsapp.credencial(conn)
        if cred and cred.canal == whatsapp.CANAL_CLOUD:
            return cred.token
    return None


async def enviar(db, tenant_id: str, config: dict, eventos: list[dict]) -> dict:
    token = await _token(db, tenant_id, config)
    if not token:
        raise whatsapp.WhatsAppError("Sem token para a Conversions API")
    corpo: dict = {"data": eventos}
    if config.get("test_event_code"):
        corpo["test_event_code"] = config["test_event_code"]
    return await whatsapp._request("POST", f"/{config['dataset_id']}/events", token,
                                   json=corpo, repetivel=True)


async def ao_mudar_etapa(db, tenant_id: str, deal_id: str) -> None:
    """Dispara o evento da etapa em que o negócio está agora. Nunca levanta."""
    try:
        config = await db.meta_conversoes.find_one({"tenant_id": tenant_id}, {"_id": 0})
        if not config or not config.get("ativo") or not config.get("dataset_id"):
            return
        deal = await db.deals.find_one({"id": deal_id, "tenant_id": tenant_id}, {"_id": 0})
        if not deal:
            return
        pipeline = await db.pipelines.find_one(
            {"id": deal["pipeline_id"], "tenant_id": tenant_id}, {"_id": 0})
        etapa = next((e for e in (pipeline or {}).get("etapas") or []
                      if e["id"] == deal.get("etapa_id")), None)
        if not etapa:
            return
        nome = evento_da_etapa(pipeline, etapa)
        if not nome:
            return
        if await db.meta_eventos.find_one(
                {"tenant_id": tenant_id, "deal_id": deal_id, "evento": nome, "status": "enviado"},
                {"_id": 0, "id": 1}):
            return
        contato = await db.contacts.find_one(
            {"id": deal["contact_id"], "tenant_id": tenant_id}, {"_id": 0})
        if not contato:
            return
        resposta_form = None
        if deal.get("formulario_resposta_id"):
            resposta_form = await db.formulario_respostas.find_one(
                {"id": deal["formulario_resposta_id"], "tenant_id": tenant_id},
                {"_id": 0, "clique": 1, "created_at": 1})

        evento = montar_evento(nome, deal, contato, resposta_form)
        registro = {
            "id": str(uuid.uuid4()), "tenant_id": tenant_id, "deal_id": deal_id,
            "contact_id": contato["id"], "evento": nome, "etapa": etapa.get("nome"),
            "canal": evento["action_source"], "valor": deal.get("valor") or 0,
            "teste": bool(config.get("test_event_code")), "created_at": _now(),
        }
        try:
            await enviar(db, tenant_id, config, [evento])
            registro["status"] = "enviado"
        except Exception as e:
            registro["status"] = "erro"
            registro["erro"] = str(e)[:300]
            logger.warning("Conversions API recusou %s do negócio %s: %s", nome, deal_id, e)
        await db.meta_eventos.insert_one(registro)
    except Exception as e:
        logger.exception("Falha ao preparar evento do Meta para o negócio %s: %s", deal_id, e)


def agendar(db, tenant_id: str, deal_id: str) -> None:
    """Agenda o envio fora do caminho de quem moveu o negócio."""
    try:
        tarefa = asyncio.get_running_loop().create_task(ao_mudar_etapa(db, tenant_id, deal_id))
    except RuntimeError:
        return
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)


async def aguardar_pendentes() -> None:
    """Para testes: espera os envios agendados terminarem."""
    while _tarefas:
        await asyncio.gather(*list(_tarefas), return_exceptions=True)


def anuncio_do_referral(referral: dict | None, waba_id: str | None) -> dict | None:
    """O anúncio de origem, a partir do `referral` da mensagem recebida.

    Só vale o que veio de anúncio (`source_type` "ad"); um `referral` de post
    orgânico não tem clique para atribuir.
    """
    if not referral or not referral.get("ctwa_clid"):
        return None
    return {
        "ctwa_clid": str(referral["ctwa_clid"])[:500],
        "source_id": referral.get("source_id"),
        "source_type": referral.get("source_type"),
        "source_url": referral.get("source_url"),
        "titulo": (referral.get("headline") or "")[:200] or None,
        "waba_id": waba_id,
        "em": _now(),
    }
