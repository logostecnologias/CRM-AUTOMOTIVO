# ZappZen

Plataforma SaaS multi-tenant de chatbots para WhatsApp, com editor visual de fluxos e Central de Atendimento. Veja [CLAUDE.md](CLAUDE.md) para o contexto completo do projeto.

## Stack

- **Backend**: FastAPI (Python) — `backend/`
- **Frontend**: React + `@xyflow/react` — `frontend/`
- **Banco**: MongoDB
- **WhatsApp**: Cloud API oficial da Meta

## Rodando localmente

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload
```

Requer um `.env` em `backend/` com as variáveis de conexão (Mongo, WhatsApp, etc.).

### Webhook do WhatsApp

O receptor é um endereço só, para todas as empresas:

```
https://SEU-DOMINIO/api/webhooks/whatsapp
```

Cadastre-o no painel do app da Meta (**WhatsApp > Configuração > Webhook**), use
o valor de `META_WEBHOOK_VERIFY_TOKEN` no campo "Verificar token" e assine o
campo **messages**. Sem a assinatura desse campo, o número envia mensagens e não
recebe nenhuma.

Em desenvolvimento, o `start-dev.ps1` sobe um túnel Cloudflare e imprime a URL
para colar no painel. A superfície pública é só `/api/webhooks/*`, garantida
pelo `backend/webhook_proxy.py`.

### Frontend

```bash
cd frontend
yarn install
yarn start
```
