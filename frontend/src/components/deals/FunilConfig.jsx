import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash, ArrowUp, ArrowDown } from "@phosphor-icons/react";
import Modal from "@/components/ui/Modal";
import { t } from "@/lib/textos";

const CORES = ["#64748B", "#2563EB", "#F97316", "#8B5CF6", "#10B981", "#EF4444", "#0F172A", "#F59E0B"];
const TIPOS = [["aberta", "Em aberto"], ["ganho", "Ganho"], ["perdido", "Perdido"]];

// Evento enviado ao Meta quando o negócio entra na etapa (ver
// backend/meta_conversoes.py). Só tem efeito com a integração ligada em Ajustes.
const EVENTOS_META = [
  ["", "Meta: nenhum"],
  ["LeadSubmitted", "Meta: Lead"],
  ["QualifiedLead", "Meta: Lead qualificado"],
  ["InitiateCheckout", "Meta: Proposta"],
  ["Purchase", "Meta: Compra"],
];

/** Mesmo padrão do backend para etapa que nunca foi configurada: a primeira
 * etapa em aberto é o lead, a de ganho é a compra. */
function eventoPadrao(etapa, i) {
  if (etapa.tipo === "ganho") return "Purchase";
  if (i === 0 && etapa.tipo === "aberta") return "LeadSubmitted";
  return "";
}

export default function FunilConfig({ pipeline, onClose, onSaved }) {
  const [nome, setNome] = useState(pipeline.nome);
  const [etapas, setEtapas] = useState([]);
  const [moverPara, setMoverPara] = useState("");
  const [conflito, setConflito] = useState(null);

  useEffect(() => {
    setNome(pipeline.nome);
    setEtapas((pipeline.etapas || []).map((e, i) => ({
      ...e, evento_meta: "evento_meta" in e ? e.evento_meta || "" : eventoPadrao(e, i),
    })));
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
    setEtapas([...etapas, { id: null, nome: "Nova etapa", cor: CORES[0], tipo: "aberta", evento_meta: "" }]);

  const remover = (i) => setEtapas(etapas.filter((_, j) => j !== i));

  // A trava de clique repetido vem do Modal.
  const salvar = async () => {
    try {
      await api.patch(`/pipelines/${pipeline.id}`,
        { nome, etapas: etapas.map(({ id, nome: n, cor, tipo, evento_meta }) => ({ id, nome: n, cor, tipo, evento_meta: evento_meta || "" })) },
        { params: moverPara ? { mover_para: moverPara } : {} });
      toast.success(t("Funil salvo"));
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
    <Modal titulo={`Etapas do ${t("funil")}`} largo
      descricao={`A etapa marcada como ${t("Ganho")} ou ${t("Perdido")} é a que fecha o ${t("negócio")} e alimenta os relatórios de conversão. O evento do Meta é enviado quando o ${t("negócio")} entra na etapa, se a integração estiver ligada em Ajustes.`}
      onFechar={onClose} onSalvar={salvar} testId="funil-config"
      rodape={(
        <button type="button" onClick={adicionar} className="zz-btn zz-btn-secondary mr-auto"
          data-testid="add-etapa">
          <Plus size={13} weight="bold" /> Adicionar etapa
        </button>
      )}>
      <div className="max-w-sm">
        <label className="text-[10px] font-bold uppercase tracking-wider text-ink-2 block mb-1">
          Nome do {t("funil")}
        </label>
        <input required className="zz-input" data-testid="funil-nome"
          value={nome} onChange={(e) => setNome(e.target.value)} />
      </div>

      <div className="border border-line mb-3 rounded-lg">
        {etapas.map((etapa, i) => (
          <div key={etapa.id || `nova-${i}`}
            className="flex items-center gap-2 px-3 py-2 border-b border-line last:border-b-0"
            data-testid={`etapa-row-${i}`}>
            <div className="flex gap-0.5">
              <button type="button" onClick={() => mover(i, -1)} disabled={i === 0}
                className="p-0.5 hover:bg-surface-3 disabled:opacity-20"><ArrowUp size={11} weight="bold" /></button>
              <button type="button" onClick={() => mover(i, 1)} disabled={i === etapas.length - 1}
                className="p-0.5 hover:bg-surface-3 disabled:opacity-20"><ArrowDown size={11} weight="bold" /></button>
            </div>
            <input required className="zz-input h-8 text-sm flex-1" value={etapa.nome}
              onChange={(ev) => alterar(i, { nome: ev.target.value })} />
            <select className="zz-input h-8 text-xs w-32" value={etapa.tipo}
              onChange={(ev) => alterar(i, { tipo: ev.target.value })}>
              {TIPOS.map(([v, r]) => <option key={v} value={v}>{t(r)}</option>)}
            </select>
            <select className="zz-input h-8 text-xs w-40" value={etapa.evento_meta || ""}
              title="Evento enviado ao Meta quando o negócio entra nesta etapa"
              data-testid={`etapa-evento-meta-${i}`}
              onChange={(ev) => alterar(i, { evento_meta: ev.target.value })}>
              {EVENTOS_META.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
            </select>
            <div className="flex gap-0.5">
              {CORES.map((c) => (
                <button key={c} type="button" onClick={() => alterar(i, { cor: c })}
                  className={`w-5 h-5 rounded-md border-2 ${etapa.cor === c ? "border-ink" : "border-transparent"}`}
                  style={{ background: c }} />
              ))}
            </div>
            <button type="button" onClick={() => remover(i)} disabled={etapas.length === 1}
              className="p-1 hover:bg-danger-soft text-danger disabled:opacity-20">
              <Trash size={13} weight="bold" />
            </button>
          </div>
        ))}
      </div>

      {conflito && (
        <div className="border border-warning bg-warning-soft p-3 mb-3 rounded-lg">
          <div className="text-sm text-ink mb-2">{conflito}</div>
          <div className="flex gap-2 items-center">
            <select className="zz-input h-8 py-1 text-sm max-w-xs" data-testid="mover-para"
              value={moverPara} onChange={(e) => setMoverPara(e.target.value)}>
              <option value="">Mover os {t("negócios")} para…</option>
              {restantes.map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
            </select>
            <button type="submit" disabled={!moverPara} className="zz-btn text-xs py-1 disabled:opacity-40">
              Mover e salvar
            </button>
          </div>
        </div>
      )}

    </Modal>
  );
}
