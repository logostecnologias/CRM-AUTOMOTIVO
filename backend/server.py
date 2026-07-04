from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from db import get_db, close_db
from auth import router as auth_router, seed_super_admin
from routes.tenants import router as tenants_router
from routes.bots import router as bots_router
from routes.flows import router as flows_router
from routes.contacts import router as contacts_router
from routes.whatsapp import router as whatsapp_router
from routes.dashboard import router as dashboard_router


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


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "zappzen"}


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zappzen")


@app.on_event("startup")
async def on_startup():
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.tenants.create_index("id", unique=True)
    await db.bots.create_index([("tenant_id", 1), ("id", 1)])
    await db.flows.create_index([("bot_id", 1)])
    await db.contacts.create_index([("tenant_id", 1)])
    await db.conversation_sessions.create_index([("tenant_id", 1), ("status", 1)])
    await db.messages_log.create_index([("session_id", 1), ("timestamp", 1)])
    await seed_super_admin()
    logger.info("ZappZen backend started, super admin seeded.")


@app.on_event("shutdown")
async def on_shutdown():
    close_db()
