import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash, X, ArrowUp, ArrowDown } from "@phosphor-icons/react";

const CORES = ["#64748B", "#2563EB", "#F97316", "#8B5CF6", "#10B981", "#EF4444", "#0F172A", "#F59E0B"];
const TIPOS = [["aberta", "Em aberto"], ["ganho", "Ganho"], ["perdido", "Perdido"]];

export default function FunilConfig({ pipeline, onClose, onSaved }) {
  const [nome, setNome] = useState(pipeline.nome);
  const [etapas, setEtapas] = useState([]);
  const [moverPara, setMoverPara] = useState("");
  const [conflito, setConflito] = useState(null);

  useEffect(() => {
    setNome(pipeline.nome);
    setEtapas((pipeline.etapas || []).map((e) => ({ ...e })));
    setConflito(null);
    setMoverPara("");
  }, [pipeline]);

  const alterar = (i, campos) =>
    setEtapas((lista) => lista.map((e, j) => (j === i ? { ...e, ...campos } : e)));

  const mover = (i, delta) => {
    const j = i + delta;
    if (j < 0 || j >= etapas.length) return;
    const copia = [...etapas];
    [copia[i], copia[j]] = [copia[j], copia[i]];
    setEtapas(copia);
  };

  const adicionar = () =>
    setEtapas([...etapas, { id: null, nome: "Nova etapa", cor: CORES[0], tipo: "aberta" }]);

  const remover = (i) => setEtapas(etapas.filter((_, j) => j !== i));

  const salvar = async (e) => {
    e?.preventDefault();
    try {
      await api.patch(`/pipelines/${pipeline.id}`,
        { nome, etapas: etapas.map(({ id, nome: n, cor, tipo }) => ({ id, nome: n, cor, tipo })) },
        { params: moverPara ? { mover_para: moverPara } : {} });
      toast.success("Funil salvo");
      setConflito(null);
      onSaved?.();
      onClose();
    } catch (ex) {
      const detalhe = formatApiErrorDetail(ex.response?.data?.detail);
      // 409 = etapa removida ainda tem negócios. Em vez de só reclamar, mostra
      // o seletor de destino, que é o que resolve.
      if (ex.response?.status === 409) setConflito(detalhe);
      else toast.error(detalhe);
    }
  };

  const restantes = etapas.filter((e) => e.id);

  return (
    <div className="border border-slate-900 bg-white p-5 mb-4 zz-panel-hard" data-testid="funil-config">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="font-heading text-xl font-black tracking-tighter">Etapas do funil</div>
          <p className="text-xs text-slate-600 mt-1">
            A etapa marcada como <strong>Ganho</strong> ou <strong>Perdido</strong> é a que fecha o
            negócio e alimenta os relatórios de conversão.
          </p>
        </div>
        <button onClick={onClose} className="p-1.5 hover:bg-slate-200"><X size={15} weight="bold" /></button>
      </div>

      <form onSubmit={salvar}>
        <div className="mb-4 max-w-sm">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600 block mb-1">
            Nome do funil
          </label>
          <input required className="zz-input h-8 py-1 text-sm" data-testid="funil-nome"
            value={nome} onChange={(e) => setNome(e.target.value)} />
        </div>

        <div className="border border-slate-200 mb-3">
          {etapas.map((etapa, i) => (
            <div key={etapa.id || `nova-${i}`}
              className="flex items-center gap-2 px-3 py-2 border-b border-slate-100 last:border-b-0"
              data-testid={`etapa-row-${i}`}>
              <div className="flex gap-0.5">
                <button type="button" onClick={() => mover(i, -1)} disabled={i === 0}
                  className="p-0.5 hover:bg-slate-200 disabled:opacity-20"><ArrowUp size={11} weight="bold" /></button>
                <button type="button" onClick={() => mover(i, 1)} disabled={i === etapas.length - 1}
                  className="p-0.5 hover:bg-slate-200 disabled:opacity-20"><ArrowDown size={11} weight="bold" /></button>
              </div>
              <input required className="zz-input h-7 py-0 text-sm flex-1" value={etapa.nome}
                onChange={(ev) => alterar(i, { nome: ev.target.value })} />
              <select className="zz-input h-7 py-0 text-xs w-28" value={etapa.tipo}
                onChange={(ev) => alterar(i, { tipo: ev.target.value })}>
                {TIPOS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
              </select>
              <div className="flex gap-0.5">
                {CORES.map((c) => (
                  <button key={c} type="button" onClick={() => alterar(i, { cor: c })}
                    className={`w-5 h-5 border-2 ${etapa.cor === c ? "border-slate-900" : "border-transparent"}`}
                    style={{ background: c }} />
                ))}
              </div>
              <button type="button" onClick={() => remover(i)} disabled={etapas.length === 1}
                className="p-1 hover:bg-red-100 text-red-600 disabled:opacity-20">
                <Trash size={13} weight="bold" />
              </button>
            </div>
          ))}
        </div>

        {conflito && (
          <div className="border-2 border-amber-400 bg-amber-50 p-3 mb-3">
            <div className="text-sm text-slate-800 mb-2">{conflito}</div>
            <div className="flex gap-2 items-center">
              <select className="zz-input h-8 py-1 text-sm max-w-xs" data-testid="mover-para"
                value={moverPara} onChange={(e) => setMoverPara(e.target.value)}>
                <option value="">Mover os negócios para…</option>
                {restantes.map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
              </select>
              <button type="submit" disabled={!moverPara} className="zz-btn text-xs py-1 disabled:opacity-40">
                Mover e salvar
              </button>
            </div>
          </div>
        )}

        <div className="flex gap-2 justify-between">
          <button type="button" onClick={adicionar} className="zz-btn zz-btn-secondary text-xs py-1"
            data-testid="add-etapa">
            <Plus size={13} weight="bold" /> Adicionar etapa
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="zz-btn zz-btn-secondary text-xs py-1">
              Cancelar
            </button>
            <button type="submit" className="zz-btn text-xs py-1" data-testid="funil-submit">Salvar</button>
          </div>
        </div>
      </form>
    </div>
  );
}
