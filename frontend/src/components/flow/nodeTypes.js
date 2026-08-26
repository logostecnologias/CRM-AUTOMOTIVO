// Node type metadata, colors, icons, default data
//
// Os tetos e a validação do Menu interativo abaixo são uma cópia deliberada de
// `backend/flow_engine.py` (validar_menu) — os dois têm que dizer o mesmo
// número. Aqui servem para avisar enquanto a pessoa edita; lá são a barreira
// que recusa a publicação. Ao mexer num, mexer no outro.
import {
  Play, ChatText, ListNumbers, Database, GitBranch, Image,
  Clock, Cloud, UserSwitch, StopCircle, ArrowsLeftRight, CalendarCheck,
} from "@phosphor-icons/react";

// Gatilhos do nó de Início.
//
// O valor (`first_message`, `keyword`, `no_response`) é chave do motor de
// fluxos e continua sendo o que vai para o banco. A lista mora aqui porque o
// mesmo rótulo é usado em três telas — o cartão no canvas, o painel de
// configuração e a lista de bots — e antes o cartão mostrava a chave crua.
export const GATILHOS = [
  { valor: "first_message", label: "Primeira mensagem",
    opcao: "Primeira mensagem do contato" },
  { valor: "keyword", label: "Palavra-chave",
    opcao: "Palavra-chave específica" },
  { valor: "no_response", label: "Sem resposta",
    opcao: "Sem resposta há X tempo" },
];

export function rotuloGatilho(valor) {
  const g = GATILHOS.find((x) => x.valor === (valor || "first_message"));
  return g ? g.label : valor;
}

export const FORMATO_TEXTO = "texto";
export const FORMATO_BOTOES = "botoes";
export const FORMATO_LISTA = "lista";

export const MENU_FORMATOS = [
  { valor: FORMATO_TEXTO, label: "Texto numerado",
    ajuda: "Lista de opções no corpo da mensagem. O contato responde digitando o número. Funciona em qualquer aparelho." },
  { valor: FORMATO_BOTOES, label: "Botões de resposta rápida",
    ajuda: "Até 3 opções, cada uma como um botão sob a mensagem. O contato toca em vez de digitar." },
  { valor: FORMATO_LISTA, label: "Lista de opções",
    ajuda: "Até 10 opções dentro de um menu que abre por um botão. Cada opção pode ter uma linha de descrição." },
];

export const LIMITES_MENU = {
  botoes: 3,
  itensLista: 10,
  rotuloBotao: 20,
  rotuloItem: 24,
  descItem: 72,
  botaoLista: 20,
};

// Espelho de `flow_engine.validar_menu`. Devolve os problemas que impediriam a
// mensagem interativa de chegar: o WhatsApp descarta a mensagem em silêncio
// nesses casos, e um Menu descartado trava a conversa esperando uma resposta
// que o contato nunca foi convidado a dar.
export function validarMenu(data = {}) {
  const formato = data.formato || FORMATO_TEXTO;
  if (formato === FORMATO_TEXTO) return [];

  const opcoes = data.options || [];
  const problemas = [];
  if (!opcoes.length) problemas.push("menu interativo sem nenhuma opção");

  const longos = (limite) =>
    opcoes.map((o) => o.label || "").filter((l) => l.length > limite);

  if (formato === FORMATO_BOTOES) {
    if (opcoes.length > LIMITES_MENU.botoes) {
      problemas.push(
        `botões aceitam no máximo ${LIMITES_MENU.botoes} opções (este menu tem ${opcoes.length}) — use o formato Lista`);
    }
    const passou = longos(LIMITES_MENU.rotuloBotao);
    if (passou.length) {
      problemas.push(`rótulo de botão passa de ${LIMITES_MENU.rotuloBotao} caracteres: ${passou.join(", ")}`);
    }
  } else if (formato === FORMATO_LISTA) {
    if (opcoes.length > LIMITES_MENU.itensLista) {
      problemas.push(
        `uma lista aceita no máximo ${LIMITES_MENU.itensLista} opções (este menu tem ${opcoes.length})`);
    }
    if (!(data.botao_texto || "").trim()) {
      problemas.push("a lista precisa do texto do botão que abre as opções");
    }
    const passou = longos(LIMITES_MENU.rotuloItem);
    if (passou.length) {
      problemas.push(`opção de lista passa de ${LIMITES_MENU.rotuloItem} caracteres: ${passou.join(", ")}`);
    }
  }
  return problemas;
}

// --- Nó de Agendamento -----------------------------------------------------
//
// Espelho de `backend/agenda_flow.validar`, pelo mesmo motivo que `validarMenu`
// espelha `flow_engine.validar_menu`: aqui avisa enquanto a pessoa edita, lá é
// a barreira que recusa a publicação. Mexer num é mexer no outro.

export const MODOS_PROFISSIONAL = [
  { valor: "qualquer", label: "A empresa escolhe quem estiver livre",
    ajuda: "O contato não escolhe profissional. Menos uma pergunta na conversa: use quando tanto faz quem atende." },
  { valor: "perguntar", label: "O contato escolhe",
    ajuda: "Mostra a lista de profissionais que atendem o serviço. Com um só cadastrado, a pergunta é pulada." },
  { valor: "fixo", label: "Sempre o mesmo profissional",
    ajuda: "Todo agendamento por este nó vai para quem você escolher abaixo." },
];

export const FORMATOS_AGENDA = [
  { valor: "lista", label: "Lista de opções",
    ajuda: "Até 10 opções num menu que abre por um botão. É o formato certo para dias e horários." },
  { valor: "texto", label: "Texto numerado",
    ajuda: "As opções no corpo da mensagem; o contato digita o número. Funciona em qualquer aparelho." },
];

export const MAX_DIAS_AGENDA = 10;

export function validarAgendamento(data = {}) {
  const problemas = [];
  const modo = data.modo_profissional || "qualquer";
  if (modo === "fixo" && !(data.resource_id || "").trim()) {
    problemas.push("o modo \"sempre o mesmo profissional\" exige escolher qual profissional");
  }
  const dias = data.dias_oferecidos;
  if (dias !== undefined && dias !== null && !(dias >= 1 && dias <= MAX_DIAS_AGENDA)) {
    problemas.push(`o nó pode oferecer de 1 a ${MAX_DIAS_AGENDA} dias`);
  }
  if ((data.formato || "lista") === "botoes") {
    // Três botões não comportam uma lista de horários: a degradação para texto
    // aconteceria em quase toda pergunta, e o formato configurado nunca sairia.
    problemas.push("agendamento não cabe em botões: use Lista de opções ou Texto numerado");
  }
  return problemas;
}

export const NODE_TYPES = {
  start: {
    label: "Início", color: "#10B981", icon: Play,
    outputs: [{ id: "out", label: "Saída" }],
    hasTarget: false,
    default: { label: "Início", trigger: "first_message" },
  },
  text: {
    // Unico no cuja cor de identidade e "nenhuma": era o quase-branco do fundo
    // claro, que no tema escuro viraria uma faixa branca no topo de cada no de
    // mensagem — e mensagem e o no mais usado. Vai de token.
    label: "Mensagem", color: "var(--surface-3)", textColor: "var(--text)", icon: ChatText,
    outputs: [{ id: "out", label: "Saída" }],
    default: { label: "Enviar Mensagem", text: "Olá, {nome_contato}! 👋" },
  },
  menu: {
    label: "Menu", color: "#2563EB", textColor: "#FFFFFF", icon: ListNumbers,
    outputs: [],  // dynamic
    default: {
      label: "Menu de Opções",
      text: "Escolha uma opção:",
      // Formato de apresentação no WhatsApp. `texto` é o comportamento
      // original (lista numerada, o contato digita o número) e continua sendo
      // o padrão: nó de Menu sem `formato` é de um fluxo publicado antes desta
      // versão, e tem que se comportar igual.
      formato: FORMATO_TEXTO,
      titulo: "",
      rodape: "",
      botao_texto: "Ver opções",
      titulo_secao: "",
      options: [
        { id: "opt_0", label: "Opção 1", descricao: "" },
        { id: "opt_1", label: "Opção 2", descricao: "" },
      ],
      invalid_message: "Resposta inválida, tente novamente.",
    },
  },
  save_variable: {
    label: "Salvar Variável", color: "#F97316", textColor: "#FFFFFF", icon: Database,
    outputs: [{ id: "out", label: "Saída" }],
    default: { label: "Salvar Variável", variable_name: "resposta", source: "last_response", value: "" },
  },
  condition: {
    label: "Condição", color: "#FDE047", icon: GitBranch,
    outputs: [{ id: "true", label: "Verdadeiro" }, { id: "false", label: "Falso" }],
    default: { label: "Se / Então", variable_name: "resposta", operator: "equals", value: "" },
  },
  media: {
    label: "Mídia", color: "#EC4899", textColor: "#FFFFFF", icon: Image,
    outputs: [{ id: "out", label: "Saída" }],
    default: { label: "Enviar Mídia", media_type: "image", url: "", caption: "" },
  },
  delay: {
    label: "Aguardar", color: "#78716C", textColor: "#FFFFFF", icon: Clock,
    outputs: [{ id: "out", label: "Saída" }],
    default: { label: "Aguardar", seconds: 2 },
  },
  webhook: {
    label: "Webhook", color: "#0F172A", textColor: "#FFFFFF", icon: Cloud,
    outputs: [{ id: "success", label: "Sucesso" }, { id: "error", label: "Erro" }],
    default: { label: "Chamar API", method: "GET", url: "https://", body: {}, response_var: "webhook_response" },
  },
  schedule: {
    label: "Agendamento", color: "#0D9488", textColor: "#FFFFFF", icon: CalendarCheck,
    outputs: [{ id: "agendado", label: "Agendou" }, { id: "nao_agendado", label: "Não agendou" }],
    default: {
      label: "Agendar horário",
      // Vazio = pergunta ao contato qual serviço. Com um serviço só cadastrado,
      // a pergunta é pulada de qualquer forma.
      service_id: "",
      modo_profissional: "qualquer",
      resource_id: "",
      dias_oferecidos: 5,
      formato: "lista",
      botao_texto: "Ver opções",
      texto_servico: "",
      texto_profissional: "",
      texto_dia: "",
      texto_hora: "",
      texto_confirmado: "",
      texto_sem_horario: "",
    },
  },
  human_handoff: {
    label: "Atendimento Humano", color: "#EF4444", textColor: "#FFFFFF", icon: UserSwitch,
    outputs: [],
    default: { label: "Transferir para Humano", department_id: "", department_name: "" },
  },
  transfer_bot: {
    label: "Transferir para Bot", color: "#8B5CF6", textColor: "#FFFFFF", icon: ArrowsLeftRight,
    outputs: [],
    default: { label: "Transferir para outro Bot", target_bot_id: "" },
  },
  end: {
    label: "Fim", color: "#475569", textColor: "#FFFFFF", icon: StopCircle,
    outputs: [],
    default: { label: "Encerrar Fluxo" },
  },
};

export const NODE_ORDER = [
  "start", "text", "menu", "save_variable", "condition",
  "media", "delay", "webhook", "schedule", "human_handoff", "transfer_bot", "end",
];
