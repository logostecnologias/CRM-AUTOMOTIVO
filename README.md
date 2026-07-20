# ZappZen

Plataforma SaaS multi-tenant de chatbots para WhatsApp, com editor visual de fluxos e Central de Atendimento. Veja [CLAUDE.md](CLAUDE.md) para o contexto completo do projeto.

## Stack

- **Backend**: FastAPI (Python) — `backend/`
- **Frontend**: React + `@xyflow/react` — `frontend/`
- **Banco**: MongoDB

## Rodando localmente

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload
```

Requer um `.env` em `backend/` com as variáveis de conexão (Mongo, WhatsApp, etc.).

### Frontend

```bash
cd frontend
yarn install
yarn start
```
