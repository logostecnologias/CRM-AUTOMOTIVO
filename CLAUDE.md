# ZappZen — Contexto do Projeto

## Visão Geral

ZappZen é uma plataforma **SaaS multi-tenant** de criação de chatbots para WhatsApp, com um **editor visual de fluxos** (tipo n8n/Typebot: retângulos conectados por linhas) e uma **Central de Atendimento** unificada para múltiplas conexões de WhatsApp.

O desenvolvimento continua localmente via **Claude Code**.

---

## Stack Técnica

- **Backend**: FastAPI (Python)
- **Banco de dados**: MongoDB (sem isolamento nativo de tenant — **todo filtro por `tenant_id` é responsabilidade da aplicação**, aplicado em toda query sensível, sem exceção)
- **Frontend**: React + `@xyflow/react` (React Flow) para o editor visual
- **Design**: Swiss Brutalist / Grid Borders, fontes Cabinet Grotesk + IBM Plex Sans, UI 100% em português, elementos com `data-testid`
- **WhatsApp**: integração real via **WuzAPI** (self-hosted, wrapper REST sobre whatsmeow), sempre atrás de um **gateway próprio** (`zappzen-gateway`, porta 8090) que faz rate limiting, normalização de número e fila/retry de webhook — o backend nunca chama a WuzAPI diretamente. Autenticação em duas camadas: `WUZAPI_ADMIN_TOKEN` (só cria/apaga instância) e um token por instância (`wuzapi_token`, guardado em `whatsapp_connections`), usado em toda outra chamada. Credenciais sempre em variável de ambiente, nunca hardcoded.

---

## Hierarquia de Usuários (3 níveis)

1. **Super Admin** — cria/ativa/desativa empresas (tenants), gerencia planos, pode "Entrar na empresa" (impersonation, via JWT com claim `impersonation_id`, com log de auditoria em `impersonation_log` e rota `/api/auth/exit-impersonation` pra sair).
2. **Tenant Admin** — vê e configura toda a operação da própria empresa: bots, fluxos, conexões WhatsApp, departamentos, usuários e toda a Central de Atendimento.
3. **Usuário Comum (agente/atendente)** — só vê conversas das conexões de WhatsApp liberadas explicitamente pra ele (`user_connection_access`). Só pode assumir conversas em "Aguardando" e responder as que já assumiu.

---

## Funcionalidades já implementadas

### Núcleo (MVP original, fases 1-3-5)
- Auth multi-tenant (JWT httpOnly cookie), super admin semeado no startup
- CRUD de bots e fluxos
- Editor visual com React Flow: **10 tipos de nó** — Início, Mensagem, Menu (saída dinâmica por opção), Salvar Variável, Condição, Mídia, Aguardar, Webhook, Atendimento Humano, Fim
- Motor de execução de fluxos, reaproveitado tanto no modo "Testar" (simulado) quanto no fluxo real via webhook do WhatsApp
- Painel Super Admin com CRUD de tenants

### Integração WhatsApp real (WuzAPI)
- `/api/whatsapp/connections/{id}/connect`, `/disconnect`, CRUD de conexões — cada uma com sua própria instância/token na WuzAPI
- Endpoint receptor `POST /api/webhooks/wuzapi/{tenant_id}/{connection_id}` recebendo eventos via o gateway (mensagem recebida, QR, status de conexão), validados por HMAC (`WUZAPI_GLOBAL_HMAC_KEY`), alimentando o motor de execução
- Funções `_send_outputs`/`send_human_message` em `flow_runtime.py` reutilizáveis, chamadas tanto pelo motor de fluxos quanto pelo módulo de atendimento humano — ambas usam `wuzapi_token` (não um "nome de instância") como credencial de envio

### Central de Atendimento (mais recente)
- Toda conversa nasce com `status_atendimento = 'bot'`; nó de Atendimento Humano no fluxo transiciona pra `aguardando`; nó Fim transiciona pra `finalizado`
- Estados: `bot` → `aguardando` → `em_atendimento` → `finalizado`
- Collection `departments` (nome + cor), com `departamento_padrao_id` em `whatsapp_connections`, sobrescrevível por conversa
- Collection `user_connection_access` controlando visibilidade por usuário comum
- Rotas: `/api/departments` (CRUD), `/api/users` (CRUD de atendentes), `/api/atendimento/*` (listar com filtros de escopo, `/assume`, `/finalize`, `/department`, `/send`, `/summary`)
- Frontend: Kanban de 4 colunas, painel lateral de chat com histórico completo (incluindo trecho conduzido pelo bot antes do handoff), polling de 3s (ainda não é WebSocket)
- Barra "MODO SUPORTE" visível durante impersonation do Super Admin

---

## Pendências conhecidas (Next Action Items da última entrega)

1. **[PRIORIDADE ALTA] Multi-conexão no frontend**: o schema (`whatsapp_connections`) já suporta múltiplas conexões por tenant, mas a UI ainda assume uma única conexão. Precisa: lista de conexões na tela de WhatsApp, seletor de conexão nos filtros da Central de Atendimento, departamento padrão configurável por conexão (já existe no backend, falta expor bem no front para múltiplas).
2. **Reabertura configurável de conversas finalizadas**: hoje sempre reabre em `bot`. Adicionar `reopen_mode` (`bot` ou `aguardando`), configurável por bot ou por departamento.
3. **WebSocket no lugar do polling de 3s**: otimização de performance para quando o volume de conversas crescer — não é bloqueador agora.

---

## Convenções e regras importantes a manter

- **Nunca** deixar uma query no backend sem filtro de `tenant_id` explícito — é a única barreira de isolamento entre empresas, já que o Mongo não tem RLS nativo.
- O motor de execução de fluxos é único e compartilhado entre o modo "Testar" (simulado) e o fluxo real de mensagens — não duplicar lógica.
- Rotas administrativas (admin/super admin) devem retornar 403 de verdade para usuários sem permissão, não só esconder na UI — validar sempre no backend.
- Toda ação de impersonation do Super Admin deve ficar registrada em `impersonation_log`.
- Design já definido (Swiss Brutalist / Grid Borders) — manter consistência visual ao adicionar novas telas.
