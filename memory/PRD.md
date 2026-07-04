# ZappZen — PRD

## Problem Statement (original)
Build ZappZen: multi-tenant SaaS platform where companies (tenants) create WhatsApp chatbots through a visual flow editor (React Flow canvas). Two roles — Super Admin (owns the platform, manages tenants) and Tenant Admin (owns bots inside their company). Each tenant fully isolated. Ten node types (Start, Text, Menu, Save Variable, Condition, Media, Delay, Webhook, Human Handoff, End), flow test simulator, mocked WhatsApp connection UI, human handoff inbox, super admin console.

## Stack (as delivered)
- Backend: FastAPI + Motor (async MongoDB) + PyJWT + bcrypt
- Frontend: React 19 + React Router 7 + @xyflow/react + Tailwind + shadcn/ui + Phosphor Icons + Sonner toasts
- Design: Swiss Brutalist / Grid-Borders light theme (Cabinet Grotesk + IBM Plex Sans + JetBrains Mono)

## User personas
1. **Super Admin** — platform owner. Manages tenant companies, sees global metrics, can suspend/reactivate.
2. **Tenant Admin** — company user. Manages own bots, flow editor, WhatsApp connection, contacts, and human-handoff inbox.

## Architecture done
- Auth: httpOnly cookie JWT (12h access + 7d refresh) with `role` and `tenant_id` claims. Super admin seeded on startup from `.env`.
- Multi-tenant isolation: every tenant-scoped query filters by `tenant_id` from the current user's token. Super admin routes 403 tenant admins and vice versa.
- Flow engine: interprets nodes graph; runs Start→Text→Menu→(branch)→End chains, waits at Menu for user input, supports variables, condition branching, mocked webhook, human handoff, media, delay.
- WhatsApp: mocked interface (start_pairing generates a fake QR string; confirm_paired sets a mock number). Real integration deferred.

## What's been implemented (2026-02)
- ✅ Auth (login/me/logout, role-based routing, super admin seeding)
- ✅ Super admin console: tenants CRUD, suspend/reactivate, global metrics dashboard
- ✅ Tenant admin: dashboard with 6 KPI tiles, bots CRUD (create/duplicate/pause/delete), contacts list, sessions list, inbox for human handoff, settings page
- ✅ Flow editor with @xyflow/react: 10 node types (custom node renderer + palette + drag-and-drop + side config panel + save/publish/testar)
- ✅ Flow test simulator (in-editor chat panel that runs the engine on the current draft)
- ✅ WhatsApp mock UI (QR display, connect/disconnect states)
- ✅ Portuguese UI throughout, Swiss Brutalist / Grid Borders design system

## Backlog / Next tasks
- **P0** — Real WhatsApp integration (Cloud API or web-lib module) via the existing `/api/whatsapp/*` interface
- **P0** — Message ingestion queue (Redis/BullMQ equivalent) that plugs into the flow engine for real inbound messages
- **P1** — Analytics: charts (recharts) for messages over time, funnel drop-off per node
- **P1** — Rich node config: per-menu-option flexible sourceHandles UI, drag-to-reorder options
- **P1** — Flow templates gallery (pre-built bots to copy)
- **P2** — Password reset flow, invite additional users per tenant, plan-based quotas enforcement
- **P2** — Export flow as JSON, import from Typebot/n8n
- **P2** — Audit log per tenant (who changed what)

## Notable design decisions
- All backend responses drop MongoDB `_id`; UUIDs stored as `id` field on all documents.
- Flow versions persisted on every save (basic history).
- Flow validation happens only at publish (documented — save is intentionally permissive to allow work-in-progress drafts).
- Test chat is server-side simulated (module-level session store) — no persistence between server restarts, which is fine because the frontend restarts each simulation.
