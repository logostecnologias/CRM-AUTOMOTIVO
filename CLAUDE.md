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

### Mídias (envio e recebimento)
- `POST /api/atendimento/sessions/{id}/send-media` (multipart: `file` + `caption`) — mesma regra de permissão do envio de texto, extraída em `_authorize_send`
- `media_store.py` guarda o binário em `MEDIA_DIR` (default `backend/media/<tenant_id>/`) com nome gerado (nunca o nome do usuário, por path traversal) e um documento em `media_files` carregando o `tenant_id` — é ele que autoriza o download, não o caminho em disco
- `GET /api/media/{media_id}` serve o arquivo autenticado e filtrado por tenant; como o JWT é cookie httpOnly, `<img>`/`<video>` no chat já chegam autenticados
- Tipo de envio derivado do MIME: imagem, vídeo, ogg/opus como áudio, resto como documento (mp3 pelo `/chat/send/audio` viraria mensagem de voz quebrada)
- Toda mídia vai pra WuzAPI como **data URI base64** — a API não busca URL sozinha. `media_store.ensure_data_uri()` cobre os dois casos (arquivo local e a URL pública do nó de Mídia do editor)
- Frontend: `ChatComposer` em `components/atendimento/shared.jsx`, compartilhado pelo Kanban e pela Inbox (anexo por botão ou Ctrl+V, legenda no próprio campo de texto); `MessageBubble` renderiza imagem/vídeo/áudio inline e documento como download
- **Recebimento**: `_extract_media` no webhook identifica o nó de mídia (`imageMessage`, `videoMessage`, `audioMessage`, `documentMessage`, `stickerMessage` → exibido como imagem) e `_ingest_incoming_media` traz o binário. O arquivo do WhatsApp é cifrado e a URL expira, então guardar a URL não serviria — o binário é baixado na hora e vira arquivo nosso, servido pelo mesmo `/api/media`
- Dois caminhos de download, porque depende de como a WuzAPI está rodando: sem `-skipmedia` ela já manda o binário em `base64` na raiz do evento; com `-skipmedia`, é preciso chamar `/chat/download{image,video,audio,document}` com os metadados de cifra da mensagem (`wuzapi_client.download_media`)
- As chaves do payload do whatsmeow variam de caixa entre versões (`URL` x `url`, `fileSha256` x `fileSHA256`) — daí o helper `_pick`, que procura cada campo por todas as grafias plausíveis. Errar a chave faria o download falhar em silêncio
- Falha de download não derruba a mensagem: a legenda ainda entra no histórico, com aviso no lugar do anexo
- Teto de tamanho no recebimento é o geral (20MB), não o de envio por tipo — recusar mídia que o contato já mandou seria perder mensagem
- **Retenção** (`media_retention.py`, mesmo padrão start/stop do `health_monitor`): varre a cada 6h e apaga arquivo fora da janela de retenção. O documento em `media_files` **não** é apagado junto — só ganha `purged_at`, e as mensagens ganham `meta.media.expired`, para a bolha antiga mostrar "mídia expirada" com nome e tamanho em vez de imagem quebrada. `/api/media` devolve 410 nesse caso
- **Janela por plano**: `retencao_midia_dias` no plano define quantos dias a empresa guarda mídia (editável na tela de Planos do super admin). Campo vazio/ausente → default do servidor `MEDIA_RETENTION_DAYS` (90); `0` em qualquer um dos dois → nunca apaga. `_tenant_windows` agrupa as empresas pela janela em vez de iterar uma a uma: mil empresas em três planos viram três consultas de purga, não mil
- Mídia de empresa já excluída cai no default global — sem isso ficaria em disco para sempre, já que nenhum plano a reivindica
- A varredura também recolhe arquivo órfão (binário em disco sem documento, resto de upload interrompido), mas só depois de 24h — nunca compete com um upload em andamento
- `_purge_expired` recusa `days <= 0` por dentro: 0 significa "desligado", e sem a guarda um cutoff de zero dia apagaria o acervo inteiro

---

### Desempenho (varredura de 2026-07-28)
- **Índices**: todos declarados numa tabela única (`INDEXES`, em `server.py`), não espalhados pelo startup — é lá que se responde "esta query está coberta?". Ao criar uma query quente nova, conferir a tabela. Faltavam os de `users.id` (usado em **toda** request autenticada, via `get_current_user`) e o de `conversation_sessions.status_atendimento` — o que existia cobria `status`, campo diferente, então a tela principal do produto nunca usava índice
- **`processed_messages` tem TTL de 7 dias**, indexado em `at`. Por isso `at` é gravado como `datetime` nativo e não como string ISO igual ao resto do sistema: o TTL do Mongo só age sobre campo do tipo `Date`. A coleção é só deduplicação da janela de retry do gateway — nada ali precisa sobreviver dias
- **`last_message` é desnormalizado na sessão**: `flow_runtime.log_message()` grava a mensagem e a prévia juntas, e **todo** caminho que escreve em `messages_log` passa por ela — é o que impede os dois lados de divergir. Antes a lista de conversas redescobria a última mensagem de cada uma com um aggregate que ordenava todas as mensagens das até 200 conversas em tela, a cada 3s, por atendente. Sessões anteriores à mudança são preenchidas por `migrations.py` (idempotente, roda no start)
- **`GET /atendimento/sessions/{id}?since=`** devolve só as mensagens novas. O corte é `$gte` e o front reconcilia por id: o relógio do Windows anda de ~15ms em ~15ms, então mensagens da mesma rajada nascem com timestamp **idêntico** — com `$gt` a rajada seguinte ao cursor sumiria da tela. Pelo mesmo motivo, todo sort de histórico desempata por `_id` (`[("timestamp", 1), ("_id", 1)]`), senão a ordem das mensagens de uma rajada é indefinida
- **Um único `httpx.AsyncClient`** no processo (`wuzapi_client._get_client()`), fechado no shutdown. Um client por chamada pagava handshake novo em cada mensagem enviada e em cada probe de saúde
- O editor de fluxos entra por `React.lazy`: o React Flow é a dependência mais pesada do frontend e só ele a usa. Bundle inicial: 155 kB gzip (era 227 kB)

## Pendências conhecidas (Next Action Items da última entrega)

1. **[PRIORIDADE ALTA] Multi-conexão no frontend**: o schema (`whatsapp_connections`) já suporta múltiplas conexões por tenant, mas a UI ainda assume uma única conexão. Precisa: lista de conexões na tela de WhatsApp, seletor de conexão nos filtros da Central de Atendimento, departamento padrão configurável por conexão (já existe no backend, falta expor bem no front para múltiplas).
2. **Reabertura configurável de conversas finalizadas**: hoje sempre reabre em `bot`. Adicionar `reopen_mode` (`bot` ou `aguardando`), configurável por bot ou por departamento.
3. **WebSocket no lugar do polling de 3s**: continua valendo, mas ficou bem menos urgente — o ciclo de polling era o que custava caro, e o `?since=` mais o `last_message` desnormalizado tiraram o grosso do custo de cada ciclo.

---

## Convenções e regras importantes a manter

- **Nunca** deixar uma query no backend sem filtro de `tenant_id` explícito — é a única barreira de isolamento entre empresas, já que o Mongo não tem RLS nativo.
- O motor de execução de fluxos é único e compartilhado entre o modo "Testar" (simulado) e o fluxo real de mensagens — não duplicar lógica.
- **Nunca** inserir em `messages_log` direto: usar `flow_runtime.log_message()`, que grava a mensagem e a prévia da sessão na mesma operação. Um insert avulso deixa a lista de conversas mostrando mensagem velha.
- Rotas administrativas (admin/super admin) devem retornar 403 de verdade para usuários sem permissão, não só esconder na UI — validar sempre no backend.
- Toda ação de impersonation do Super Admin deve ficar registrada em `impersonation_log`.
- Design já definido (Swiss Brutalist / Grid Borders) — manter consistência visual ao adicionar novas telas.
