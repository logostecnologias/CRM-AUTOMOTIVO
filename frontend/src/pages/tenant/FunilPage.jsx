import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { formatBRL, parseBRLInput } from "@/lib/currency";
import {
  Plus, SlidersHorizontal, TrendUp, MagnifyingGlass, X, Megaphone, User, Warning,
  BellSlash, PencilSimple, Car, Wallet,
} from "@phosphor-icons/react";
import { Pilula, TEMPERATURAS, PAGAMENTOS } from "@/components/deals/etiquetas";
import Modal from "@/components/ui/Modal";
import { useAcao } from "@/hooks/useAcao";
import { t } from "@/lib/textos";
import DealPanel from "@/components/deals/DealPanel";
import FunilConfig from "@/components/deals/FunilConfig";
import FunilMetricas from "@/components/deals/FunilMetricas";

const iniciaisDe = (nome = "") =>
  nome.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase() || "?";

// "Há 3 dias" desde a última mudança: cartão parado há semanas salta aos olhos.
function haQuanto(iso) {
  if (!iso) return "";
  const min = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 60) return min < 2 ? "agora" : `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h}h`;
  const d = Math.floor(h / 24);
  return d === 1 ? "há 1 dia" : d < 60 ? `há ${d} dias` : `há ${Math.floor(d / 30)} meses`;
}

function Cartao({ deal, onAbrir }) {
  const atrasado = deal.previsao_fechamento && deal.status === "aberto" &&
    new Date(deal.previsao_fechamento) < new Date();
  const nome = deal.contact?.nome || deal.titulo;
  const pag = (deal.pagamento || []).map((p) => PAGAMENTOS.find((x) => x.valor === p)?.rotulo || p);
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", deal.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={() => onAbrir(deal.id)}
      className="zz-cartao-funil border border-line bg-surface p-3 mb-2 cursor-pointer hover:border-line-strong active:opacity-60 rounded-xl"
      data-testid={`deal-card-${deal.id}`}
    >
      <div className="flex items-start gap-2.5">
        <div className="zz-avatar-ini" aria-hidden>{iniciaisDe(nome)}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <div className="text-sm font-semibold leading-tight truncate flex-1">{nome}</div>
            <span className="text-[10px] text-ink-3 shrink-0">{haQuanto(deal.updated_at || deal.created_at)}</span>
          </div>
          {deal.contact?.numero_whatsapp && (
            <div className="text-[11px] font-mono text-ink-3 truncate">{deal.contact.numero_whatsapp}</div>
          )}
        </div>
      </div>

      {(deal.temperatura || deal.origem) && (
        <div className="flex flex-wrap gap-1 mt-2">
          {deal.temperatura && (
            <Pilula classe={deal.temperatura}>
              {TEMPERATURAS.find((x) => x.valor === deal.temperatura)?.rotulo}
            </Pilula>
          )}
          {deal.origem && <Pilula title="Origem">{deal.origem}</Pilula>}
        </div>
      )}

      <div className="mt-2 space-y-1 text-[11.5px] text-ink-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Car size={13} className="shrink-0 text-ink-3" />
          <span className="truncate flex-1">{deal.veiculo?.nome || "Sem interesse"}</span>
          {deal.veiculo?.placa && <span className="font-mono text-[10px] text-ink-3 shrink-0">{deal.veiculo.placa}</span>}
        </div>
        <div className="flex items-center gap-1.5 min-w-0">
          <Wallet size={13} className="shrink-0 text-ink-3" />
          <span className="truncate">{pag.length ? pag.join(" + ") : "Sem forma de pagamento"}</span>
        </div>
      </div>

      <div className="flex items-center gap-2 mt-2 pt-2 border-t border-line">
        <span className="font-mono text-[12px] font-bold">{deal.valor ? formatBRL(deal.valor) : ""}</span>
        {deal.sem_proximo_passo && (
          <span title="Sem próximo passo agendado — abra e agende" className="text-warning">
            <BellSlash size={12} weight="bold" />
          </span>
        )}
        {deal.campanha_id && (
          <span title="Originado de campanha" className="text-ink-4">
            <Megaphone size={11} weight="bold" />
          </span>
        )}
        {deal.previsao_fechamento && (
          <span className={`ml-auto text-[10px] font-mono ${atrasado ? "text-danger font-bold" : "text-ink-3"}`}>
            {new Date(deal.previsao_fechamento).toLocaleDateString("pt-BR")}
          </span>
        )}
      </div>
    </div>
  );
}

// Nome da etapa editável no próprio título da coluna. O modal de etapas
// continua sendo o lugar de reordenar, trocar tipo e cor e remover; renomear e
// criar são as edições do dia a dia, e escondê-las atrás de um botão foi o que
// fez o cliente achar que as etapas não se editavam.
function NomeEditavel({ valor, onSalvar, placeholder, testId, children }) {
  const [editando, setEditando] = useState(false);
  const [texto, setTexto] = useState(valor);
  // Enter fecha o campo, e o campo saindo de foco dispara o blur logo em
  // seguida: sem esta marca, uma etapa nova seria criada duas vezes.
  const fechou = useRef(false);
  useEffect(() => { if (!editando) setTexto(valor); }, [valor, editando]);

  const abrir = () => { fechou.current = false; setEditando(true); };
  const terminar = async (gravar) => {
    if (fechou.current) return;
    fechou.current = true;
    const novo = texto.trim();
    setEditando(false);
    if (gravar && novo && novo !== valor) await onSalvar(novo);
    else setTexto(valor);
  };

  if (!editando) {
    return children(abrir);
  }
  return (
    <input autoFocus className="zz-input h-8 text-xs font-bold" data-testid={testId}
      placeholder={placeholder} value={texto} maxLength={60}
      onChange={(e) => setTexto(e.target.value)}
      onBlur={() => terminar(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); terminar(true); }
        if (e.key === "Escape") { e.preventDefault(); terminar(false); }
      }} />
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
      <div className="flex items-center gap-2 border border-line bg-surface h-9 px-2 rounded-lg">
        <span className="text-sm font-semibold flex-1 truncate">{valor.nome}</span>
        <button type="button" onClick={() => onChange(null)} className="p-0.5 hover:bg-surface-3">
          <X size={12} weight="bold" />
        </button>
      </div>
    );
  }
  return (
    <div className="border border-line bg-surface rounded-lg">
      <input className="zz-input border-0 h-9" placeholder={`Buscar ${t("contato")}…`} data-testid="deal-contact-search"
        value={busca} onChange={(e) => setBusca(e.target.value)} />
      {busca && (
        <div className="max-h-36 overflow-y-auto border-t border-line">
          {achados.length === 0 && <div className="p-2 text-xs text-ink-3">Nada encontrado.</div>}
          {achados.map((c) => (
            <button key={c.id} type="button" onClick={() => { onChange(c); setBusca(""); }}
              className="w-full text-left flex items-center gap-2 px-2 py-1.5 border-b border-line hover:bg-surface-2">
              <span className="text-sm font-semibold flex-1 truncate">{c.nome}</span>
              <span className="text-[11px] font-mono text-ink-3">{c.numero_whatsapp}</span>
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
    // Vindo da tela de treino do agente ("Editar as etapas").
    if (params.get("etapas")) setConfig(true);
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

  // A trava de clique repetido vem do Modal.
  const criar = async () => {
    if (!novo.contato) return toast.error(`Escolha o ${t("contato")} do ${t("negócio")}`);
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
      toast.success(`${t("Negócio")} criado`);
      carregar();
      setAbertoId(r.data.id);
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const funil = quadro?.pipeline;

  // Renomear e criar etapa direto no quadro. Mandam a lista inteira, como o
  // modal: é o mesmo PATCH, e o id de cada etapa é o que mantém os negócios
  // ligados a ela depois do rename.
  const [gravarEtapas] = useAcao(async (etapas) => {
    try {
      await api.patch(`/pipelines/${funil.id}`, {
        nome: funil.nome,
        etapas: etapas.map(({ id, nome, cor, tipo }) => ({ id: id || null, nome, cor, tipo })),
      });
      api.get("/pipelines").then((r) => setFunis(r.data)).catch(() => {});
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  });
  const etapasDoFunil = () =>
    [...(funil?.etapas || [])].sort((a, b) => (a.ordem || 0) - (b.ordem || 0));
  const renomearEtapa = (id, nome) =>
    gravarEtapas(etapasDoFunil().map((e) => (e.id === id ? { ...e, nome } : e)));
  // A etapa nova entra antes de Ganho/Perdido: depois deles ela seria uma
  // etapa em aberto no fim do funil, onde ninguém procura.
  const criarEtapa = (nome) => {
    const lista = etapasDoFunil();
    const i = lista.findIndex((e) => e.tipo !== "aberta");
    const nova = { id: null, nome, cor: "#64748B", tipo: "aberta" };
    gravarEtapas(i < 0 ? [...lista, nova] : [...lista.slice(0, i), nova, ...lista.slice(i)]);
  };
  const totalAberto = (quadro?.colunas || [])
    .filter((c) => c.etapa.tipo === "aberta")
    .reduce((acc, c) => acc + (c.valor || 0), 0);

  return (
    <div className={`p-8 ${abertoId ? "pr-[500px]" : ""}`} data-testid="funil-page">
      <div className="flex items-end justify-between mb-6 gap-4">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">{t("Funil de negócios")}</h1>
          <p className="text-ink-2 mt-2 text-sm">
            Arraste o cartão entre as etapas. {formatBRL(totalAberto)} em aberto no {t("funil")}.
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
            <SlidersHorizontal size={14} weight="bold" /> Editar etapas
          </button>
          <button onClick={() => setNovo({ titulo: "", valor: 0, contato: null, responsavel_id: "", previsao: "" })}
            className="zz-btn" data-testid="new-deal-btn" disabled={!funilId}>
            <Plus size={14} weight="bold" /> Novo {t("negócio")}
          </button>
        </div>
      </div>

      {metricas && funilId && (
        <Modal titulo={`Desempenho do ${t("funil")}`} largo onFechar={() => setMetricas(false)}>
          <FunilMetricas pipelineId={funilId} semMoldura />
        </Modal>
      )}
      {config && funil && (
        <FunilConfig pipeline={funil} onClose={() => setConfig(false)}
          onSaved={() => {
            api.get("/pipelines").then((r) => setFunis(r.data)).catch(() => {});
            carregar();
          }} />
      )}

      {novo && (
        <Modal titulo={`Novo ${t("negócio")}`}
          descricao={`O ${t("negócio")} é o que gera conversão, ticket médio e ciclo de venda — a conversa sozinha não.`}
          onFechar={() => setNovo(null)} onSalvar={criar}
          salvarLabel="Criar" salvandoLabel="Criando…" testId="new-deal-form"
          corpoClasse="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="sm:col-span-2">
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Título</label>
            <input required autoFocus className="zz-input" data-testid="new-deal-title"
              placeholder="Plano anual, orçamento de reforma…"
              value={novo.titulo} onChange={(e) => setNovo({ ...novo, titulo: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{t("Contato")}</label>
            <SeletorContato valor={novo.contato} onChange={(c) => setNovo({ ...novo, contato: c })} />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Valor</label>
            <input className="zz-input font-mono" data-testid="new-deal-value"
              value={formatBRL(novo.valor)}
              onChange={(e) => setNovo({ ...novo, valor: parseBRLInput(e.target.value) })} />
          </div>
        </Modal>
      )}

      <div className="flex gap-3 items-center mb-4">
        <div className="relative flex-1 max-w-xs">
          <MagnifyingGlass size={14} weight="bold" className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
          <input className="zz-input pl-8" placeholder={`Buscar ${t("negócio")}…`} data-testid="deal-search"
            value={busca} onChange={(e) => setBusca(e.target.value)} />
        </div>
        <select className="zz-input max-w-[200px]" data-testid="deal-owner-filter"
          value={responsavel} onChange={(e) => setResponsavel(e.target.value)}>
          <option value="">Todos os responsáveis</option>
          {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
        </select>
        {(busca || responsavel) && (
          <button onClick={() => { setBusca(""); setResponsavel(""); }} className="p-1.5 hover:bg-surface-3">
            <X size={14} weight="bold" />
          </button>
        )}
      </div>

      {!quadro ? (
        <div className="text-xs font-bold uppercase tracking-[0.25em] text-ink-3 py-8">Carregando quadro…</div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-4 items-start">
          {quadro.colunas.map((coluna) => (
            <div key={coluna.etapa.id}
              onDragOver={(e) => { e.preventDefault(); setArrastandoSobre(coluna.etapa.id); }}
              onDragLeave={() => setArrastandoSobre((a) => (a === coluna.etapa.id ? null : a))}
              onDrop={(e) => soltar(e, coluna.etapa)}
              className={`w-[240px] shrink-0 bg-surface-2 border rounded-xl ${
                arrastandoSobre === coluna.etapa.id ? "border-info border-2 bg-info-soft" : "border-line"
              }`}
              data-testid={`funil-coluna-${coluna.etapa.id}`}>
              <div className="px-3 py-2 border-b border-line bg-surface"
                style={{ borderTop: `3px solid ${coluna.etapa.cor}` }}>
                <NomeEditavel valor={coluna.etapa.nome} testId={`etapa-nome-${coluna.etapa.id}`}
                  onSalvar={(nome) => renomearEtapa(coluna.etapa.id, nome)}>
                  {(editar) => (
                    <div className="flex items-center justify-between gap-1 group">
                      <button type="button" onClick={editar} title="Renomear etapa"
                        className="flex items-center gap-1 min-w-0 text-left"
                        data-testid={`etapa-renomear-${coluna.etapa.id}`}>
                        <span className="text-xs font-bold uppercase tracking-wider truncate">{coluna.etapa.nome}</span>
                        <PencilSimple size={11} weight="bold"
                          className="shrink-0 text-ink-4 opacity-0 group-hover:opacity-100" />
                      </button>
                      <span className="text-[10px] font-mono text-ink-3 shrink-0">{coluna.n}</span>
                    </div>
                  )}
                </NomeEditavel>
                <div className="font-mono text-xs font-bold text-ink">
                  {formatBRL(coluna.valor)}{coluna.valor_parcial ? "+" : ""}
                </div>
              </div>
              <div className="p-2 min-h-[120px] max-h-[calc(100vh-436px)] overflow-y-auto">
                {coluna.deals.length === 0 && (
                  <div className="text-[11px] text-ink-4 text-center py-6">Arraste um cartão para cá</div>
                )}
                {coluna.deals.map((d) => <Cartao key={d.id} deal={d} onAbrir={setAbertoId} />)}
                {coluna.truncada && (
                  <div className="text-[10px] text-ink-3 text-center py-1 border-t border-line">
                    mostrando {coluna.deals.length} de {coluna.n}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div className="w-[200px] shrink-0">
            <NomeEditavel valor="" placeholder="Nome da etapa" testId="nova-etapa-nome"
              onSalvar={criarEtapa}>
              {(editar) => (
                <button type="button" onClick={editar} data-testid="nova-etapa"
                  className="w-full flex items-center justify-center gap-1.5 border border-dashed border-line-strong rounded-xl py-3 text-xs font-semibold text-ink-3 hover:text-ink hover:border-info">
                  <Plus size={13} weight="bold" /> Nova etapa
                </button>
              )}
            </NomeEditavel>
          </div>
        </div>
      )}

      {perda && (
        <Modal titulo={t("Por que perdemos?")}
          descricao={`É este campo que alimenta o relatório de motivos de perda. Pode deixar em branco, mas aí o ${t("negócio")} entra como "não informado".`}
          onFechar={() => setPerda(null)}
          onSalvar={() => { mover(perda.dealId, perda.etapaId, perda.motivo); setPerda(null); }}
          salvarLabel={`Marcar como ${t("perdido")}`} testId="motivo-perda-dialog">
          <div className="flex items-center gap-2 text-danger">
            <Warning size={18} weight="bold" />
            <span className="text-sm font-semibold">{t("Este negócio sai do funil como perdido.")}</span>
          </div>
          <input autoFocus className="zz-input" data-testid="motivo-perda-input"
            placeholder="Preço, prazo, escolheu concorrente…"
            value={perda.motivo} onChange={(e) => setPerda({ ...perda, motivo: e.target.value })} />
        </Modal>
      )}

      {abertoId && (
        <DealPanel dealId={abertoId} pipeline={funil} usuarios={usuarios}
          onClose={() => setAbertoId(null)} onChanged={carregar} />
      )}
    </div>
  );
}
