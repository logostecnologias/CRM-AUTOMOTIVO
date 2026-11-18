# Análise do concorrente: CarMillion / CRMillion

Feita em 18/11/2026 a partir de 15 prints de uma demonstração do concorrente
(`app.crmillion.com.br`, `vendas.carmillionbr.com/multimarcas`) e das
anotações da reunião com o cliente (Kevin). Fonte: pasta
`LOGOS - CRM Automotivo/WhatsApp Unknown 2026-11-18 at 10.42.03`.

## O que o concorrente mostra

**IA no WhatsApp.** O lead chega pela OLX e a IA manda na hora: saudação com o
nome da loja, foto do carro com faixa de dados, o resumo
"Chevrolet – SPIN | 1.8 | branco | 2024 | 29.157 km | R$ 103.900" e já pergunta
como o cliente quer negociar (troca ou financiamento).
A IA é vendida em três planos: **Estagiária, Consultora e Diretora**. A
Diretora tem fluxo personalizado, IA conversacional, integração com estoque,
suporte prioritário, 5 follow-ups por lead e ligação ativa para leads dos
portais.

**CRM.**
- **Dashboard:** novos leads (em atendimento, finalizados), visitas agendadas
  (realizadas, taxa de realização), vendas (em negociação, perdidas, taxa de
  conversão). Gráficos de leads por canal, por origem e por vendedor.
- **Inbox único:** WhatsApp, Instagram, Messenger, OLX e outros portais.
  Filtros "Não lidas" e "Atribuídas para mim". Etiquetas no lead (À vista,
  Financiamento, Morno, Troca). Linha do tempo com notas internas, troca de
  atendente e mudanças de etapa. Muda a etapa do Kanban direto da conversa.
- **Leads:** tabela com nome, WhatsApp, data de entrada, carro de interesse,
  origem e etapa.
- **Funil Kanban de revenda:** Novo Lead, Qualificado, Visita Agendada,
  Financiamento em Análise, Repescagem, Carro indisponível, Cliente com
  restrição, Consórcio. O card mostra a temperatura (Frio, Morno, Quente), o
  carro com a placa e a forma de pagamento.
- **Estoque:** lista ou grade com foto, ano/modelo, km e preço. Ficha com
  galeria de 20 fotos, marca, modelo, versão, câmbio, combustível, motor,
  portas, cor, categoria, condição, localização e observações. Botão
  **"Encaminhar"**, que manda o carro para o cliente.
- **Agenda:** visitas, test drives, assinaturas, pós-venda e tarefas, com
  vendedor.
- **Configurações:** usuários por plano (Premium, 50 usuários), funções,
  equipes, integrações, templates, origens, tags, mensagens rápidas
  (`/documentos`, `/financiamento`, `/troca`…) e estoque.

## O que o cliente pediu (anotações)

- Cadastro de veículos simples e manual (marca, modelo, versão e todos os
  dados) que gere um **link de catálogo**.
- IA que entenda tudo e use **voz clonada** em áudios e ligações.
- Integração com os portais: o concorrente pega os leads por e-mail, e o
  cliente quer pegar **direto do chat do portal**.
- CRM ligado ao estoque, com a API oficial do WhatsApp e do Instagram.

## Preço do concorrente

| Item | Valor |
|---|---|
| Implementação (estoque, portais, fluxos, IA) | R$ 5.000 no Pix ou em 3x, ou R$ 2.500 no cartão |
| Mensalidade (300 leads, no boleto) | R$ 1.350 (preço base R$ 1.300) |
| Lead acima de 250 | + R$ 1 por lead |
| Usuário no CRM | R$ 35 cada (3 meses grátis) |
| Garantia | 45 dias |

O preço sobe com o volume de leads e com o nível da IA.

**Negociação com o Kevin.** Ele achou caro, e a implementação caiu para
R$ 4 mil. Também reclamou da mensalidade e do preço por usuário, e não queria
pagar o CRM todo mês. O vendedor ofereceu o ano inteiro por R$ 18.600 no
cartão ou R$ 16.300 no Pix. Kevin quer pagar R$ 13 mil.
Ele aceita a solução; o que trava o fechamento é o preço e o modelo de
cobrança.

## Comparação com o `crmauto` (18/11/2026)

| Recurso | Situação no `crmauto` |
|---|---|
| WhatsApp (API oficial + WuzAPI), inbox, atendimento | tem |
| Funil Kanban com etapas configuráveis | tem (falta o modelo pronto de revenda) |
| Agenda, atividades, dashboard, relatórios | tem |
| Agentes de IA, fluxos, campanhas, formulários | tem |
| Telefone (Twilio) | tem (sem voz clonada) |
| Envio da conversão de volta ao Meta | tem (o concorrente não mostra) |
| Estoque | parcial: só uma planilha que a IA consulta (`ai_estoque.py`). Não tem cadastro de veículo, fotos, ficha nem tela |
| Catálogo público por link | não tem |
| Encaminhar carro com foto e ficha no chat | não tem |
| Instagram e Messenger no inbox | não tem |
| Portais (OLX, Webmotors, iCarros, Mobiauto) | não tem |
| Carro de interesse e placa no lead/negociação, temperatura | não tem |
| Notas internas e mensagens rápidas | não encontrado |
| Planos Estagiária/Consultora/Diretora, follow-ups automáticos | parcial: existem planos e follow-up em atividades, mas não nesse formato |
| Voz clonada | não tem |

## Prioridades propostas

1. **Estoque de veículos de verdade:** cadastro manual com fotos e a ficha
   completa, substituindo a planilha. É a base do resto.
2. **Catálogo público por link** e botão **"Encaminhar"** (foto + ficha no
   WhatsApp). Passa a ser a fonte da IA, para a mensagem automática estilo
   Spin.
3. **Funil e lead automotivos:** etapas de revenda prontas, carro de interesse
   e placa na negociação, temperatura, forma de pagamento e troca.
4. **Notas internas e mensagens rápidas** no atendimento.
5. **Portais:** entrada de leads por e-mail primeiro, depois por API onde o
   portal permitir.
6. Instagram e Messenger, voz clonada e os planos de IA.

Os itens 1 a 4 não dependem de terceiros. Os itens 5 e 6 dependem de
credenciais e aprovação dos portais e da Meta.

## Decisões de design (18/11/2026)

- **Nome do produto:** AUTO.
- **Direção visual:** "Showroom": claro, silencioso, o carro como protagonista
  (foto grande, ficha técnica, placa no estilo Mercosul, selos discretos).
- **Só dois temas:** **Logos** (preto `#0E0E10`, laranja `#F77C20` só em
  detalhes, Poppins 600 nos títulos) e **R3** (petróleo `#00333D`, gelo
  `#F1EEEE`, lima `#D6E30F` só sobre o petróleo). ZappZen e Nexa saem.
- Nos dois: menu lateral escuro, botão principal na cor escura da marca, o
  acento nunca sobre branco (no claro, só a versão escurecida para texto),
  texto corrido em Inter, cor de "atenção" distinta do acento.
- Menu: Painel · Atendimento · **Pátio** (Estoque, Catálogo público) · Vendas ·
  Captação (Campanhas, Formulários, Portais) · Automação · Análise ·
  Configuração (recolhida).
- Referência visual: `mockup-showroom.png` (Logos) e `mockup-showroom-r3.png`
  (R3), na raiz do repositório.

**Cuidado:** o `crmauto` roda sobre o banco de produção. Recursos novos entram
em coleções novas, sem mudar a estrutura do que o cliente já usa.
