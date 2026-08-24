import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { formatBRL, parseBRLInput } from "@/lib/currency";
import {
  Plus, SlidersHorizontal, TrendUp, MagnifyingGlass, X, Megaphone, User, Warning,
  BellSlash,
} from "@phosphor-icons/react";
import DealPanel from "@/components/deals/DealPanel";
import FunilConfig from "@/components/deals/FunilConfig";
import FunilMetricas from "@/components/deals/FunilMetricas";

function Cartao({ deal, onAbrir }) {
  const atrasado = deal.previsao_fechamento && deal.status === "aberto" &&
    new Date(deal.previsao_fechamento) < new Date();
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", deal.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={() => onAbrir(deal.id)}
      className="border border-slate-300 bg-white p-2.5 mb-2 cursor-pointer hover:border-slate-900 active:opacity-60"
      data-testid={`deal-card-${deal.id}`}
    >
      <div className="text-sm font-semibold leading-tight mb-1 line-clamp-2">{deal.titulo}</div>
      <div className="font-mono text-sm font-bold mb-1.5">{formatBRL(deal.valor)}</div>
      {deal.contact && (
        <div className="flex items-center gap-1 text-[11px] text-slate-600 truncate">
          <User size={11} weight="bold" className="shrink-0" />
          <span className="truncate">{deal.contact.nome}</span>
        </div>
      )}
      <div className="flex items-center gap-2 mt-1.5">
        {deal.sem_proximo_passo && (
          <span title="Sem próximo passo agendado — abra e agende" className="text-amber-600">
            <BellSlash size={12} weight="bold" />
          </span>
        )}
        {deal.campanha_id && (
          <span title="Originado de campanha" className="text-slate-400">
            <Megaphone size={11} weight="bold" />
          </span>
        )}
        {deal.previsao_fechamento && (
          <span className={`text-[10px] font-mono ${atrasado ? "text-red-600 font-bold" : "text-slate-500"}`}>
            {new Date(deal.previsao_fechamento).toLocaleDateString("pt-BR")}
          </span>
        )}
      </div>
    </div>
  );
}

function SeletorContato({ valor, onChange }) {
  const [busca, setBusca] = useState("");
  const [achados, setAchados] = useState([]);

  useEffect(() => {
    const t = setTimeout(() => {
      api.get("/contacts", { params: { q: busca || undefined, limit: 20 } })
        .then((r) => setAchados(r.data.items || [])).catch(() => setAchados([]));
    }, 300);
    return () => clearTimeout(t);
  }, [busca]);

  if (valor) {
    return (
      <div className="flex items-center gap-2 border border-slate-300 bg-white h-9 px-2">
        <span className="text-sm font-semibold flex-1 truncate">{valor.nome}</span>
        <button type="button" onClick={() => onChange(null)} className="p-0.5 hover:bg-slate-200">
          <X size={12} weight="bold" />
        </button>
      </div>
    );
  }
  return (
    <div className="border border-slate-300 bg-white">
      <input className="zz-input border-0 h-9" placeholder="Buscar contato…" data-testid="deal-contact-search"
        value={busca} onChange={(e) => setBusca(e.target.value)} />
      {busca && (
        <div className="max-h-36 overflow-y-auto border-t border-slate-200">
          {achados.length === 0 && <div className="p-2 text-xs text-slate-500">Nada encontrado.</div>}
          {achados.map((c) => (
            <button key={c.id} type="button" onClick={() => { onChange(c); setBusca(""); }}
              className="w-full text-left flex items-center gap-2 px-2 py-1.5 border-b border-slate-100 hover:bg-slate-50">
              <span className="text-sm font-semibold flex-1 truncate">{c.nome}</span>
              <span className="text-[11px] font-mono text-slate-500">{c.numero_whatsapp}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function FunilPage() {
  const [funis, setFunis] = useState([]);
  const [funilId, setFunilId] = useState("");
  const [quadro, setQuadro] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [busca, setBusca] = useState("");
  const [responsavel, setResponsavel] = useState("");
  const [abertoId, setAbertoId] = useState(null);
  const [config, setConfig] = useState(false);
  const [metricas, setMetricas] = useState(false);
  const [novo, setNovo] = useState(null);
  // Queda numa coluna de "perdido" precisa do motivo antes de gravar — sem ele
  // o relatório de motivos de perda nasce vazio e ninguém volta para preencher.
  const [perda, setPerda] = useState(null);
  const [arrastandoSobre, setArrastandoSobre] = useState(null);
  // Link direto vindo da ficha do contato ("abrir este negócio").
  const [params] = useSearchParams();
  useEffect(() => {
    const id = params.get("negocio");
    if (id) setAbertoId(id);
  }, [params]);

  useEffect(() => {
    api.get("/pipelines").then((r) => {
      setFunis(r.data);
      setFunilId((atual) => atual || r.data[0]?.id || "");
    }).catch(() => {});
    api.get("/users").then((r) => setUsuarios(r.data)).catch(() => {});
  }, []);

  const carregar = useCallback(() => {
    if (!funilId) return;
    api.get("/deals/board", {
      params: { pipeline_id: funilId, q: busca || undefined, responsavel_id: responsavel || undefined },
    }).then((r) => setQuadro(r.data)).catch(() => {});
  }, [funilId, busca, responsavel]);

  useEffect(() => {
    const t = setTimeout(carregar, 250);
    return () => clearTimeout(t);
  }, [carregar]);

  const mover = async (dealId, etapaId, motivo) => {
    try {
      const payload = { etapa_id: etapaId };
      if (motivo !== undefined) payload.motivo_perda = motivo;
      await api.patch(`/deals/${dealId}`, payload);
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const soltar = (e, etapa) => {
    e.preventDefault();
    setArrastandoSobre(null);
    const dealId = e.dataTransfer.getData("text/plain");
    if (!dealId) return;
    const coluna = quadro.colunas.find((c) => c.deals.some((d) => d.id === dealId));
    if (coluna?.etapa.id === etapa.id) return;
    if (etapa.tipo === "perdido") setPerda({ dealId, etapaId: etapa.id, motivo: "" });
    else mover(dealId, etapa.id);
  };

  const criar = async (e) => {
    e.preventDefault();
    if (!novo.contato) return toast.error("Escolha o contato do negócio");
    try {
      const r = await api.post("/deals", {
        titulo: novo.titulo,
        contact_id: novo.contato.id,
        pipeline_id: funilId,
        valor: novo.valor,
        responsavel_id: novo.responsavel_id || null,
        previsao_fechamento: novo.previsao || null,
      });
      setNovo(null);
      toast.success("Negócio criado");
      carregar();
      setAbertoId(r.data.id);
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const funil = quadro?.pipeline;
  const totalAberto = (quadro?.colunas || [])
    .filter((c) => c.etapa.tipo === "aberta")
    .reduce((acc, c) => acc + (c.valor || 0), 0);

  return (
    <div className={`p-8 ${abertoId ? "pr-[500px]" : ""}`} data-testid="funil-page">
      <div className="flex items-end justify-between mb-6 gap-4">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Comercial</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Funil de negócios</h1>
          <p className="text-slate-600 mt-2 text-sm">
            Arraste o cartão entre as etapas. {formatBRL(totalAberto)} em aberto no funil.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          {funis.length > 1 && (
            <select className="zz-input max-w-[200px]" data-testid="funil-select"
              value={funilId} onChange={(e) => setFunilId(e.target.value)}>
              {funis.map((f) => <option key={f.id} value={f.id}>{f.nome}</option>)}
            </select>
          )}
          <button onClick={() => { setMetricas((v) => !v); setConfig(false); }}
            className="zz-btn zz-btn-secondary" data-testid="toggle-metricas">
            <TrendUp size={14} weight="bold" /> Desempenho
          </button>
          <button onClick={() => { setConfig((v) => !v); setMetricas(false); }}
            className="zz-btn zz-btn-secondary" data-testid="toggle-config">
            <SlidersHorizontal size={14} weight="bold" /> Etapas
          </button>
          <button onClick={() => setNovo({ titulo: "", valor: 0, contato: null, responsavel_id: "", previsao: "" })}
            className="zz-btn" data-testid="new-deal-btn" disabled={!funilId}>
            <Plus size={14} weight="bold" /> Novo negócio
          </button>
        </div>
      </div>

      {metricas && funilId && <FunilMetricas pipelineId={funilId} onClose={() => setMetricas(false)} />}
      {config && funil && (
        <FunilConfig pipeline={funil} onClose={() => setConfig(false)}
          onSaved={() => {
            api.get("/pipelines").then((r) => setFunis(r.data)).catch(() => {});
            carregar();
          }} />
      )}

      {novo && (
        <form onSubmit={criar} className="border border-slate-900 bg-white p-4 mb-4 grid grid-cols-5 gap-3 items-end zz-panel-hard"
          data-testid="new-deal-form">
          <div className="col-span-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Título</label>
            <input required autoFocus className="zz-input" data-testid="new-deal-title"
              placeholder="Plano anual, orçamento de reforma…"
              value={novo.titulo} onChange={(e) => setNovo({ ...novo, titulo: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Contato</label>
            <SeletorContato valor={novo.contato} onChange={(c) => setNovo({ ...novo, contato: c })} />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Valor</label>
            <input className="zz-input font-mono" data-testid="new-deal-value"
              value={formatBRL(novo.valor)}
              onChange={(e) => setNovo({ ...novo, valor: parseBRLInput(e.target.value) })} />
          </div>
          <div className="flex gap-2">
            <button type="submit" className="zz-btn" data-testid="new-deal-submit">Criar</button>
            <button type="button" onClick={() => setNovo(null)} className="zz-btn zz-btn-secondary">Cancelar</button>
          </div>
        </form>
      )}

      <div className="flex gap-3 items-center mb-4">
        <div className="relative flex-1 max-w-xs">
          <MagnifyingGlass size={14} weight="bold" className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="zz-input pl-8" placeholder="Buscar negócio…" data-testid="deal-search"
            value={busca} onChange={(e) => setBusca(e.target.value)} />
        </div>
        <select className="zz-input max-w-[200px]" data-testid="deal-owner-filter"
          value={responsavel} onChange={(e) => setResponsavel(e.target.value)}>
          <option value="">Todos os responsáveis</option>
          {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
        </select>
        {(busca || responsavel) && (
          <button onClick={() => { setBusca(""); setResponsavel(""); }} className="p-1.5 hover:bg-slate-200">
            <X size={14} weight="bold" />
          </button>
        )}
      </div>

      {!quadro ? (
        <div className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500 py-8">Carregando quadro…</div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-4 items-start">
          {quadro.colunas.map((coluna) => (
            <div key={coluna.etapa.id}
              onDragOver={(e) => { e.preventDefault(); setArrastandoSobre(coluna.etapa.id); }}
              onDragLeave={() => setArrastandoSobre((a) => (a === coluna.etapa.id ? null : a))}
              onDrop={(e) => soltar(e, coluna.etapa)}
              className={`w-[240px] shrink-0 bg-slate-100 border ${
                arrastandoSobre === coluna.etapa.id ? "border-slate-900 border-2" : "border-slate-200"
              }`}
              data-testid={`funil-coluna-${coluna.etapa.id}`}>
              <div className="px-3 py-2 border-b border-slate-300 bg-white"
                style={{ borderTop: `3px solid ${coluna.etapa.cor}` }}>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider truncate">{coluna.etapa.nome}</span>
                  <span className="text-[10px] font-mono text-slate-500 shrink-0">{coluna.n}</span>
                </div>
                <div className="font-mono text-xs font-bold text-slate-700">
                  {formatBRL(coluna.valor)}{coluna.valor_parcial ? "+" : ""}
                </div>
              </div>
              <div className="p-2 min-h-[120px] max-h-[calc(100vh-380px)] overflow-y-auto">
                {coluna.deals.length === 0 && (
                  <div className="text-[11px] text-slate-400 text-center py-6">Arraste um cartão para cá</div>
                )}
                {coluna.deals.map((d) => <Cartao key={d.id} deal={d} onAbrir={setAbertoId} />)}
                {coluna.truncada && (
                  <div className="text-[10px] text-slate-500 text-center py-1 border-t border-slate-300">
                    mostrando {coluna.deals.length} de {coluna.n}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {perda && (
        <div className="fixed inset-0 bg-slate-900/40 z-50 flex items-center justify-center p-4"
          onClick={() => setPerda(null)}>
          <form onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              mover(perda.dealId, perda.etapaId, perda.motivo);
              setPerda(null);
            }}
            className="bg-white border-2 border-slate-900 p-5 w-full max-w-md zz-panel-hard"
            data-testid="motivo-perda-dialog">
            <div className="flex items-center gap-2 mb-2">
              <Warning size={18} weight="bold" className="text-red-600" />
              <div className="font-heading text-xl font-black tracking-tighter">Por que perdemos?</div>
            </div>
            <p className="text-xs text-slate-600 mb-3">
              É este campo que alimenta o relatório de motivos de perda. Pode deixar em branco, mas
              aí o negócio entra como "não informado".
            </p>
            <input autoFocus className="zz-input mb-3" data-testid="motivo-perda-input"
              placeholder="Preço, prazo, escolheu concorrente…"
              value={perda.motivo} onChange={(e) => setPerda({ ...perda, motivo: e.target.value })} />
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setPerda(null)} className="zz-btn zz-btn-secondary">
                Cancelar
              </button>
              <button type="submit" className="zz-btn" data-testid="motivo-perda-submit">
                Marcar como perdido
              </button>
            </div>
          </form>
        </div>
      )}

      {abertoId && (
        <DealPanel dealId={abertoId} pipeline={funil} usuarios={usuarios}
          onClose={() => setAbertoId(null)} onChanged={carregar} />
      )}
    </div>
  );
}
