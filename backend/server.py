from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
from fastapi import FastAPI, Response
from pymongo.errors import OperationFailure
from starlette.middleware.cors import CORSMiddleware

from db import get_db, close_db
from auth import router as auth_router, seed_super_admin
from routes.tenants import router as tenants_router
from routes.bots import router as bots_router
from routes.flows import router as flows_router
from routes.contacts import router as contacts_router
from routes.whatsapp import router as whatsapp_router
from routes.dashboard import router as dashboard_router
from routes.webhooks import router as webhooks_router
from routes.webhooks_wuzapi import router as webhooks_wuzapi_router
from routes.departments import router as departments_router
from routes.users import router as users_router
from routes.atendimento import router as atendimento_router
from routes.plans import router as plans_router
from routes.media import router as media_router
from routes.campaigns import router as campaigns_router
from routes.deals import router as deals_router
from routes.activities import router as activities_router
from routes.reports import router as reports_router
from routes.ai import router as ai_router
from routes.settings import router as settings_router
from routes.scheduling import router as scheduling_router
from routes.voz import router as voz_router
from routes.formularios import router as formularios_router
from routes.meta_conversoes import router as meta_conversoes_router
from routes.estoque import router as estoque_router
import agenda_worker
import campaign_runner
import health_monitor
import media_retention
import migrations
import whatsapp_client


app = FastAPI(title="ZappZen API")


def _cors_origins() -> list[str]:
    """Origens permitidas — exigidas, nunca `*` (ZZ-10).

    Com `allow_credentials=True`, o Starlette **não** devolve `*`: quando a
    requisição traz cookie, ele ecoa a Origin recebida e marca
    `Allow-Credentials: true` — ou seja, um `*` de configuração vira "qualquer
    site pode agir em nome do usuário logado". Por isso aqui não há default: sem
    `CORS_ORIGINS` o boot falha, igual a `JWT_SECRET`, e `*` é recusado
    explicitamente.
    """
    bruto = os.environ.get("CORS_ORIGINS")
    if not bruto or not bruto.strip():
        raise RuntimeError(
            "CORS_ORIGINS não definido: liste as origens permitidas separadas "
            "por vírgula (ex.: https://app.suaempresa.com). O boot é abortado "
            "de propósito — um default '*' com cookies de credencial é inseguro."
        )
    origens = [o.strip() for o in bruto.split(",") if o.strip()]
    if any(o == "*" for o in origens):
        raise RuntimeError(
            "CORS_ORIGINS não pode ser '*' junto com cookies de credencial. "
            "Liste as origens exatas do frontend."
        )
    return origens


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cabeçalhos de segurança em toda resposta (ZZ-16). `setdefault` para não pisar
# em quem já definiu o seu — /api/media manda a própria CSP `sandbox`, e não
# queremos afrouxá-la aqui. Sem CSP global de propósito: a API devolve JSON, e
# uma CSP restrita quebraria o Swagger em /docs, que carrega assets de CDN.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",      # sem MIME sniffing (reforça ZZ-07)
    "X-Frame-Options": "DENY",                # sem iframe -> sem clickjacking
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.middleware("http")
async def _carimbar_seguranca(request, call_next):
    from auth import _cookie_secure
    resp = await call_next(request)
    for chave, valor in _SECURITY_HEADERS.items():
        resp.headers.setdefault(chave, valor)
    # HSTS só faz sentido quando se serve por HTTPS (mesma condição do cookie
    # Secure): mandá-lo em dev http não teria efeito e confundiria o diagnóstico.
    if _cookie_secure():
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return resp


# CORS aberto só para o envio de formulário de site (`/api/f/...`). O resto da
# API aceita apenas a origem do painel, com cookie; este endereço é chamado do
# site do cliente, que pode ser qualquer domínio, e não leva credencial nenhuma
# (quem identifica o formulário é a chave no caminho). Fica por fora do
# CORSMiddleware, que recusaria o preflight de uma origem fora da lista antes de
# o pedido chegar à rota.
_CORS_PUBLICO = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


@app.middleware("http")
async def _cors_formularios(request, call_next):
    if not request.url.path.startswith("/api/f/"):
        return await call_next(request)
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS_PUBLICO)
    resp = await call_next(request)
    # Se a origem for a do painel, o CORSMiddleware já pôs a dele com
    # credencial; `*` com credencial é inválido, então a credencial sai.
    if "access-control-allow-credentials" in resp.headers:
        del resp.headers["access-control-allow-credentials"]
    for chave, valor in _CORS_PUBLICO.items():
        resp.headers[chave] = valor
    return resp


app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(bots_router)
app.include_router(flows_router)
app.include_router(contacts_router)
app.include_router(whatsapp_router)
app.include_router(dashboard_router)
app.include_router(webhooks_router)
# Receptor do canal não oficial. Mesmo prefixo (`/api/webhooks`), caminhos
# diferentes (`/wuzapi/...`), módulo separado: os dois protocolos não têm nada
# em comum antes de `handle_incoming_message`, e o da Cloud API está verificado
# contra tráfego real — misturá-los faria cada correção de um passar por cima
# do outro.
app.include_router(webhooks_wuzapi_router)
app.include_router(departments_router)
app.include_router(users_router)
app.include_router(atendimento_router)
app.include_router(plans_router)
app.include_router(media_router)
app.include_router(campaigns_router)
app.include_router(deals_router)
app.include_router(meta_conversoes_router)
app.include_router(estoque_router)
app.include_router(activities_router)
app.include_router(reports_router)
app.include_router(ai_router)
app.include_router(settings_router)
app.include_router(scheduling_router)
# Webhook de voz do Twilio e a tela de Telefone (ver `ligacoes.py`).
app.include_router(voz_router)
# Formulário de site: o endereço público que recebe o lead e a configuração.
app.include_router(formularios_router)


@app.get("/api/health")
async def health():
    # A ponte do WhatsApp vai junto: um monitor de uptime apontado aqui pega
    # a queda dela, que foi três dias e meio invisível em 03/11/2026. O
    # status HTTP continua 200: o backend está de pé, e quem vigia decide.
    fora = health_monitor.ponte_fora()
    return {"status": "ok", "service": "zappzen",
            "ponte_whatsapp": "fora" if fora else "ok",
            **({"ponte_fora_desde": fora["desde"]} if fora else {})}


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zappzen")


# `processed_messages` só existe para deduplicar reentrega: o gateway repete um
# webhook por minutos, não por meses. Sem expiração a coleção crescia um
# documento por mensagem recebida, para sempre, com um índice único que o Mongo
# tenta manter em memória.
PROCESSED_MESSAGES_TTL = 7 * 86400


# Índices declarados numa tabela só, em vez de espalhados pelo startup: é aqui
# que se responde "esta query está coberta?" sem varrer o backend inteiro.
#
# `unique` aparece apenas onde já existia. Um índice único novo sobre dado
# legado duplicado derrubaria o startup por completo — e o que se quer aqui é
# desempenho; a unicidade dos uuid4 vem de quem os gera.
INDEXES: list[tuple[str, list[tuple[str, int]], dict]] = [
    # get_current_user resolve o usuário por `id` em TODA request autenticada.
    # Sem este índice, cada request custava uma varredura completa de `users`.
    ("users", [("id", 1)], {}),
    ("users", [("email", 1)], {"unique": True}),
    ("users", [("tenant_id", 1)], {}),

    ("tenants", [("id", 1)], {"unique": True}),
    ("plans", [("id", 1)], {}),

    ("bots", [("tenant_id", 1), ("id", 1)], {}),
    # Escolha do bot que atende cada conversa nova (_pick_bot_for_new_session).
    ("bots", [("tenant_id", 1), ("connection_id", 1), ("trigger", 1), ("status", 1)], {}),

    ("flows", [("bot_id", 1)], {}),
    # _load_bot_flow abre o fluxo por id a cada mensagem recebida.
    ("flows", [("id", 1)], {}),

    ("contacts", [("tenant_id", 1)], {}),
    ("contacts", [("id", 1)], {}),
    # Resolução do contato pelo número, uma vez por mensagem recebida.
    ("contacts", [("tenant_id", 1), ("numero_whatsapp", 1)], {}),
    # Público de campanha por etiqueta, já descontando quem pediu para sair
    # (campaigns.audience_query). É a consulta que decide quem recebe.
    ("contacts", [("tenant_id", 1), ("opt_out", 1), ("tags", 1)], {}),
    # Carteira de um responsável (filtro da lista de contatos).
    ("contacts", [("tenant_id", 1), ("responsavel_id", 1)], {}),

    # Notas da ficha, sempre lidas por contato e em ordem de data. `_id` entra
    # porque entra no sort: duas notas seguidas compartilham o `created_at`
    # (resolução do relógio), e é ele que desempata.
    ("contact_notes", [("tenant_id", 1), ("contact_id", 1), ("created_at", -1), ("_id", -1)], {}),
    ("contact_notes", [("id", 1)], {}),
    # Definições de campo personalizado: lidas inteiras, na ordem da tela.
    ("contact_field_defs", [("tenant_id", 1), ("ordem", 1)], {}),

    ("pipelines", [("tenant_id", 1), ("created_at", 1)], {}),
    ("pipelines", [("id", 1)], {}),

    # Uma coluna do quadro: etapa do funil, na ordem dos cartões. É a consulta
    # que roda uma vez por coluna a cada abertura do Kanban.
    ("deals", [("tenant_id", 1), ("pipeline_id", 1), ("etapa_id", 1), ("ordem", 1)], {}),
    # Relatório: resumo por status e a janela por data de fechamento.
    ("deals", [("tenant_id", 1), ("pipeline_id", 1), ("status", 1), ("fechado_em", 1)], {}),
    # Bloco de negócios na ficha do contato.
    ("deals", [("tenant_id", 1), ("contact_id", 1)], {}),
    # Carteira de um responsável (filtro do quadro).
    ("deals", [("tenant_id", 1), ("responsavel_id", 1)], {}),
    ("deals", [("id", 1)], {}),
    # Retorno por campanha: agrupa os ganhos pela campanha de origem.
    ("deals", [("tenant_id", 1), ("campanha_id", 1), ("status", 1)], {}),

    # Histórico do negócio. `_id` entra porque entra no sort: dois eventos do
    # mesmo salvamento compartilham o `created_at`.
    ("deal_events", [("tenant_id", 1), ("deal_id", 1), ("created_at", -1), ("_id", -1)], {}),
    # Conversions API: um documento por empresa, e o registro de envios, que
    # é consultado a cada mudança de etapa ("este evento já saiu?").
    ("meta_conversoes", [("tenant_id", 1)], {"unique": True}),
    ("meta_eventos", [("tenant_id", 1), ("deal_id", 1), ("evento", 1), ("status", 1)], {}),
    ("meta_eventos", [("tenant_id", 1), ("created_at", -1)], {}),

    # A agenda de um responsável: pendentes, na ordem de vencimento. É a
    # consulta que abre a tela de Atividades e alimenta o selo do menu.
    ("activities", [("tenant_id", 1), ("responsavel_id", 1), ("concluida_em", 1), ("vence_em", 1)], {}),
    # Mesma lista sem filtro de responsável, e o resumo por empresa.
    ("activities", [("tenant_id", 1), ("concluida_em", 1), ("vence_em", 1)], {}),
    # "Este negócio tem próximo passo?" — marca do cartão no quadro.
    ("activities", [("tenant_id", 1), ("deal_id", 1), ("concluida_em", 1)], {}),
    # Bloco de atividades na ficha do contato.
    ("activities", [("tenant_id", 1), ("contact_id", 1), ("concluida_em", 1)], {}),
    ("activities", [("id", 1)], {}),
    # Corrente de follow-up, desfeita quando a atividade de origem é apagada.
    ("activities", [("tenant_id", 1), ("origem_id", 1)], {}),

    ("campaigns", [("tenant_id", 1), ("created_at", -1)], {}),
    ("campaigns", [("id", 1)], {}),
    # Varredura do supervisor: campanha em disparo e agendada cuja hora chegou.
    ("campaigns", [("status", 1), ("agendada_para", 1)], {}),

    # O claim do próximo destinatário (find_one_and_update ordenado por _id)
    # roda uma vez por mensagem disparada — é a consulta mais quente de uma
    # campanha grande.
    ("campaign_recipients", [("campaign_id", 1), ("status", 1), ("_id", 1)], {}),
    ("campaign_recipients", [("id", 1)], {}),
    # Marcação de resposta e listagem por contato.
    ("campaign_recipients", [("campaign_id", 1), ("contact_id", 1)], {}),
    # Cota mensal de disparos do plano.
    ("campaign_recipients", [("tenant_id", 1), ("status", 1), ("sent_at", 1)], {}),
    # "Quais campanhas este contato já recebeu?" — bloco da ficha.
    ("campaign_recipients", [("tenant_id", 1), ("contact_id", 1)], {}),
    # Falha de entrega chega por webhook e casa com o destinatário pelo wamid.
    # Numa campanha de 20.000 sem índice, cada status de falha varreria a lista
    # inteira de destinatários da empresa.
    ("campaign_recipients", [("tenant_id", 1), ("wamid", 1)], {"sparse": True}),

    # A lista da Central filtra por `status_atendimento` e ordena por
    # `updated_at`. O índice que existia cobria `status` — outro campo, com
    # outros valores (ativa/finalizada) — e por isso nunca era usado pela tela
    # principal do produto.
    ("conversation_sessions", [("tenant_id", 1), ("status_atendimento", 1), ("updated_at", -1)], {}),
    # Mesma lista sem filtro de status (a aba "todas").
    ("conversation_sessions", [("tenant_id", 1), ("updated_at", -1)], {}),
    ("conversation_sessions", [("id", 1)], {}),
    # Conversa em andamento de um contato numa conexão (handle_incoming_message).
    ("conversation_sessions", [("tenant_id", 1), ("contact_id", 1), ("whatsapp_connection_id", 1)], {}),
    # Contadores do dashboard, que ainda consultam `status`.
    ("conversation_sessions", [("tenant_id", 1), ("status", 1)], {}),
    # Janela do relatório de atendimento: conversas criadas no período.
    ("conversation_sessions", [("tenant_id", 1), ("created_at", 1)], {}),
    # Soma de não lidas do sino de notificação, a cada poucos segundos.
    ("conversation_sessions", [("tenant_id", 1), ("unread_count", 1)], {}),

    # `_id` entra no índice porque entra no sort do histórico: mensagens da
    # mesma rajada compartilham o timestamp, e é ele que desempata. Substitui
    # o antigo (session_id, timestamp), que é seu prefixo — bancos que já o
    # tenham podem descartá-lo.
    ("messages_log", [("session_id", 1), ("timestamp", 1), ("_id", 1)], {}),
    ("messages_log", [("meta.media.id", 1)], {"sparse": True}),
    # Status de entrega chega por webhook e casa com a bolha pelo wamid. Uma
    # mensagem entregue e lida gera duas buscas por aqui, então sem índice
    # seria uma varredura do histórico inteiro por evento.
    ("messages_log", [("tenant_id", 1), ("meta.wamid", 1)], {"sparse": True}),
    # Contagem de mensagens do mês no dashboard e a série por dia do relatório
    # de atendimento (agrupada pelo prefixo do ISO em `timestamp`).
    ("messages_log", [("tenant_id", 1), ("timestamp", 1)], {}),

    ("processed_messages", [("message_id", 1)], {"unique": True}),
    ("processed_messages", [("at", 1)], {"expireAfterSeconds": PROCESSED_MESSAGES_TTL}),

    ("whatsapp_connections", [("tenant_id", 1), ("id", 1)], {}),
    # O webhook da Cloud API chega num endereço só, para todas as empresas, e
    # o que diz de quem ele é são os metadados do payload. Este índice está no
    # caminho de TODA mensagem recebida do sistema inteiro.
    ("whatsapp_connections", [("phone_number_id", 1)], {"sparse": True}),
    # O mesmo papel, no canal não oficial: a ponte nao assina o webhook, entao
    # quem prova a origem do evento e um segredo na propria URL, e e por ele
    # que a conexao e encontrada. Caminho de TODA mensagem recebida por esse
    # canal, e a consulta acontece antes de qualquer decisao.
    ("whatsapp_connections", [("wuzapi_webhook_token", 1)], {"sparse": True}),
    # Varredura do health_monitor.
    ("whatsapp_connections", [("status", 1), ("last_webhook_event_at", 1)], {}),

    # Consultado em toda chamada da Central, para montar o escopo do atendente.
    ("user_connection_access", [("tenant_id", 1), ("user_id", 1)], {}),

    ("departments", [("tenant_id", 1)], {}),
    ("departments", [("id", 1)], {}),

    ("media_files", [("tenant_id", 1), ("id", 1)], {}),
    # Varredura de retenção: busca por idade e marca as mensagens do arquivo.
    ("media_files", [("created_at", 1)], {}),
    ("media_files", [("tenant_id", 1), ("stored_name", 1)], {}),

    # Agentes de IA da empresa. Lidos a cada mensagem recebida que chegue a um
    # ponto sem bot, então a consulta é quente: `ativo` e `modo` entram no
    # índice porque entram no filtro (agente desligado não deve nem ser lido).
    ("ai_agents", [("tenant_id", 1), ("ativo", 1), ("modo", 1), ("created_at", 1)], {}),
    ("ai_agents", [("id", 1)], {}),
    # Toda consulta de estoque do agente filtra pela versão atual, ordenada
    # pela linha da planilha. A busca por palavra é regex sobre `busca`, que
    # nenhum índice cobre: este é o que a restringe às linhas de um agente só.
    ("ai_estoque", [("tenant_id", 1), ("agente_id", 1), ("versao", 1), ("ordem", 1)], {}),

    # Consumo agregado do mês (cota do plano e o número que a tela mostra).
    ("ai_usage", [("tenant_id", 1), ("mes", 1)], {}),
    # A chave do upsert que soma cada resposta no acumulado do dia.
    ("ai_usage", [("tenant_id", 1), ("dia", 1), ("provedor", 1), ("modelo", 1),
                  ("origem", 1), ("agente_id", 1)], {}),

    # Estoque de veículos: toda leitura é do pátio de uma empresa, e a ficha é
    # aberta pelo id.
    ("veiculos", [("tenant_id", 1), ("id", 1)], {}),

    ("impersonation_log", [("id", 1)], {}),

    # Trilha de auditoria (ZZ-21): consultada por empresa e por tipo de ação,
    # sempre da mais recente para a mais antiga.
    ("audit_log", [("tenant_id", 1), ("em", -1)], {}),
    ("audit_log", [("acao", 1), ("em", -1)], {}),

    # --- Agenda -----------------------------------------------------------
    #
    # A consulta quente é sempre a mesma: "o que este profissional tem marcado
    # nesta janela?". Ela roda uma vez por dia consultado, e um agendamento pelo
    # bot consulta vários dias seguidos, sem índice, cada pergunta de horário
    # varreria a coleção inteira da empresa. `status` entra porque entra no
    # filtro (cancelado não ocupa), e `inicio` fecha a faixa.
    ("appointments", [("tenant_id", 1), ("resource_id", 1), ("status", 1), ("inicio", 1)], {}),
    # A tela da agenda: a janela inteira da empresa, em ordem. `_id` entra
    # porque entra no sort: dois horários podem começar no mesmo minuto com
    # profissionais diferentes, e sem o desempate a ordem fica indefinida.
    ("appointments", [("tenant_id", 1), ("inicio", 1), ("_id", 1)], {}),
    # Os horários futuros de um contato: a ficha, e a ferramenta de cancelar do
    # agente de IA.
    ("appointments", [("tenant_id", 1), ("contact_id", 1), ("inicio", 1)], {}),
    # A varredura de lembretes, que roda a cada cinco minutos para todas as
    # empresas de uma vez, por isso ela NÃO começa por `tenant_id`.
    ("appointments", [("lembrete_enviado_em", 1), ("status", 1), ("inicio", 1)], {}),
    ("appointments", [("id", 1)], {}),
    # "Esse serviço/profissional ainda tem horário marcado?", antes de excluir.
    ("appointments", [("tenant_id", 1), ("service_id", 1), ("status", 1)], {}),

    ("services", [("tenant_id", 1), ("ativo", 1), ("ordem", 1)], {}),
    ("services", [("id", 1)], {}),
    ("resources", [("tenant_id", 1), ("ativo", 1), ("nome", 1)], {}),
    ("resources", [("id", 1)], {}),
    ("scheduling_settings", [("tenant_id", 1)], {}),

    # Telefone. O número chamado é a chave de roteamento de **toda** ligação
    # que chega ao webhook de voz, de todas as empresas: mesmo papel do
    # `phone_number_id` das conexões de WhatsApp.
    ("voz_config", [("numero", 1)], {"sparse": True}),
    ("voz_config", [("tenant_id", 1)], {}),
    # O Twilio busca a gravação por este token, sem login.
    ("voz_config", [("audio_token", 1)], {"sparse": True}),
    # A tecla volta pelo CallSid; a lista da tela e o resumo são por período.
    ("ligacoes", [("tenant_id", 1), ("call_sid", 1)], {}),
    ("ligacoes", [("tenant_id", 1), ("created_at", -1), ("_id", -1)], {}),
    # "Este número já recebeu a mensagem há pouco?", a cada tecla 1.
    ("ligacoes", [("tenant_id", 1), ("numero", 1), ("status", 1), ("created_at", -1)], {}),
    ("ligacoes", [("id", 1)], {}),

    # Formulários de site. A chave chega em **todo** envio público, de todas
    # as empresas, e é por ela que se acha o formulário: única, porque duas
    # empresas com a mesma chave receberiam o lead uma da outra.
    ("formularios", [("chave", 1)], {"unique": True}),
    ("formularios", [("tenant_id", 1), ("created_at", 1)], {}),
    ("formularios", [("id", 1)], {}),
    # Lista da tela e resumo por período; a contagem da grade agrupa por formulário.
    ("formulario_respostas", [("tenant_id", 1), ("formulario_id", 1), ("created_at", -1), ("_id", -1)], {}),
    ("formulario_respostas", [("tenant_id", 1), ("created_at", -1)], {}),
    # "Este número já mandou há pouco?" (clique duplo e WhatsApp repetido), e
    # a LGPD, que acha as respostas da pessoa pela ficha.
    ("formulario_respostas", [("tenant_id", 1), ("contact_id", 1), ("created_at", -1)], {}),
    ("formulario_respostas", [("id", 1)], {}),
]

# Um índice já existente com as mesmas chaves e opções diferentes faz o Mongo
# recusar a criação. Só acontece quando a definição muda de uma versão para
# outra (foi o caso do TTL) — recriar é o comportamento pretendido, e deixar o
# erro subir derrubaria o boot.
_INDEX_CONFLICT_CODES = {85, 86}  # IndexOptionsConflict, IndexKeySpecsConflict


async def _ensure_indexes(db):
    for collection, keys, options in INDEXES:
        try:
            await db[collection].create_index(keys, **options)
        except OperationFailure as e:
            if e.code not in _INDEX_CONFLICT_CODES:
                raise
            name = "_".join(f"{field}_{direction}" for field, direction in keys)
            logger.info("Índice %s.%s mudou de definição — recriando", collection, name)
            await db[collection].drop_index(name)
            await db[collection].create_index(keys, **options)


async def _expire_legacy_processed_messages(db):
    """O TTL do Mongo só enxerga campo do tipo Date, e `at` era gravado como
    string ISO — os documentos anteriores a esta mudança nunca expirariam
    sozinhos. Apagá-los é exatamente o que o TTL faria: são registros de
    deduplicação velhos de dias, muito além de qualquer janela de retry."""
    result = await db.processed_messages.delete_many({"at": {"$type": "string"}})
    if result.deleted_count:
        logger.info("Removidos %d registros antigos de deduplicação (sem TTL)", result.deleted_count)


@app.on_event("startup")
async def on_startup():
    db = get_db()
    await _ensure_indexes(db)
    await _expire_legacy_processed_messages(db)
    await seed_super_admin()
    migrations.start()
    health_monitor.start()
    media_retention.start()
    campaign_runner.start()
    agenda_worker.start()
    faltando = [v for v in ("META_APP_SECRET", "META_WEBHOOK_VERIFY_TOKEN")
                if not os.environ.get(v)]
    if faltando:
        # Não derruba o boot (um ambiente pode subir sem webhook por um tempo),
        # mas grita: sem o App Secret todo webhook é recusado com 503 (ZZ-11), e
        # sem o token de verificação a própria Meta não aceita cadastrar a URL.
        logger.warning("%s ausente: webhooks serão RECUSADOS até configurar",
                       " e ".join(faltando))
    logger.info("ZappZen backend started, super admin seeded.")


@app.on_event("shutdown")
async def on_shutdown():
    migrations.stop()
    health_monitor.stop()
    media_retention.stop()
    campaign_runner.stop()
    agenda_worker.stop()
    await whatsapp_client.close_client()
    close_db()
