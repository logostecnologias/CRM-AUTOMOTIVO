// Node type metadata, colors, icons, default data
import {
  Play, ChatText, ListNumbers, Database, GitBranch, Image,
  Clock, Cloud, UserSwitch, StopCircle, ArrowsLeftRight,
} from "@phosphor-icons/react";

export const NODE_TYPES = {
  start: {
    label: "Início", color: "#10B981", icon: Play,
    outputs: [{ id: "out", label: "Saída" }],
    hasTarget: false,
    default: { label: "Início", trigger: "first_message" },
  },
  text: {
    label: "Mensagem", color: "#F8F9FA", textColor: "#0F172A", icon: ChatText,
    outputs: [{ id: "out", label: "Saída" }],
    default: { label: "Enviar Mensagem", text: "Olá, {nome_contato}! 👋" },
  },
  menu: {
    label: "Menu", color: "#2563EB", textColor: "#FFFFFF", icon: ListNumbers,
    outputs: [],  // dynamic
    default: {
      label: "Menu de Opções",
      text: "Escolha uma opção:",
      options: [
        { id: "opt_0", label: "Opção 1" },
        { id: "opt_1", label: "Opção 2" },
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
  "media", "delay", "webhook", "human_handoff", "transfer_bot", "end",
];
