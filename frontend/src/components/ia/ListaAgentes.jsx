import { useEffect, useMemo, useRef, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import {
  Plus, PencilSimple, Trash, ChatCircleDots, Robot, PaperPlaneRight, Code,
  DotsThree, MagnifyingGlass, PlugsConnected, Warning,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import AgenteWizard from "./AgenteWizard";

const MODO_ROTULO = {
  fallback: "Entra quando nenhum robô atende",
  primeiro: "Atende na frente",
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
  const fim = useRef(null);

  useEffect(() => { fim.current?.scrollIntoView({ behavior: "smooth" }); }, [mensagens, pensando]);

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
        className="bg-surface w-full max-w-lg zz-panel-hard flex flex-col overflow-hidden"
        style={{ height: "min(80vh, 640px)" }}
        data-testid="agente-chat-teste">
        <div className="border-b border-line p-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="font-heading text-lg font-bold tracking-tight truncate">
              Testar {agente.nome}
            </div>
            <div className="text-[11px] text-ink-3">
              Nada é enviado por WhatsApp nem gravado no histórico.
            </div>
          </div>
          <button className="zz-btn zz-btn-secondary text-xs py-1.5 shrink-0" onClick={onFechar}>
            Fechar
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-surface-2">
          {mensagens.length === 0 && (
            <div className="text-xs text-ink-3 text-center py-10">
              Escreva como se fosse um cliente e veja o que o agente responde.
            </div>
          )}
          {mensagens.map((m, i) => (
            <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[80%] px-3.5 py-2 text-sm rounded-2xl ${
                m.role === "user"
                  ? "bg-brand text-brand-fg"
                  : m.role === "assistant"
                    ? "bg-surface border border-line"
                    : m.role === "sistema"
                      ? "bg-warning-soft border border-warning/40 text-warning text-xs"
                      : "bg-danger-soft border border-danger/40 text-danger text-xs"
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          {pensando && <div className="text-xs text-ink-3">Digitando…</div>}
          <div ref={fim} />
        </div>

        <form onSubmit={enviar} className="border-t border-line p-3 flex gap-2">
          <input className="zz-input" autoFocus placeholder="Escreva como um cliente…"
            value={texto} onChange={(e) => setTexto(e.target.value)}
            data-testid="agente-chat-input" />
          <button type="submit" className="zz-btn shrink-0" disabled={pensando || !texto.trim()}>
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
        className="bg-surface w-full max-w-2xl zz-panel-hard overflow-hidden"
        data-testid="agente-prompt">
        <div className="border-b border-line p-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="font-heading text-lg font-bold tracking-tight truncate">
              Instruções de {agente.nome}
            </div>
            <div className="text-[11px] text-ink-3">
              É exatamente isto que o modelo recebe a cada mensagem.
            </div>
          </div>
          <button className="zz-btn zz-btn-secondary text-xs py-1.5 shrink-0" onClick={onFechar}>
            Fechar
          </button>
        </div>
        <pre className="p-4 text-xs font-mono whitespace-pre-wrap overflow-y-auto bg-surface-2 text-ink-2"
          style={{ maxHeight: "60vh" }}>
          {prompt ?? "Carregando…"}
        </pre>
      </div>
    </div>
  );
}

/** Menu de ações secundárias do cartão. As ações raras saem de vista para o
 * cartão não virar uma fileira de seis botõezinhos. */
function MenuAcoes({ onEditar, onPrompt, onExcluir }) {
  const [aberto, setAberto] = useState(false);
  useEffect(() => {
    if (!aberto) return;
    const fechar = () => setAberto(false);
    window.addEventListener("click", fechar);
    return () => window.removeEventListener("click", fechar);
  }, [aberto]);

  const item = "w-full text-left px-3 py-2 text-sm hover:bg-surface-2 flex items-center gap-2";
  return (
    <div className="relative shrink-0" onClick={(e) => e.stopPropagation()}>
      <button onClick={() => setAberto((v) => !v)} aria-label="Mais ações"
        className="w-8 h-8 rounded-lg flex items-center justify-center text-ink-3 hover:bg-surface-2 hover:text-ink">
        <DotsThree size={20} weight="bold" />
      </button>
      {aberto && (
        <div className="absolute right-0 top-9 z-20 w-52 py-1 bg-surface rounded-xl zz-panel-hard border border-line">
          <button className={item} onClick={onEditar}>
            <PencilSimple size={15} /> Editar configuração
          </button>
          <button className={item} onClick={onPrompt}>
            <Code size={15} /> Ver instruções
          </button>
          <button className={`${item} text-danger`} onClick={onExcluir}>
            <Trash size={15} /> Excluir agente
          </button>
        </div>
      )}
    </div>
  );
}

function Numero({ valor, rotulo, destaque }) {
  return (
    <div className="flex-1 min-w-0">
      <div className={`font-heading text-lg font-bold leading-none ${destaque ? "text-success" : "text-ink"}`}>
        {valor}
      </div>
      <div className="text-[10px] uppercase tracking-wider text-ink-3 mt-1 truncate">{rotulo}</div>
    </div>
  );
}

export default function ListaAgentes({ plataformaDisponivel }) {
  const [agentes, setAgentes] = useState([]);
  const [catalogo, setCatalogo] = useState(null);
  const [provedores, setProvedores] = useState([]);
  const [conexoes, setConexoes] = useState([]);
  const [departamentos, setDepartamentos] = useState([]);
  const [busca, setBusca] = useState("");
  const [editando, setEditando] = useState(null); // objeto do agente, ou "novo"
  const [testando, setTestando] = useState(null);
  const [vendoPrompt, setVendoPrompt] = useState(null);

  const carregar = () => api.get("/ai/agents").then((r) => setAgentes(r.data));

  useEffect(() => {
    carregar().catch(() => {});
    api.get("/ai/agents/catalog").then((r) => setCatalogo(r.data)).catch(() => {});
    api.get("/ai/providers").then((r) => setProvedores(r.data.provedores)).catch(() => {});
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/departments").then((r) => setDepartamentos(r.data)).catch(() => {});
  }, []);

  const remover = async (a) => {
    if (!(await confirmToast(
      `Excluir o agente "${a.nome}"? As conversas que ele atende passam a cair na fila humana.`,
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
      // campos que o servidor controla nem os contadores calculados na leitura.
      const { id, tenant_id, created_at, updated_at, conversas, mascara, tem_chave,
              credencial_status, credencial_erro, credencial_em, ...resto } = a;
      const { data } = await api.patch(`/ai/agents/${a.id}`, { ...resto, ativo: !a.ativo });
      setAgentes((as) => as.map((x) => (x.id === a.id ? { ...data, conversas } : x)));
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase();
    if (!q) return agentes;
    return agentes.filter((a) =>
      [a.nome, a.empresa_nome, a.tipo].filter(Boolean).some((c) => c.toLowerCase().includes(q)));
  }, [agentes, busca]);

  const rotuloTipo = (a) => catalogo?.tipos.find((t) => t.id === a.tipo)?.rotulo || a.tipo;

  const rotuloModelo = (a) => {
    if (!a.provedor) return plataformaDisponivel ? "IA do plano" : null;
    const p = provedores.find((x) => x.id === a.provedor);
    return p?.modelos.find((m) => m.id === a.modelo)?.rotulo || a.modelo;
  };

  /** Por que este agente não conseguiria responder agora. `null` = tudo certo.
   *  Fica no cartão, e não num aviso geral da página, porque a credencial é de
   *  cada agente: um pode estar pronto e o outro com a chave revogada. */
  const problema = (a) => {
    if (a.credencial_status === "erro") return "A chave de IA parou de funcionar";
    if (!a.tem_chave && !plataformaDisponivel) return "Sem chave de IA configurada";
    return null;
  };
  const rotuloTom = (id) => catalogo?.tons.find((t) => t.id === id)?.rotulo || id;

  const resumo = (a) => {
    if (a.tipo === "personalizado" && a.objetivo) return a.objetivo;
    const base = catalogo?.tipos.find((t) => t.id === a.tipo)?.descricao || "";
    return a.empresa_nome ? `${base} Atende pela ${a.empresa_nome}.` : base;
  };

  const canais = (a) => {
    if (!a.conexoes?.length) return "Todas as conexões";
    const nomes = conexoes.filter((c) => a.conexoes.includes(c.id)).map((c) => c.nome);
    return nomes.length ? nomes.join(", ") : `${a.conexoes.length} conexão(ões)`;
  };

  return (
    <div className="mt-10" data-testid="lista-agentes">
      {/* Cabeçalho */}
      <div className="flex flex-wrap items-end justify-between gap-4 mb-4">
        <div>
          <div className="flex items-baseline gap-2">
            <h2 className="font-heading text-2xl font-bold tracking-tight">Agentes</h2>
            {agentes.length > 0 && (
              <span className="text-sm text-ink-3">
                {agentes.length} {agentes.length === 1 ? "agente" : "agentes"}
              </span>
            )}
          </div>
          <p className="text-ink-2 text-sm mt-0.5">
            Quem atende automaticamente, e com que comportamento.
          </p>
        </div>
      </div>

      {agentes.length > 2 && (
        <div className="relative mb-4">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
          <input className="zz-input pl-9" placeholder="Buscar agentes…"
            value={busca} onChange={(e) => setBusca(e.target.value)}
            data-testid="buscar-agente" />
        </div>
      )}

      {/* Grade */}
      {agentes.length === 0 ? (
        <div className="zz-panel p-12 flex flex-col items-center text-center gap-3">
          <div className="w-14 h-14 rounded-2xl bg-brand-soft text-ink flex items-center justify-center">
            <Robot size={26} weight="bold" />
          </div>
          <div className="font-heading text-lg font-bold tracking-tight">Nenhum agente ainda</div>
          <p className="text-ink-2 text-sm max-w-sm">
            Em três passos você define quem responde, com que tom, e até onde ele vai antes de
            chamar uma pessoa.
          </p>
          <button className="zz-btn mt-1" disabled={!catalogo} onClick={() => setEditando("novo")}>
            <Plus size={16} weight="bold" /> Criar o primeiro agente
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtrados.map((a) => {
            const ligado = a.ativo && a.modo !== "desligado";
            const c = a.conversas || { atendendo: 0, transferidas: 0, total: 0 };
            return (
              <div key={a.id} className="zz-panel p-5 flex flex-col gap-4"
                data-testid={`agente-${a.id}`}>
                {/* Identidade */}
                <div className="flex items-start gap-3">
                  <div className="relative shrink-0">
                    <div className={`w-11 h-11 rounded-full flex items-center justify-center font-heading text-lg font-bold ${
                      ligado ? "bg-brand text-brand-fg" : "bg-surface-3 text-ink-3"
                    }`}>
                      {(a.nome || "?").trim().charAt(0).toUpperCase()}
                    </div>
                    <span className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-2 border-surface ${
                      ligado ? "bg-success-solid" : "bg-line-strong"
                    }`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-bold truncate">{a.nome}</div>
                    <div className="text-xs text-ink-3 truncate">
                      {rotuloTipo(a)}{rotuloModelo(a) ? ` · ${rotuloModelo(a)}` : ""}
                    </div>
                  </div>
                  <MenuAcoes
                    onEditar={() => setEditando(a)}
                    onPrompt={() => setVendoPrompt(a)}
                    onExcluir={() => remover(a)}
                  />
                </div>

                <p className="text-sm text-ink-2 line-clamp-3 min-h-[3.75rem]">{resumo(a)}</p>

                {/* Números reais: saem de uma agregação sobre as conversas que
                    este agente atendeu, não de contador decorativo. */}
                <div className="flex items-start gap-3 py-3 border-y border-line">
                  <Numero valor={c.atendendo} rotulo="atendendo" destaque={c.atendendo > 0} />
                  <div className="w-px self-stretch bg-line" />
                  <Numero valor={c.transferidas} rotulo="transferidas" />
                  <div className="w-px self-stretch bg-line" />
                  <Numero valor={c.total} rotulo="no total" />
                </div>

                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-ink-3 mb-2">
                    Comportamento
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <span className="px-2 py-1 rounded-full bg-surface-2 border border-line text-[11px] text-ink-2">
                      {MODO_ROTULO[a.modo] || a.modo}
                    </span>
                    {(a.tom || []).map((t) => (
                      <span key={t}
                        className="px-2 py-1 rounded-full bg-surface-2 border border-line text-[11px] text-ink-2">
                        {rotuloTom(t)}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 text-xs text-ink-3">
                  <PlugsConnected size={14} />
                  <span className="truncate">{canais(a)}</span>
                </div>

                {problema(a) && (
                  <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[11px] text-warning">
                    <Warning size={14} weight="bold" className="shrink-0 mt-px" />
                    <span>{problema(a)} — as conversas continuam indo para a fila humana.</span>
                  </div>
                )}

                {/* Ações */}
                <div className="mt-auto space-y-2">
                  <div className="flex gap-2">
                    <button className="zz-btn zz-btn-secondary flex-1 justify-center"
                      onClick={() => alternarAtivo(a)} data-testid={`agente-pausar-${a.id}`}>
                      {a.ativo ? "Pausar" : "Ativar"}
                    </button>
                    <button className="zz-btn flex-1 justify-center"
                      onClick={() => setEditando(a)} data-testid={`agente-editar-${a.id}`}>
                      Configurar
                    </button>
                  </div>
                  <button className="zz-btn zz-btn-secondary w-full justify-center"
                    onClick={() => setTestando(a)} data-testid={`agente-testar-${a.id}`}>
                    <ChatCircleDots size={15} weight="bold" /> Testar conversa
                  </button>
                </div>
              </div>
            );
          })}
          {filtrados.length === 0 ? (
            <div className="col-span-full zz-panel p-8 text-center text-sm text-ink-3">
              Nenhum agente encontrado para “{busca}”.
            </div>
          ) : (
            // O criar vive aqui, e não no cabeçalho: fica ao lado do que já
            // existe, no fim da leitura, em vez de competir com o título.
            <button type="button" disabled={!catalogo}
              onClick={() => setEditando("novo")} data-testid="novo-agente-btn"
              className="rounded-2xl border border-dashed border-line-strong text-ink-3
                         min-h-56 flex flex-col items-center justify-center gap-2
                         hover:border-info hover:text-info hover:bg-info-soft
                         disabled:opacity-45 transition-colors">
              <Plus size={22} weight="bold" />
              <span className="text-sm font-bold">Criar agente</span>
            </button>
          )}
        </div>
      )}

      {editando && catalogo && (
        <AgenteWizard
          catalogo={catalogo}
          provedores={provedores}
          plataformaDisponivel={plataformaDisponivel}
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
