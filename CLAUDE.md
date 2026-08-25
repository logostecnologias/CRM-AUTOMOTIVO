# ZappZen — Contexto do Projeto

## Visão Geral

ZappZen é uma plataforma **SaaS multi-tenant** de criação de chatbots para WhatsApp, com um **editor visual de fluxos** (tipo n8n/Typebot: retângulos conectados por linhas) e uma **Central de Atendimento** unificada para múltiplas conexões de WhatsApp.

O desenvolvimento continua localmente via **Claude Code**.

---

## Stack Técnica

- **Backend**: FastAPI (Python)
- **Banco de dados**: MongoDB (sem isolamento nativo de tenant — **todo filtro por `tenant_id` é responsabilidade da aplicação**, aplicado em toda query sensível, sem exceção)
- **Frontend**: React + `@xyflow/react` (React Flow) para o editor visual
- **Design**: **Suave arredondado** com tema claro e escuro, tudo saindo de tokens em `frontend/src/index.css` (era Swiss Brutalist / Grid Borders até 25/08/2026). Fontes Cabinet Grotesk + IBM Plex Sans, UI 100% em português, elementos com `data-testid`
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

### Campanhas de disparo (envio ativo)
- **É o primeiro envio ativo do sistema.** Todo o resto era reativo: mensagem só saía dentro de uma conversa nascida de um webhook de entrada. Campanha inverte isso, e é daí que vêm quase todas as decisões deste módulo
- `campaigns` (a campanha) + `campaign_recipients` (**um documento por destinatário**). O estado por destinatário é o que permite retomar exatamente de onde parou depois de um restart — e é de onde saem as métricas, sem varrer `messages_log`
- **A sessão é criada antes do envio** (`campaigns.ensure_session`), nunca depois. Um disparo que só chamasse `wuzapi.send_text` entregaria a mensagem e deixaria a resposta do contato cair numa conversa nova, sem vínculo: o atendente veria "quanto custa?" sem saber o que foi oferecido. Conversa aberta do mesmo contato na mesma conexão é reaproveitada — abrir uma segunda dividiria o histórico do número em dois lugares
- A conversa de campanha nasce em `status_atendimento = 'bot'`, **não** em `aguardando`: a maioria dos disparados não responde, e jogar o público inteiro na fila encheria a Central de conversas em que ninguém falou nada. Ela entra na fila quando (e se) o contato responder
- `aguardando_primeira_resposta` na sessão é o sinal que faz a resposta funcionar. A conversa foi aberta por nós, então não há fluxo em andamento nem menu esperando; sem essa marca, o caminho de entrada encontraria uma sessão `ativa` sem `awaiting`, **não faria nada**, e a resposta ficaria no histórico sem bot e sem atendente. `resposta_modo` decide o destino: `aguardando` (fila humana) ou `bot` (roda o fluxo do bot escolhido, do nó Início)
- **Cadência com jitter** (`campaign_runner`): uma task por campanha, um envio por vez, com pausa de `60/por_minuto` multiplicada por um fator aleatório. Mandar tudo o mais rápido possível é o caminho conhecido para o número ser bloqueado — e o número é do cliente. Intervalo exato é assinatura de robô, daí o jitter
- **O claim do destinatário é atômico** (`find_one_and_update` de `pendente` → `enviando`). Com dois processos no ar, a janela entre ler e marcar é suficiente para o mesmo contato receber a campanha duas vezes. Destinatário preso em `enviando` há mais de 15 min volta para a fila — é o resto de um processo que morreu no meio do envio
- **Conexão desconectada pausa a campanha**, não queima o público: marcar 1.800 contatos como "falha" porque o QR caiu tornaria a campanha inaproveitável
- O público é **congelado** em `campaign_recipients` no início do disparo, não resolvido a cada envio: uma campanha "todos os contatos" rodando por uma hora incluiria quem chegou no meio, e o total na tela nunca fecharia com o enviado. Materializar é idempotente, e é isso que torna "retomar" seguro
- **Opt-out** (`contacts.opt_out` + `opt_out_em`): o contato sai respondendo `SAIR`/`PARAR`/`DESCADASTRAR`. O cotejo é com a mensagem **inteira** normalizada (sem acento/pontuação), nunca "contém" — "quero cancelar meu pedido" é atendimento, e tirar esse cliente da base por engano é pior que exigir a palavra exata. Vale para qualquer mensagem, não só resposta de campanha, e não interrompe o atendimento
- `opt_out` é filtrado em `audience_query`, não na hora do envio: assim a prévia que a tela mostra é o mesmo número que vai receber
- `agendada_para` é **normalizado na entrada** para o formato de `_now()`. O supervisor compara como string, e o navegador manda `…Z` enquanto o Python gera `…+00:00` — dois textos que não se ordenam entre si
- `canal: "wuzapi"` já é gravado em cada campanha. É o campo que decide por onde ela sai quando a Cloud API oficial entrar, sem migrar as antigas
- **Teto por plano**: `max_disparos_mes` conta mensagem **entregue** no mês (`campaign_recipients.status = enviado`), não campanha criada — é a mensagem que custa. Vazio ou 0 = ilimitado. Não entra na tabela `LIMITS` do `plan_limits.py` porque aquele helper conta documentos por tenant, e este limite é por janela de tempo
- Teto de público por campanha: `MAX_PUBLICO` (20.000). Acima disso a resposta diz o número exato em vez de truncar calado
- Contatos ganharam `tags` (público por etiqueta) e a tela ficou paginada com busca. A lista antiga devolvia 500 documentos crus sem filtro — inútil para escolher público
- **A tela avisa do risco.** Disparo em volume por API não oficial derruba número de WhatsApp, e o prejuízo é do cliente. O aviso fica fixo no topo da tela de Campanhas, não escondido em documentação


### Ficha de contato
- O registro deixou de ter 4 campos úteis: além de nome/número/etiquetas/opt-out, agora tem `email`, `empresa`, `cargo`, `origem`, `responsavel_id` e `campos` (personalizados). `origem` é preenchida na criação (`mensagem recebida`, `cadastro manual`) — depois não há como saber por onde o contato entrou
- **Campos personalizados** em duas partes: `contact_field_defs` (definição por empresa: nome, tipo `texto|numero|data|selecao`, opções, ordem) e `contacts.campos` (`{id_da_definição: valor}`). Valor de definição apagada é **descartado** em silêncio, não recusado — apagar um campo não pode impedir que a ficha volte a ser salva; já valor de tipo errado é recusado, senão "abc" num campo numérico quebraria depois qualquer filtro que dependa dele. Apagar a definição limpa o valor de todas as fichas (`$unset` em `campos.<id>`)
- `_para_numero` aceita `1250.5`, `1250,50` **e** `1.250,50`: a tela é pt-BR (ponto de milhar, vírgula decimal) mas o `<input type="number">` entrega ponto decimal. Um `replace(",", ".")` cru virava `1.250.50` e recusava valor válido
- **Notas em coleção própria** (`contact_notes`), não em array dentro do contato: a lista cresce sem teto e o documento do contato é lido a cada mensagem recebida. O sort desempata por `_id` — mesma razão do histórico de mensagens: duas notas seguidas nascem com `created_at` idêntico (resolução do relógio), e só com o timestamp a nota nova aparecia embaixo da anterior
- `GET /contacts/{id}` devolve a ficha inteira numa chamada (dados, campos casados com as definições, notas, conversas, campanhas recebidas, resumo). Seis requests para montar uma tela custariam seis idas e voltas pelo túnel SSH onde cabem seis consultas na mesma
- `POST /contacts` normaliza o número para dígitos e **recusa duplicado com 409**: o número é a identidade do contato em todo o sistema, e um duplicado partiria a ficha em duas
- **`outbound.py`** nasceu aqui: o bootstrap de sessão saiu de `campaigns.py` quando a ficha ganhou envio, porque o conceito é "a plataforma escreveu primeiro", não "campanha". `campaigns.ensure_session` passou a delegar. A diferença entre os dois está em quem assume: campanha nasce sem dono (em `bot`, entra na fila só se o contato responder); mensagem da ficha nasce **com** dono — `em_atendimento` no nome de quem clicou, `status = aguardando_humano` para o motor de fluxos não tentar responder por cima, e sem `aguardando_primeira_resposta` (já tem quem responda)
- `POST /contacts/{id}/send` **reusa `flow_runtime.send_human_message`**, o mesmo envio do painel de atendimento — não uma segunda implementação. É o que garante o prefixo com o nome de quem enviou, o `log_message` (prévia junto) e que falha de entrega não apareça como enviada
- Sem conexão escolhida, o envio sai pela **conexão da última conversa do contato**: ele já conhece aquele número, e trocar o remetente no meio de um assunto parece outra empresa falando
- `opt_out` **não** bloqueia mensagem direta: é recusa de campanha, e isto é uma pessoa escrevendo para outra. A ficha mostra o aviso em vez de impedir


### Funil de negócios
- O Kanban da Central mostra **estado de conversa**; isso nunca foi funil — não tem valor, previsão, dono nem desfecho. Negócio é outra entidade (`deals`), e é dela que saem as contas que uma agência cobra: conversão, ticket médio, ciclo de venda e retorno por campanha
- **Etapas embutidas no funil** (`pipelines.etapas`), não em coleção separada: são poucas, ordenadas, e nunca lidas sem o funil. Cada etapa tem `tipo` (`aberta|ganho|perdido`) — é o `tipo` que diz ao sistema quando o negócio fechou, não o nome dela
- **`status` é gravado no negócio mesmo sendo derivado da etapa.** Duplicação proposital: "abertos" e "ganhos no mês" são as consultas quentes, e não há como indexar valor que mora dentro de um array de outra coleção. Quem muda de etapa passa por `deals.aplicar_etapa`, que é o único lugar que mexe nos três campos que precisam concordar (`etapa_id`, `status`, `fechado_em`) — mover para "Ganho" sem gravar a data tiraria o negócio de todo relatório de ciclo, e voltar de "Perdido" sem limpá-la o manteria contado como fechado para sempre
- **`ciclo_dias` é gravado no fechamento**, não calculado no relatório: o `$avg` do Mongo não subtrai duas datas guardadas como string ISO, e ISO é o formato do resto do sistema
- **Toda mudança gera evento** (`deal_events`): sem histórico não existe ciclo de venda nem tempo por etapa, e "por que perdemos" viraria opinião. `registrar_evento` nunca levanta — perder um log é ruim, travar a venda porque o log falhou é pior. Salvar o mesmo valor não gera evento, para o histórico não encher de linhas iguais
- **Remover etapa que ainda tem negócio é recusado com 409**, dizendo quantos são; ou se passa `mover_para`. Apagar em silêncio deixaria os negócios apontando para uma etapa inexistente e eles desapareceriam do quadro sem nunca terem sido ganhos nem perdidos. Renomear preserva o `id` — e por isso preserva o vínculo
- **Atribuição de origem** (`deals.atribuir_origem`): sem campanha nem sessão informadas, procura a conversa mais recente do contato que nasceu de um disparo. É o vínculo que permite dizer "esta campanha gerou R$ 40 mil fechados" em vez de "teve boa taxa de resposta", que não paga ninguém
- **Conversão é sobre negócios decididos** (ganhos ÷ (ganhos + perdidos)), não sobre o total: contar os abertos como perda faria a taxa despencar só porque o funil está cheio. A janela dos relatórios filtra por `fechado_em`, não por criação — "ganhamos R$ X em agosto" é sobre o que fechou em agosto
- **Teto de `POR_COLUNA` (100) cartões por coluna**, com o total real ao lado (`n`) e `truncada`/`valor_parcial` para a tela dizer "mostrando 100 de 400". Com filtro ativo o `n` é recontado em vez de usar `len(cartoes)`, senão o corte ficaria invisível
- Os totais das colunas saem de **uma agregação sobre a coluna inteira** (`deals.por_etapa`), não da soma dos cartões devolvidos: somar o que veio mostraria R$ 30 mil numa coluna de R$ 200 mil
- **Arrastar usa o drag-and-drop nativo do HTML5**, sem biblioteca: o projeto não tem nenhuma de dnd e o caso é mover cartão entre colunas. Soltar numa coluna de `perdido` abre o diálogo de motivo antes de gravar — deixar para depois é garantir relatório de motivos vazio
- O item "CRM" do menu passou a se chamar **"Conversas"**, e "Funil" é a tela nova. O rótulo antigo prometia o que a tela não entregava


### Atividades e follow-up
- Ficha e funil guardam o que **já** aconteceu; atividade guarda o que ainda precisa acontecer. Sem isso o próximo passo mora na cabeça do vendedor, e o CRM vira cadastro morto
- **"Atrasada" não é campo, é comparação.** O estado gravado é só `concluida_em` (nulo = pendente); atrasada é `pendente e vence_em < agora`, calculado na leitura (`atividades.com_atraso`). Gravar um status exigiria varredura periódica para virar a chave de cada atividade na hora certa — trabalho de fundo para produzir o que uma comparação de data já responde
- **Os cortes de "hoje" e "semana" vêm do navegador**, não do servidor: "hoje" em UTC-3 começa três horas antes de "hoje" em UTC, e o servidor não sabe o fuso de quem abriu a tela. O backend só filtra por `de`/`ate`. Calcular no servidor faria a agenda de fim de tarde mostrar as tarefas de amanhã
- **O follow-up é encadeado na conclusão**: `POST /activities/{id}/complete` aceita `proxima` no mesmo pedido, e a nova herda contato, negócio e responsável, guardando `origem_id`. É ali que a pessoa está pensando no assunto — "depois eu agendo" é como se perde a venda
- A próxima é **validada e montada antes** de fechar a atual. Na ordem inversa, uma data inválida no follow-up deixava a atividade concluída e devolvia erro: quem tentasse de novo levava 409 e ficava sem o próximo passo, que era o motivo do clique
- Atividade **sem responsável não aparece na agenda de ninguém**, então `responsavel_id` cai em quem criou (ou em quem editou, se o campo for limpo). É assim que uma tarefa deixa de desaparecer
- **`sem_proximo_passo` no cartão do quadro** (`atividades.negocios_sem_proximo_passo`): cartão sem atividade pendente é venda parada sem ninguém ter decidido pará-la. Sai de uma agregação só sobre os ids em tela — uma consulta por cartão custaria uma ida ao banco por negócio. Negócio já fechado não é cobrado
- O resumo da agenda (atrasadas/hoje/semana/pendentes) sai de **uma agregação com `$cond`**, não de quatro contagens: o que domina é a ida e volta pelo túnel SSH
- Excluir atividade **não apaga a corrente** de follow-up: as seguintes são compromissos já assumidos, só perdem o `origem_id`
- Selo de atrasadas no menu com polling de **60s**, não os 3s da fila: atividade vence em hora marcada, e quem está atrasado às 14:00 continua atrasado às 14:01
- **Lembrete fora do sistema não existe** (push, e-mail, WhatsApp para o responsável). O aviso é in-app: selo no menu e aba "Atrasadas". Usuário não tem telefone no schema, só e-mail

### Datas vindas do cliente (`datas.py`)
- `para_utc` é para **instante** (`agendada_para`, `vence_em`): o navegador manda `…Z` e o Python gera `…+00:00`, dois textos para o mesmo momento que não se ordenam entre si — e esses campos são comparados como string no banco
- `valida_data` é para **dia do calendário** (`previsao_fechamento`, campo personalizado de data): normalizar seria um erro, porque `2026-09-30` viraria `2026-09-30T00:00:00+00:00` e, exibido em UTC-3, apareceria como dia 29. Prazo não pode andar para trás por causa de fuso
- A distinção é o motivo de existir o módulo: a mesma checagem estava em três lugares e as três versões divergiam exatamente nisso


### Importação e exportação de contatos (CSV)
- Era o que travava a base na prática: contato só nascia de mensagem recebida ou de cadastro um por um, então uma planilha de milhares de leads não tinha por onde entrar — e sem base, campanha e funil não têm o que processar
- **O número concentra o risco.** Uma planilha real traz `(11) 99999-8888`, `11999998888`, `+55 11 99999-8888` e `5511999998888` na mesma coluna. `normaliza_numero` aceita as quatro: 10/11 dígitos ganham o DDI, 12/13 passam como estão. **Nunca inventa dígito** — acrescentar o nono num número de 8 manda a mensagem para outra pessoa, e um fixo tem a mesma forma de um celular antigo. Linha com número irreconhecível é recusada com o motivo, não "corrigida"
- **Importação em dois passos.** `dry_run=True` (o padrão) não grava nada: devolve o mapeamento sugerido, uma amostra do que entraria e os números (novos, já existentes, com erro). Importar às cegas e descobrir depois que a coluna do telefone estava errada é o que esse passo evita
- O arquivo sobe duas vezes (prévia e confirmação) **de propósito**: guardar o conteúdo entre as chamadas criaria estado temporário para expirar e limpar, e um CSV é texto — reenviar é barato
- **O mapeamento é sugerido, nunca imposto**: sinônimos por coluna (`celular`/`telefone`/`whatsapp` → número) cotejados por texto normalizado, e campo personalizado casado pelo nome da definição. Coluna não reconhecida fica sem alvo em vez de ser adivinhada. Um alvo por coluna: com "Telefone" e "Celular" na mesma planilha, a segunda sobrescreveria a primeira
- **Nada é ignorado em silêncio**: cada linha recusada volta com o número da linha **do arquivo** (cabeçalho conta como 1, que é o que o editor de planilha mostra) e o motivo; acima de `MAX_ERROS_DETALHADOS` o total omitido vai junto
- Erro numa linha derruba **a linha**, não a importação: `_valida_campos` é chamado por linha dentro de `try`, e um valor errado num campo personalizado não pode impedir as outras 5.000 de entrar
- **Duplicado por número dentro da empresa**, com `ignorar` (padrão) ou `atualizar`. Em `atualizar`, só sobrescreve o que vem preenchido — e **etiquetas são somadas, não substituídas**: a etiqueta posta na tela não pode ser apagada por uma planilha que simplesmente não a conhece
- Quem já existe é descoberto em **lotes de 1.000** e a escrita vai por `bulk_write` de 500 com `ordered=False`. Um `find_one` por linha seriam 20 mil idas e voltas pelo túnel SSH
- Teto de 10MB aplicado **durante** a leitura do upload, e 20.000 linhas por arquivo. Com o teto só no fim, um arquivo de 500MB já teria passado inteiro pela memória
- **Exportação em fluxo** (`StreamingResponse`), linha a linha do cursor — montar o arquivo inteiro na memória é justamente o que não se faz neste projeto. `;` como separador padrão e **BOM no início**, porque o destino real é o Excel em português: com `,` ele joga tudo numa coluna, e sem BOM os acentos viram símbolos. Campos personalizados entram como colunas, e os filtros da tela valem na exportação
- A exportação também é o mecanismo de LGPD para "o titular pediu os dados dele"


### Permissões: o que o atendente alcança
- `require_tenant_member` (em `auth.py`) é a dependência de "qualquer pessoa de dentro da empresa". Antes, tudo em `/contacts` exigia `require_tenant_admin`, o que deixava `responsavel_id` decorativo: quem era responsável por um contato não conseguia abrir a ficha dele
- **A equipe alcança a base toda**: listar/buscar contatos, abrir e editar ficha, anotar, cadastrar, enviar mensagem da ficha, ver campos personalizados, funil (quadro, negócios, relatório) e agenda de atividades
- **Continua só no admin** o que é configuração ou movimentação em massa: criar/editar/apagar campo personalizado, mexer nas etapas do funil, e **importar/exportar CSV**. Exportar a base inteira é o caminho mais curto para ela sair da empresa, e não é tarefa de quem atende
- Anotação: o atendente apaga só a própria (`autor_id` entra no filtro do delete); o admin apaga qualquer uma
- `accessible_connection_ids` saiu de `routes/atendimento.py` para `auth.py`, porque a regra vale em **toda** tela que envia mensagem, não só na Central. `_resolve_conexao` da ficha agora a consulta: o atendente só fala pelas conexões liberadas, e se a conversa aberta do contato está numa conexão fora do alcance dele o envio é **recusado com 403** em vez de abrir uma segunda conversa por outro número — que dividiria o histórico e furaria o escopo
- Cuidado ao testar barreira de permissão: chamar a função da rota direto **não** executa o `Depends`. O teste confere a guarda onde ela é declarada (inspecionando a assinatura do endpoint) além de exercitar as funções `require_*`

### Relatórios
- Três: **atendimento** e **campanhas** (`relatorios.py`) e o do **funil**, que já existia (`deals.metricas`). A tela junta os três em abas, reaproveitando `FunilMetricas`
- **Os tempos são calculados na leitura, não gravados** — e isso é o oposto do que o funil faz. `espera` é `assumido_em - aguardando_desde`, `atendimento` é `finalizado_em - assumido_em`, e o `$avg` do Mongo não subtrai duas datas em string ISO. No funil a solução foi gravar `ciclo_dias` no fechamento, porque o campo nasceu com a coleção; aqui existem conversas antigas, e um campo novo exigiria migrar a base toda para produzir um número que só é lido quando alguém abre um relatório. A conta sai em Python sobre as conversas da janela, com projeção de sete campos
- **Teto de `MAX_SESSOES` (50.000) por janela**, com **413** e o número exato quando estoura. Meia conta sem aviso é pior que recusar
- **`$substr` no ISO para a série por dia**: `"2026-08-24T18:30:00+00:00"` cortado em 10 dá `"2026-08-24"`, e agrupar por esse prefixo dá o dia sem converter data nenhuma — é o único lugar em que guardar data como texto vira vantagem
- **Média sempre acompanhada de p90**: uma fila com média de 4 min e p90 de 40 é uma operação com problema que a média esconde. Duração negativa (relógio, campo fora de ordem) entra como ausente em vez de puxar a média
- Com filtro de conexão/departamento, as mensagens são contadas pelos ids das conversas do recorte (em lotes de 1.000); sem filtro, direto por `tenant_id`, que o índice cobre. Misturar os dois mostraria o volume da empresa ao lado dos números de uma conexão só
- O relatório de campanhas junta `campaign_recipients` com `deals` ganhos: campanha que fechou negócio na janela aparece mesmo tendo disparado antes, senão a receita ficaria sem dono

### Gráficos
- **Paleta validada, não escolhida a olho**: no tema claro `#2563EB` (o azul que já existe no produto) + `#EA580C`. O `#F97316` do sistema **reprova** no contraste contra fundo claro (2,73:1); a variação escura passa. Separação para daltonismo ~31 (piso é 8)
- **O tema escuro tem par próprio, não o claro clareado**: `#3B82F6` + `#E06D1F`. Os passos claros **reprovam na banda de luminosidade** do tema escuro (o laranja `#EA580C` fica acima do teto), então o par escuro foi validado como conjunto contra a `--surface` escura. As cores saem de `var(--serie-1)`/`var(--serie-2)` — o SVG aceita `var()` em `fill`, então o gráfico troca de paleta sem re-render
- **Nunca eixo duplo.** Conversas e mensagens têm escalas diferentes, então são dois gráficos lado a lado. Eixo duplo inventa correlação que não está no dado
- Barra ≤ 24px com topo arredondado (raio 4) e base quadrada; vão de 2px entre segmentos empilhados, **descontado da própria barra** para o topo continuar marcando o total; grade fina e sólida (tracejado é ruído); rótulo de dia de tantos em tantos
- **Legenda sempre com duas séries ou mais**, e toda série tem alternativa em tabela (botão no canto) — identidade nunca depende só de cor
- A geometria vive em `components/reports/geometria.js`, **JS puro sem JSX**, justamente para ser conferida sem navegador: é a parte que erra em silêncio (barra fora da área, pilha passando do total, raio maior que a barra)


### Design: de brutalista para suave, e o tema escuro
- O desenho anterior era **Swiss Brutalist** de propósito: canto reto, borda preta de 1px e sombra dura deslocada 4px. Isto é a mesma tipografia e a mesma família de cor em versão suave — raio arredondado, borda cinza, sombra difusa. Trocado a pedido do cliente em 25/08/2026
- **O tema escuro só foi possível porque a cor saiu do JSX.** As ~1.100 classes cravadas (`bg-white`, `text-slate-500`, `border-slate-900`) não têm equivalente escuro: não existe "o `bg-white` do tema escuro". Elas viraram tokens (`bg-surface`, `text-ink-3`, `border-line`) definidos em `index.css` com um valor por tema. Sem essa troca, "adicionar tema escuro" seria editar cada tela de novo
- **O par claro/escuro de cada papel é escolhido junto — tema escuro não é o claro invertido.** O botão sólido é azul-marinho no claro e **azul** no escuro, porque um bloco quase preto sobre fundo escuro não se destaca de nada. O contraste dos 18 pares texto/fundo é conferido por script nos dois temas; dois reprovaram e foram corrigidos (`--text-4` a 2,56:1, que é o rótulo do eixo do gráfico, e `--danger` sobre a própria caixa de erro a 4,41:1) — os dois vinham de antes, mas quem define o token agora é este arquivo
- **`-solid` + `-fg` andam em par.** `bg-danger`/`bg-success` no escuro são cores **claras**: texto branco sobre elas dá ~2:1, o erro clássico de tema escuro feito por inversão. Preenchimento cheio (barra de alerta, selo verde) usa `bg-danger-solid` + `text-danger-fg`, que já vem com o texto certo para cada tema
- **O tema é aplicado antes do React montar** (`lib/tema.js`, chamado em `index.js`), não num `useEffect`: no efeito o primeiro quadro já teria sido pintado claro, e todo carregamento no escuro daria um flash branco
- **Três estados, não dois**: `claro`, `escuro` e `sistema` (o padrão). Quem já configurou o sistema no escuro não deveria configurar de novo aqui; e uma escolha explícita tem que ganhar do sistema depois, senão o botão não funcionaria para quem está no escuro e quer claro. A preferência é do **navegador**, não do usuário no banco: é configuração de dispositivo
- **Raio por tamanho do elemento, não uniforme**: 14px em cartão, 10px em controle, 6px em quadradinho de cor, pílula em selo e avatar, 2xl em bolha de conversa. Raio de 14px num quadrado de 16px viraria bolha
- **"Selecionado" não pode ser `border-line-strong` contra `border-line`.** A varredura mecânica mandou toda borda preta para o cinza forte, e nos estados de seleção isso apagou o sinal — os dois cinzas são quase iguais. Seleção passou a ser `border-info` (+ `ring-1 ring-info`) ou fundo sólido de marca. Foi o retrabalho manual mais extenso depois da varredura
- O `style` inline **não** passa por varredura de classe. Sobraram hexes no cabeçalho do Kanban e nas abas da Inbox, que ficariam brancos no tema escuro — hoje usam `var(--…)`
- Sonner pinta o próprio cartão a partir de `theme`: deixado em `"light"` ele desenharia toast claro no tema escuro, por cima das nossas variáveis

### Exclusão, anonimização e mesclagem de contato
- **Anonimizar é o padrão; apagar é a exceção.** A LGPD pede que o dado pessoal saia, não que o registro da transação desapareça. Um negócio de R$ 40 mil fechado em julho tem de continuar somando em julho — apagá-lo mudaria retroativamente um relatório que a empresa já entregou. Então o dado pessoal sai e o esqueleto fica: o negócio aponta para um contato que agora se chama "Contato removido"
- O **conteúdo das mensagens também é dado pessoal** (o contato digitou endereço, CPF, mandou foto de documento). Anonimizar redige o texto, apaga o arquivo de mídia do disco e marca `purged_at` — mesmo padrão do `media_retention`, para a bolha antiga mostrar "mídia expirada" em vez de imagem quebrada. A prévia na sessão (`last_message`) é redigida junto, senão o texto continuaria visível na lista de conversas
- `numero_whatsapp` vira `anon-<id>`, não vazio: é o que impede uma importação futura de recriar a ficha achando que o número está livre
- **`modo=apagar`** existe para contato de teste ou importação errada: leva conversas, mensagens, negócios e histórico, e a resposta diz exatamente o que foi. Só admin nas duas — é a operação mais destrutiva da base
- **Mesclar move, não copia.** Conversas, negócios, atividades, notas e disparos passam para a ficha que fica. Campo vazio herda o do secundário; campo preenchido **não** é sobrescrito, porque quem escolheu o principal escolheu os dados dele. Etiquetas são somadas e `opt_out` é a recusa mais restritiva das duas
- Se as duas fichas receberam a **mesma campanha**, o destinatário do secundário é descartado em vez de movido — mover deixaria o contato contado duas vezes na métrica daquela campanha
- **Duplicado não é detectado por número**: ele já é único por empresa (o cadastro recusa com 409). Duplicata real é a mesma pessoa por dois números, e o que resta para reconhecê-la é e-mail ou nome. Contato anonimizado fica fora da varredura — todos passam a ter o mesmo nome-marcador, e agrupar por ele juntaria pessoas diferentes

### Testes (`backend/tests/`)
- Rodam contra um **Mongo falso** (`tests/fakedb.py`), não contra o banco real: o Mongo do projeto está atrás de túnel SSH, e teste que só passa com o túnel de pé não roda em máquina nova. O falso cobre lógica — filtros, agregações, transições de estado, permissão. **Não** cobre índice aceito, tipo e o resultado exato de uma agregação real; isso continua exigindo teste de fumaça com o banco no ar
- **`_conectar_fake()` é chamado no início de cada teste, não só no import.** O pytest importa todos os módulos de teste no mesmo processo, e `get_db` (e o dublê de `wuzapi.send_text`) são atributos de módulo compartilhados: sem reaplicar, o último arquivo importado ficava com o banco de todos, e as mensagens "enviadas" caíam no gravador da outra suíte. Foi exatamente o que aconteceu na primeira execução
- Os helpers se chamam `etapa_*`, não `teste_*`: o prefixo `test` faz o pytest coletar a função como teste, e helper async coletado falha por não ter plugin de asyncio. Cada módulo expõe um `test_suite()` só, que roda as etapas em ordem
- As etapas de um módulo **compartilham** o estado do Mongo falso e continuam de onde a anterior parou. O `--dist loadscope` do `pytest.ini` fixa o módulo num worker só, e é isso que preserva a ordem sob paralelismo
- **Barreira de permissão não se testa chamando a função da rota**: o `Depends` não executa. O teste confere a guarda onde ela é declarada (inspecionando a assinatura do endpoint) além de exercitar as funções `require_*`
- A geometria do gráfico tem teste próprio no frontend (`geometria.test.js`, roda com `craco test`) — é a parte que erra em silêncio no navegador


### Desempenho (varredura de 2026-07-28)
- **Índices**: todos declarados numa tabela única (`INDEXES`, em `server.py`), não espalhados pelo startup — é lá que se responde "esta query está coberta?". Ao criar uma query quente nova, conferir a tabela. Faltavam os de `users.id` (usado em **toda** request autenticada, via `get_current_user`) e o de `conversation_sessions.status_atendimento` — o que existia cobria `status`, campo diferente, então a tela principal do produto nunca usava índice
- **`processed_messages` tem TTL de 7 dias**, indexado em `at`. Por isso `at` é gravado como `datetime` nativo e não como string ISO igual ao resto do sistema: o TTL do Mongo só age sobre campo do tipo `Date`. A coleção é só deduplicação da janela de retry do gateway — nada ali precisa sobreviver dias
- **`last_message` é desnormalizado na sessão**: `flow_runtime.log_message()` grava a mensagem e a prévia juntas, e **todo** caminho que escreve em `messages_log` passa por ela — é o que impede os dois lados de divergir. Antes a lista de conversas redescobria a última mensagem de cada uma com um aggregate que ordenava todas as mensagens das até 200 conversas em tela, a cada 3s, por atendente. Sessões anteriores à mudança são preenchidas por `migrations.py` (idempotente, roda no start)
- **`GET /atendimento/sessions/{id}?since=`** devolve só as mensagens novas. O corte é `$gte` e o front reconcilia por id: o relógio do Windows anda de ~15ms em ~15ms, então mensagens da mesma rajada nascem com timestamp **idêntico** — com `$gt` a rajada seguinte ao cursor sumiria da tela. Pelo mesmo motivo, todo sort de histórico desempata por `_id` (`[("timestamp", 1), ("_id", 1)]`), senão a ordem das mensagens de uma rajada é indefinida
- **Um único `httpx.AsyncClient`** no processo (`wuzapi_client._get_client()`), fechado no shutdown. Um client por chamada pagava handshake novo em cada mensagem enviada e em cada probe de saúde
- **Mídia nunca passa inteira pela memória.** No recebimento do upload, `media_store.store_stream()` grava em disco conforme chega, com o teto aplicado durante a escrita. No envio, `media_store.DataUriStream` lê o arquivo aos pedaços e codifica em base64 na hora, e `wuzapi_client._CorpoStream` costura o JSON em volta. O pico ficou **constante em ~3,4MB**, independente do tamanho do arquivo (antes era ~4× o arquivo: 64MB para um vídeo de 16MB). Três detalhes que não se pode mexer sem quebrar:
  - o corpo vai com **`Content-Length` explícito**, o que mantém o envio fora do `Transfer-Encoding: chunked` que o httpx usaria sozinho para um corpo iterável — não há garantia de que a WuzAPI aceite chunked. Por isso `DataUriStream.__len__` calcula o tamanho exato do base64 (`4 * ceil(n/3)`) sem montá-lo; errar por um byte corrompe a requisição inteira
  - `DataUriStream` reabre o arquivo a cada `async for`, porque `_request` tem retry e um gerador já consumido mandaria corpo vazio na segunda tentativa
  - o httpx só reconhece `bytes` e `str` como corpo pronto; **`bytearray` ele trata como stream síncrono**, e um `AsyncClient` recusa isso na hora do envio
- **Contagens são agrupadas, não uma consulta por linha**: `summary` (quatro colunas do Kanban), `unread-count` (soma no servidor, com as duas metades em paralelo) e a lista de empresas do super admin. O que dominava não era o volume, era a ida e volta até o banco — que aqui passa por túnel SSH
- O editor de fluxos entra por `React.lazy`: o React Flow é a dependência mais pesada do frontend e só ele a usa. Bundle inicial: 155 kB gzip (era 227 kB)

## Pendências conhecidas (Next Action Items da última entrega)

1. **Lembrete fora do sistema**: as atividades avisam dentro do app (selo no menu, aba "Atrasadas"), mas não há push, e-mail nem WhatsApp para o responsável no vencimento. Precisa de um worker no padrão `health_monitor` e de um canal — o usuário só tem e-mail no schema, não telefone.
2. **[PRIORIDADE ALTA] Multi-conexão no frontend**: o schema (`whatsapp_connections`) já suporta múltiplas conexões por tenant, mas a UI ainda assume uma única conexão. Precisa: lista de conexões na tela de WhatsApp, seletor de conexão nos filtros da Central de Atendimento, departamento padrão configurável por conexão (já existe no backend, falta expor bem no front para múltiplas).
3. **Reabertura configurável de conversas finalizadas**: hoje sempre reabre em `bot`. Adicionar `reopen_mode` (`bot` ou `aguardando`), configurável por bot ou por departamento.
4. **Campanha na Cloud API oficial**: o que existe hoje sai pela WuzAPI (protocolo não oficial), o que serve para volume baixo e público que já falou com a empresa. Disparo em escala exige Meta Cloud API com template HSM aprovado e opt-in registrado — o campo `canal` da campanha já existe para isso.
5. **Atribuição de campanha na Central**: a sessão carrega `campanha_id`, mas o Kanban/Inbox ainda não mostram de qual campanha a conversa veio. Falta só o selo na tela.
6. **Cobrança**: os planos têm `preco_mensal` e limites que já são aplicados, mas não existe gateway de pagamento, assinatura, fatura nem bloqueio por inadimplência. A cobrança hoje acontece fora do sistema. Depende de escolher o provedor antes de codar.
7. **Teste de fumaça contra o Mongo real**: a suíte roda contra um Mongo falso (`backend/tests/fakedb.py`). Índices aceitos, tipos e o resultado exato das agregações nunca foram exercitados no banco de verdade — o túnel SSH esteve fora durante toda esta série de entregas.
8. **Agentes de IA**: a tela segue placeholder, sem integração com LLM. O contexto necessário já existe (histórico indexado por sessão, ferramentas de CRM que viram tool calling). Autenticação por chave de API — assinatura de terceiro não é caminho compatível.
9. **WebSocket no lugar do polling de 3s**: continua valendo, mas ficou bem menos urgente — o ciclo de polling era o que custava caro, e o `?since=` mais o `last_message` desnormalizado tiraram o grosso do custo de cada ciclo.

---

## Convenções e regras importantes a manter

- **Nunca** deixar uma query no backend sem filtro de `tenant_id` explícito — é a única barreira de isolamento entre empresas, já que o Mongo não tem RLS nativo.
- O motor de execução de fluxos é único e compartilhado entre o modo "Testar" (simulado) e o fluxo real de mensagens — não duplicar lógica.
- **Nunca** inserir em `messages_log` direto: usar `flow_runtime.log_message()`, que grava a mensagem e a prévia da sessão na mesma operação. Um insert avulso deixa a lista de conversas mostrando mensagem velha.
- **Nunca** carregar um arquivo de mídia inteiro na memória (`read_bytes` + `to_data_uri`): usar `store_stream` no recebimento e `DataUriStream` no envio. O teto por tipo chega a 20MB, e isso é por envio simultâneo.
- `mime` vem do cliente e termina embutido num data URI dentro de um JSON: passar sempre por `media_store.sanitize_mime()`.
- **Nunca** disparar campanha sem passar por `campaign_recipients`: é o documento por destinatário que dá retomada, métrica e a garantia de não enviar duas vezes. Envio direto num laço perde tudo isso e não sobrevive a um restart.
- **Nunca** apagar contato com `delete_one` avulso: usar `contatos.anonimizar()` (padrão) ou `contatos.apagar()`. Um delete cru deixa conversas, negócios e mídia órfãos, e o texto das mensagens — que é dado pessoal — intacto no banco.
- **Nunca** usar `require_tenant_admin` para leitura/escrita da base de contatos, funil ou agenda: é `require_tenant_member`. Admin fica para configuração e exportação em massa.
- **Nunca** montar gráfico com dois eixos y, nem escolher cor de série a olho: rodar o validador de paleta.
- **Nunca** normalizar número de telefone à mão: usar `contatos_csv.normaliza_numero()`, e nunca completar dígito que não veio. Um número "corrigido" pertence a outra pessoa, e a mensagem sai.
- **Nunca** gravar um status "atrasada" em atividade: atraso é `vence_em < agora` calculado na leitura. Um campo persistido exigiria varredura periódica e ficaria errado entre uma varredura e outra.
- **Nunca** calcular limite de "hoje"/"semana" no servidor: o fuso é do navegador. O backend recebe `de`/`ate` e filtra.
- **Nunca** mudar a etapa de um negócio escrevendo `etapa_id` na mão: usar `deals.aplicar_etapa()`, que ajusta `status`, `fechado_em` e `motivo_perda` na mesma operação. Um `$set` avulso deixa negócio ganho fora dos relatórios ou negócio reaberto contado como fechado.
- **Nunca** criar `conversation_sessions` fora de `flow_runtime.handle_incoming_message` (entrada) ou `outbound.ensure_session` (envio ativo). Sessão montada à mão fica sem `aguardando_primeira_resposta` e a resposta do contato não aciona nem bot nem fila.
- **Nunca** montar público de campanha sem `campaigns.audience_query()`: é ele que exclui quem pediu para sair. Um filtro escrito à mão manda mensagem para quem se descadastrou.
- Rotas administrativas (admin/super admin) devem retornar 403 de verdade para usuários sem permissão, não só esconder na UI — validar sempre no backend.
- Toda ação de impersonation do Super Admin deve ficar registrada em `impersonation_log`.
- **Nunca** cravar cor no JSX (`bg-white`, `text-slate-500`, `border-slate-900`, hex em `style`): usar os tokens (`bg-surface`, `text-ink-3`, `border-line`, `var(--serie-1)`). Cor cravada não tem equivalente no tema escuro — é literalmente o que impediu o tema escuro de existir, e uma única classe esquecida vira painel branco no meio da tela escura.
- **Nunca** deixar borda completa sem raio, nem marcar "selecionado" só trocando `border-line` por `border-line-strong`: os dois cinzas são quase iguais e o sinal desaparece. Seleção é `border-info` (+ `ring-1 ring-info`) ou fundo sólido de marca.
- **Nunca** pôr texto branco sobre `bg-danger`/`bg-success`: no tema escuro esses tokens são claros. Preenchimento cheio usa o par `bg-*-solid` + `text-*-fg`, que já vem escolhido para os dois temas.
- Design já definido (suave arredondado, tokens claros/escuros) — manter consistência visual ao adicionar novas telas.
