from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
from fastapi import FastAPI
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
from routes.departments import router as departments_router
from routes.users import router as users_router
from routes.atendimento import router as atendimento_router
from routes.plans import router as plans_router
from routes.media import router as media_router
import health_monitor
import media_retention
import migrations
import wuzapi_client


app = FastAPI(title="ZappZen API")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(bots_router)
app.include_router(flows_router)
app.include_router(contacts_router)
app.include_router(whatsapp_router)
app.include_router(dashboard_router)
app.include_router(webhooks_router)
app.include_router(departments_router)
app.include_router(users_router)
app.include_router(atendimento_router)
app.include_router(plans_router)
app.include_router(media_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "zappzen"}


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
    # Soma de não lidas do sino de notificação, a cada poucos segundos.
    ("conversation_sessions", [("tenant_id", 1), ("unread_count", 1)], {}),

    # `_id` entra no índice porque entra no sort do histórico: mensagens da
    # mesma rajada compartilham o timestamp, e é ele que desempata. Substitui
    # o antigo (session_id, timestamp), que é seu prefixo — bancos que já o
    # tenham podem descartá-lo.
    ("messages_log", [("session_id", 1), ("timestamp", 1), ("_id", 1)], {}),
    ("messages_log", [("meta.media.id", 1)], {"sparse": True}),
    # Contagem de mensagens do mês no dashboard.
    ("messages_log", [("tenant_id", 1), ("timestamp", 1)], {}),

    ("processed_messages", [("message_id", 1)], {"unique": True}),
    ("processed_messages", [("at", 1)], {"expireAfterSeconds": PROCESSED_MESSAGES_TTL}),

    ("whatsapp_connections", [("tenant_id", 1), ("id", 1)], {}),
    ("whatsapp_connections", [("wuzapi_token", 1)], {"sparse": True}),
    # Webhook sem ids na URL resolve a conexão pelo `userID` do payload.
    ("whatsapp_connections", [("wuzapi_user_id", 1)], {"sparse": True}),
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

    ("impersonation_log", [("id", 1)], {}),
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
    logger.info("ZappZen backend started, super admin seeded.")


@app.on_event("shutdown")
async def on_shutdown():
    migrations.stop()
    health_monitor.stop()
    media_retention.stop()
    await wuzapi_client.close_client()
    close_db()
