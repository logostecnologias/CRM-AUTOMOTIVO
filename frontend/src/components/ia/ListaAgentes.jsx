import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import {
  Plus, PencilSimple, Trash, ChatCircleDots, Robot, PaperPlaneRight, Code,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import AgenteWizard from "./AgenteWizard";

const MODO_ROTULO = {
  fallback: "Quando nenhum robô atender",
  primeiro: "Na frente, em toda conversa",
  desligado: "Desligado",
};

/** Conversa de teste com um agente, sem WhatsApp e sem gravar nada.
 *
 * Mesma ideia do "Testar" do editor de fluxos: ver o agente responder antes de
 * apontá-lo para clientes de verdade. Bate no motor real, então também
 * exercita a credencial e o teto do plano — um teste que passasse por fora
 * desses dois não provaria nada sobre produção. */
function ChatTeste({ agente, onFechar }) {
  const [mensagens, setMensagens] = useState([]);
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);

  const enviar = async (e) => {
    e.preventDefault();
    const conteudo = texto.trim();
    if (!conteudo || pensando) return;
    const proximas = [...mensagens, { role: "user", content: conteudo }];
    setMensagens(proximas);
    setTexto("");
    setPensando(true);
    try {
      const { data } = await api.post(`/ai/agents/${agente.id}/test`, { mensagens: proximas });
      setMensagens([
        ...proximas,
        data.transferiu
          ? { role: "sistema", content: `Transferido para atendimento humano — ${data.motivo}` }
          : { role: "assistant", content: data.texto },
      ]);
    } catch (ex) {
      setMensagens([
        ...proximas,
        { role: "erro", content: formatApiErrorDetail(ex.response?.data?.detail) },
      ]);
    } finally {
      setPensando(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onFechar}>
      <div onClick={(e) => e.stopPropagation()}
        className="bg-surface border border-line-strong w-full max-w-lg zz-panel-hard flex flex-col rounded-lg"
        style={{ height: "min(80vh, 640px)" }}
        data-testid="agente-chat-teste">
        <div className="border-b border-line p-4 flex items-center justify-between">
          <div>
            <div className="font-heading text-lg font-black tracking-tighter">
              Testar {agente.nome}
            </div>
            <div className="text-[11px] text-ink-3">
              Conversa de teste. Nada é enviado por WhatsApp nem gravado no histórico.
            </div>
          </div>
          <button className="zz-btn zz-btn-secondary text-xs py-1" onClick={onFechar}>
            Fechar
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-surface-2">
          {mensagens.length === 0 && (
            <div className="text-xs text-ink-3 text-center py-8">
              Escreva como se fosse um cliente e veja o que o agente responde.
            </div>
          )}
          {mensagens.map((m, i) => (
            <div key={i}
              className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[80%] px-3 py-2 text-sm border rounded-2xl ${
                m.role === "user"
                  ? "bg-brand text-brand-fg border-brand"
                  : m.role === "assistant"
                    ? "bg-surface border-line"
                    : m.role === "sistema"
                      ? "bg-warning-soft border-warning text-warning text-xs"
                      : "bg-danger-soft border-danger text-danger text-xs"
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          {pensando && <div className="text-xs text-ink-3">Digitando…</div>}
        </div>

        <form onSubmit={enviar} className="border-t border-line p-3 flex gap-2">
          <input className="zz-input" autoFocus placeholder="Escreva como um cliente…"
            value={texto} onChange={(e) => setTexto(e.target.value)}
            data-testid="agente-chat-input" />
          <button type="submit" className="zz-btn" disabled={pensando || !texto.trim()}>
            <PaperPlaneRight size={14} weight="bold" />
          </button>
        </form>
      </div>
    </div>
  );
}

/** O prompt final montado a partir das escolhas. Existe para o admin conferir
 * o que o agente realmente recebe — sem isso, mexer em tom e restrição é
 * adivinhação. */
function VerPrompt({ agente, onFechar }) {
  const [prompt, setPrompt] = useState(null);
  useEffect(() => {
    api.get(`/ai/agents/${agente.id}/prompt`)
      .then((r) => setPrompt(r.data.instrucoes))
      .catch((ex) => toast.error(formatApiErrorDetail(ex.response?.data?.detail)));
  }, [agente.id]);
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onFechar}>
      <div onClick={(e) => e.stopPropagation()}
        className="bg-surface border border-line-strong w-full max-w-2xl zz-panel-hard rounded-lg"
        data-testid="agente-prompt">
        <div className="border-b border-line p-4 flex items-center justify-between">
          <div className="font-heading text-lg font-black tracking-tighter">
            Instruções de {agente.nome}
          </div>
          <button className="zz-btn zz-btn-secondary text-xs py-1" onClick={onFechar}>Fechar</button>
        </div>
        <pre className="p-4 text-xs font-mono whitespace-pre-wrap overflow-y-auto bg-surface-2"
          style={{ maxHeight: "60vh" }}>
          {prompt ?? "Carregando…"}
        </pre>
      </div>
    </div>
  );
}

export default function ListaAgentes({ conexaoOk }) {
  const [agentes, setAgentes] = useState([]);
  const [catalogo, setCatalogo] = useState(null);
  const [conexoes, setConexoes] = useState([]);
  const [departamentos, setDepartamentos] = useState([]);
  const [editando, setEditando] = useState(null); // objeto do agente, ou "novo"
  const [testando, setTestando] = useState(null);
  const [vendoPrompt, setVendoPrompt] = useState(null);

  const carregar = () => api.get("/ai/agents").then((r) => setAgentes(r.data));

  useEffect(() => {
    carregar().catch(() => {});
    api.get("/ai/agents/catalog").then((r) => setCatalogo(r.data)).catch(() => {});
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/departments").then((r) => setDepartamentos(r.data)).catch(() => {});
  }, []);

  const remover = async (a) => {
    if (!(await confirmToast(`Excluir o agente "${a.nome}"? As conversas que ele atende passam a cair na fila humana.`,
      { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/ai/agents/${a.id}`);
      setAgentes((as) => as.filter((x) => x.id !== a.id));
      toast.success("Agente excluído.");
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const alternarAtivo = async (a) => {
    try {
      // O PATCH recebe o agente inteiro (é um PUT disfarçado), mas sem os
      // campos que o servidor controla — mandá-los de volta não faz mal hoje,
      // porque o pydantic os ignora, e é justamente esse tipo de dependência
      // silenciosa que quebra quando alguém liga `extra="forbid"`.
      const { id, tenant_id, created_at, updated_at, ...resto } = a;
      const { data } = await api.patch(`/ai/agents/${a.id}`, { ...resto, ativo: !a.ativo });
      setAgentes((as) => as.map((x) => (x.id === a.id ? data : x)));
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const nomeConexoes = (a) => {
    if (!a.conexoes?.length) return "Todas as conexões";
    return conexoes.filter((c) => a.conexoes.includes(c.id)).map((c) => c.nome).join(", ")
      || `${a.conexoes.length} conexão(ões)`;
  };

  return (
    <div className="mt-10" data-testid="lista-agentes">
      <div className="flex items-end justify-between mb-4 gap-4">
        <div>
          <div className="font-heading text-2xl font-black tracking-tighter">Agentes</div>
          <p className="text-ink-2 text-sm mt-0.5">
            Quem atende automaticamente, e com que comportamento.
          </p>
        </div>
        <button className="zz-btn" disabled={!catalogo}
          onClick={() => setEditando("novo")} data-testid="novo-agente-btn">
          <Plus size={16} weight="bold" /> Novo agente
        </button>
      </div>

      {!conexaoOk && agentes.length > 0 && (
        <div className="mb-4 border border-warning bg-warning-soft p-3 text-xs text-warning rounded-lg">
          Os agentes estão configurados, mas sem uma conta de IA conectada eles não conseguem
          responder — as conversas continuam caindo na fila humana.
        </div>
      )}

      {agentes.length === 0 ? (
        <div className="border border-line bg-surface p-10 flex flex-col items-center text-center gap-3 rounded-lg">
          <div className="w-12 h-12 bg-brand text-brand-fg flex items-center justify-center">
            <Robot size={22} weight="bold" />
          </div>
          <p className="text-ink-2 text-sm max-w-sm">
            Nenhum agente ainda. Em três passos você configura quem responde, com que tom e até
            onde vai antes de chamar uma pessoa.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {agentes.map((a) => (
            <div key={a.id}
              className="border border-line bg-surface p-5 flex items-center gap-4 rounded-lg"
              data-testid={`agente-${a.id}`}>
              <div className={`w-9 h-9 shrink-0 flex items-center justify-center ${
                a.ativo && a.modo !== "desligado" ? "bg-brand text-brand-fg" : "bg-surface-3 text-ink-3"
              }`}>
                <Robot size={18} weight="bold" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-bold text-sm flex items-center gap-2">
                  {a.nome}
                  <span className="text-[10px] font-bold uppercase tracking-wider text-ink-3 border border-line px-1.5 py-0.5 rounded-full">
                    {catalogo?.tipos.find((t) => t.id === a.tipo)?.rotulo || a.tipo}
                  </span>
                  {(!a.ativo || a.modo === "desligado") && (
                    <span className="text-[10px] font-bold uppercase tracking-wider text-ink-3">
                      pausado
                    </span>
                  )}
                </div>
                <div className="text-xs text-ink-2 mt-0.5 truncate">
                  {MODO_ROTULO[a.modo] || a.modo} · {nomeConexoes(a)}
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                <button className="zz-btn zz-btn-secondary text-xs py-1"
                  onClick={() => setTestando(a)} data-testid={`agente-testar-${a.id}`}>
                  <ChatCircleDots size={14} weight="bold" /> Testar
                </button>
                <button className="zz-btn zz-btn-secondary text-xs py-1"
                  onClick={() => setVendoPrompt(a)} title="Ver as instruções montadas">
                  <Code size={14} weight="bold" />
                </button>
                <button className="zz-btn zz-btn-secondary text-xs py-1"
                  onClick={() => alternarAtivo(a)}>
                  {a.ativo ? "Pausar" : "Ativar"}
                </button>
                <button className="zz-btn zz-btn-secondary text-xs py-1"
                  onClick={() => setEditando(a)} data-testid={`agente-editar-${a.id}`}>
                  <PencilSimple size={14} weight="bold" />
                </button>
                <button className="zz-btn zz-btn-secondary text-xs py-1 text-danger"
                  onClick={() => remover(a)}>
                  <Trash size={14} weight="bold" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editando && catalogo && (
        <AgenteWizard
          catalogo={catalogo}
          conexoes={conexoes}
          departamentos={departamentos}
          agente={editando === "novo" ? null : editando}
          onFechar={() => setEditando(null)}
          onSalvo={() => { setEditando(null); carregar(); }}
        />
      )}
      {testando && <ChatTeste agente={testando} onFechar={() => setTestando(null)} />}
      {vendoPrompt && <VerPrompt agente={vendoPrompt} onFechar={() => setVendoPrompt(null)} />}
    </div>
  );
}
