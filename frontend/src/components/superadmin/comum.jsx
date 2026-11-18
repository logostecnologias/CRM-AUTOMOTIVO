import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { useAuth } from "@/context/AuthContext";
import { MARCAS, valida as validaMarca } from "@/lib/marca";
import { haQuanto, plural } from "@/components/painel/Indicadores";

/**
 * Entrar na empresa (modo suporte), já na tela onde o problema se resolve.
 *
 * Os alertas da visão geral e as linhas da lista levam `destino`: entrar no
 * painel e navegar até o WhatsApp à mão é exatamente o caminho que o alerta
 * existe para encurtar.
 */
export function useEntrar() {
  const nav = useNavigate();
  const { refresh } = useAuth();
  return useAcao(async (empresa, destino = "/app") => {
    try {
      await api.post(`/admin/tenants/${empresa.id}/impersonate`);
      await refresh();
      nav(destino || "/app");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao entrar na empresa");
    }
  });
}

/** Título de um grupo de alertas da visão geral, pelo número de empresas. */
export function tituloDoAlerta(tipo, n) {
  const empresas = plural(n, "empresa", "empresas");
  switch (tipo) {
    case "conexoes": return `${empresas} com WhatsApp fora do ar`;
    case "agentes": return `${empresas} com agente de IA de chave recusada`;
    case "sem_whatsapp": return `${empresas} sem WhatsApp conectado`;
    case "parada": return `${empresas} sem mensagem há uma semana`;
    case "campanhas": return `${empresas} com campanha pausada`;
    case "acima_plano": return `${empresas} acima do limite do plano`;
    case "sem_plano": return `${empresas} sem plano`;
    default: return `${empresas}: ${tipo}`;
  }
}

/** O porquê do alerta, dito uma vez no grupo. */
export function porQue(tipo) {
  switch (tipo) {
    case "conexoes": return "Lembretes, campanhas e respostas por esse número não saem. O cliente pode nem ter percebido.";
    case "agentes": return "As conversas estão indo para a fila em vez de serem respondidas.";
    case "sem_whatsapp": return "Cadastro com mais de dois dias e implantação parada: sem número, nada entra nem sai.";
    case "parada": return "O WhatsApp está cadastrado, mas nada passou por ele em sete dias. É o sinal mais cedo de cancelamento.";
    case "campanhas": return "O disparo parou no meio e não volta sozinho.";
    case "acima_plano": return "O excedente continua funcionando, só a criação nova é barrada. Vale conversar sobre upgrade.";
    case "sem_plano": return "Sem plano, nenhum limite vale e a empresa não entra na receita.";
    default: return null;
  }
}

/** O detalhe de uma empresa dentro do grupo de alerta. */
export function detalheDaEmpresa(tipo, e) {
  switch (tipo) {
    case "conexoes": return e.n > 1 ? `${e.n} conexões` : null;
    case "agentes":
    case "campanhas":
      return [e.nomes?.join(", "), e.motivo].filter(Boolean).join(" · ") || null;
    case "parada":
      return e.ultima ? `última mensagem ${haQuanto(e.ultima)}` : "nenhuma mensagem em 30 dias";
    case "acima_plano": return e.detalhe?.join(", ");
    default: return null;
  }
}

/** Texto curto de um problema, para a linha da empresa na lista. */
export function rotuloDoProblema(p) {
  switch (p.tipo) {
    case "conexoes": return p.n > 1 ? `${p.n} WhatsApp fora do ar` : "WhatsApp fora do ar";
    case "agentes": return "Chave de IA recusada";
    case "sem_whatsapp": return "Sem WhatsApp";
    case "parada": return "Parada há 7 dias";
    case "campanhas": return "Campanha pausada";
    case "acima_plano": return "Acima do plano";
    case "sem_plano": return "Sem plano";
    default: return p.tipo;
  }
}

/** Selo da marca da empresa, com a amostra de cor de cada uma. */
export function SeloMarca({ marca }) {
  const m = MARCAS[validaMarca(marca)];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2 whitespace-nowrap">
      <span className="w-2.5 h-2.5 rounded-full border border-line shrink-0"
        style={{ background: m.amostra[0] }} aria-hidden />
      {m.nome}
    </span>
  );
}
