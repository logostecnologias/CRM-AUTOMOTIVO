import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { useAuth } from "@/context/AuthContext";
import { MARCAS, valida as validaMarca } from "@/lib/marca";
import { haQuanto, plural } from "@/components/painel/Indicadores";
import { CheckCircle, Info, Warning, WarningCircle } from "@phosphor-icons/react";

/**
 * Peças compartilhadas pelas telas do super admin: a visão geral, a lista de
 * empresas e a ficha. Os planos saíram em 18/11/2026; o único teto que sobrou
 * é o de IA, como campo da empresa.
 */

// --- Senha ----------------------------------------------------------------

// Espelha o `SENHA_MIN` de `backend/routes/tenants.py`. O piso de verdade é o
// do servidor; este aqui existe para o super admin saber do limite enquanto
// digita, em vez de descobrir por um 422 em inglês depois de preencher tudo.
export const SENHA_MIN = 8;

// Sem `l`, `I`, `1`, `O` e `0`: a senha vai ser lida em voz alta ou copiada de
// um WhatsApp e digitada à mão pelo cliente, e é nesses cinco caracteres que
// isso falha.
const ALFABETO = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";

export function gerarSenha(tamanho = 14) {
  const sorteio = new Uint32Array(tamanho);
  crypto.getRandomValues(sorteio);
  return Array.from(sorteio, (n) => ALFABETO[n % ALFABETO.length]).join("");
}

export async function copiar(texto, aviso = "Copiado") {
  try {
    await navigator.clipboard.writeText(texto);
    toast.success(aviso);
  } catch {
    // `navigator.clipboard` não existe fora de HTTPS (e o painel roda em
    // localhost sem TLS em desenvolvimento). Sem este aviso o clique não faz
    // nada e parece que copiou.
    toast.error("Não foi possível copiar. Selecione o texto e copie à mão.");
  }
}

// --- Modo suporte ---------------------------------------------------------

/**
 * Entrar na empresa (modo suporte), já na tela onde o problema se resolve.
 * Os alertas e as linhas levam `destino`: entrar no painel e navegar até o
 * WhatsApp à mão é exatamente o caminho que o alerta existe para encurtar.
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

// --- Números --------------------------------------------------------------

export function numero(n) {
  return (n || 0).toLocaleString("pt-BR");
}

/** 1.234.567 tokens vira "1,2 mi": a coluna de IA não cabe o número inteiro. */
export function compacto(n) {
  const v = n || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`;
  if (v >= 1_000) return `${(v / 1_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil`;
  return v.toLocaleString("pt-BR");
}

export function dolar(n) {
  return (n || 0).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
}

export function dataHora(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

// --- Alertas --------------------------------------------------------------

/** Título de um grupo de alertas da visão geral, pelo número de empresas. */
export function tituloDoAlerta(tipo, n) {
  const empresas = plural(n, "empresa", "empresas");
  switch (tipo) {
    case "conexoes": return `${empresas} com WhatsApp fora do ar`;
    case "agentes": return `${empresas} com agente de IA de chave recusada`;
    case "ia_no_teto": return `${empresas} no limite de IA do mês`;
    case "ia_perto_teto": return `${empresas} perto do limite de IA`;
    case "sem_whatsapp": return `${empresas} sem WhatsApp conectado`;
    case "parada": return `${empresas} sem mensagem há uma semana`;
    case "campanhas": return `${empresas} com campanha pausada`;
    default: return `${empresas}: ${tipo}`;
  }
}

/** O porquê do alerta, dito uma vez no grupo. */
export function porQue(tipo) {
  switch (tipo) {
    case "conexoes": return "Lembretes, campanhas e respostas por esse número não saem. O cliente pode nem ter percebido.";
    case "agentes": return "As conversas estão indo para a fila em vez de serem respondidas.";
    case "ia_no_teto": return "O agente sem chave própria parou de responder e as conversas vão para a fila. Aumente o limite na ficha ou peça a chave do cliente.";
    case "ia_perto_teto": return "Passou de 80% do limite mensal de IA. Ainda dá tempo de ajustar antes de o agente parar.";
    case "sem_whatsapp": return "Cadastro com mais de dois dias e implantação parada: sem número, nada entra nem sai.";
    case "parada": return "O WhatsApp está cadastrado, mas nada passou por ele em sete dias. É o sinal mais cedo de cancelamento.";
    case "campanhas": return "O disparo parou no meio e não volta sozinho.";
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
    case "ia_no_teto": return e.detalhe?.join(", ");
    case "ia_perto_teto": return e.pct != null ? `${e.pct}% do limite` : null;
    default: return null;
  }
}

/** Texto curto de um problema, para a linha da empresa na lista. */
export function rotuloDoProblema(p) {
  switch (p.tipo) {
    case "conexoes": return p.n > 1 ? `${p.n} WhatsApp fora do ar` : "WhatsApp fora do ar";
    case "agentes": return "Chave de IA recusada";
    case "ia_no_teto": return "IA no limite";
    case "ia_perto_teto": return `IA em ${p.pct}%`;
    case "sem_whatsapp": return "Sem WhatsApp";
    case "parada": return "Parada há 7 dias";
    case "campanhas": return "Campanha pausada";
    default: return p.tipo;
  }
}

/** Onde a ficha abre para resolver um problema que não tem tela no cliente. */
export function abaDoProblema(tipo) {
  return tipo === "ia_no_teto" || tipo === "ia_perto_teto" ? "config" : "resumo";
}

export function IconeNivel({ nivel, size = 16 }) {
  // Ícone + texto, nunca só a cor: o nível também é dito pelo ícone.
  if (nivel === "alto") return <WarningCircle size={size} weight="fill" className="text-danger shrink-0" />;
  if (nivel === "medio") return <Warning size={size} weight="fill" className="text-warning shrink-0" />;
  return <Info size={size} weight="fill" className="text-ink-3 shrink-0" />;
}

export function SeloProblema({ p, pequeno }) {
  const cor = p.nivel === "alto"
    ? "bg-danger-soft border-danger text-danger"
    : p.nivel === "medio" ? "bg-warning-soft border-warning text-warning" : "bg-surface-2 border-line text-ink-2";
  return (
    <span className={`${pequeno ? "text-[11px] px-1.5" : "text-xs px-2"} py-0.5 rounded-full border whitespace-nowrap ${cor}`}>
      {rotuloDoProblema(p)}
    </span>
  );
}

/**
 * A saúde de uma empresa num ponto: vermelho com problema grave, amarelo com
 * atenção, verde em dia, cinza suspensa. Acompanha sempre um texto (o selo ou
 * "em dia"), nunca só a cor.
 */
export function nivelDaEmpresa(t) {
  if (t.status !== "active") return "suspensa";
  const niveis = new Set((t.saude?.problemas || []).map((p) => p.nivel));
  if (niveis.has("alto")) return "alto";
  if (niveis.has("medio")) return "medio";
  return "ok";
}

export function PontoSaude({ nivel }) {
  const cor = {
    alto: "bg-danger", medio: "bg-warning", ok: "bg-success", suspensa: "bg-ink-4",
  }[nivel];
  const rotulo = { alto: "Problema grave", medio: "Precisa de atenção", ok: "Em dia", suspensa: "Suspensa" }[nivel];
  return <span className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${cor}`} title={rotulo} aria-label={rotulo} />;
}

export function EmDia() {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-success">
      <CheckCircle size={13} weight="fill" /> em dia
    </span>
  );
}

// --- IA -------------------------------------------------------------------

/**
 * Consumo de IA pago pela plataforma contra o teto da empresa. Sem teto, só o
 * número: uma barra vazia sugeriria um limite que não existe.
 */
export function BarraIA({ ia, compactar = true }) {
  if (!ia) return null;
  const usado = ia.tokens_plataforma || 0;
  if (!ia.teto) {
    return (
      <div className="text-xs">
        <span className="font-mono">{compactar ? compacto(usado) : numero(usado)}</span>
        <span className="text-ink-3"> · sem limite</span>
      </div>
    );
  }
  const pct = Math.min(100, ia.pct || 0);
  const cor = (ia.pct || 0) >= 100 ? "bg-danger" : (ia.pct || 0) >= 80 ? "bg-warning" : "bg-brand";
  return (
    <div className="min-w-[110px]">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-mono">{compactar ? compacto(usado) : numero(usado)}</span>
        <span className={`font-mono ${(ia.pct || 0) >= 100 ? "text-danger font-bold" : "text-ink-3"}`}>
          {ia.pct}%
        </span>
      </div>
      <div className="h-1.5 mt-1 bg-surface-3 rounded-full overflow-hidden">
        <div className={`h-full ${cor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// --- Linha do tempo -------------------------------------------------------

const CAMPOS = {
  name: "o nome",
  marca: "a marca",
  limite_tokens_ia_mes: "o limite de IA",
  retencao_midia_dias: "a retenção de mídia",
};

/** O que aconteceu, em português, a partir da ação gravada na auditoria. */
export function descreverAtividade(a) {
  const m = a.meta || {};
  switch (a.acao) {
    case "suporte.entrar": return "entrou em modo suporte";
    case "tenant.create": return "criou a empresa";
    case "tenant.delete": {
      const n = Object.values(m.apagados || {}).reduce((x, y) => x + y, 0);
      return `excluiu a empresa${n ? ` (${numero(n)} registros)` : ""}`;
    }
    case "tenant.update": {
      if (m.status === "suspended") return "suspendeu a empresa";
      if (m.status === "active") return "reativou a empresa";
      const mudou = Object.keys(m).map((k) => CAMPOS[k]).filter(Boolean);
      return mudou.length ? `alterou ${mudou.join(", ")}` : "alterou a empresa";
    }
    case "user.senha_redefinida": return `redefiniu a senha de ${a.alvo || "um usuário"}`;
    case "user.update":
      if (m.senha_trocada) return "trocou a senha de um usuário";
      if (m.status === "suspended") return "suspendeu um usuário";
      if (m.status === "active") return "reativou um usuário";
      return "alterou um usuário";
    case "contact.export": return "exportou a base de contatos";
    case "contact.merge": return "mesclou dois contatos";
    case "contact.anonimizar": return "anonimizou um contato";
    case "contact.apagar": return "apagou um contato";
    default: return a.acao;
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

/** Cabeçalho de um cartão das telas do super admin. */
export function Cartao({ titulo, acao, children, className = "", testid }) {
  return (
    <div className={`border border-line bg-surface rounded-xl overflow-hidden ${className}`} data-testid={testid}>
      {titulo && (
        <div className="flex items-center justify-between gap-3 px-4 pt-3.5 pb-2.5">
          <div className="text-sm font-semibold">{titulo}</div>
          {acao}
        </div>
      )}
      {children}
    </div>
  );
}
