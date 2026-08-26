import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import { Plus, Trash, PencilSimple, X } from "@phosphor-icons/react";

const TIPOS = [
  ["texto", "Texto"],
  ["numero", "Número"],
  ["data", "Data"],
  ["selecao", "Lista de opções"],
];

const VAZIO = { nome: "", tipo: "texto", opcoes: [], ordem: 0 };

export default function FieldsManager({ onClose, onChanged }) {
  const [campos, setCampos] = useState([]);
  const [form, setForm] = useState(null);
  const [opcoesTexto, setOpcoesTexto] = useState("");

  const carregar = () => api.get("/contacts/fields").then((r) => setCampos(r.data)).catch(() => {});
  useEffect(() => { carregar(); }, []);

  const abrirNovo = () => {
    setForm({ ...VAZIO, ordem: campos.length });
    setOpcoesTexto("");
  };

  const abrirEdicao = (c) => {
    setForm({ id: c.id, nome: c.nome, tipo: c.tipo, opcoes: c.opcoes || [], ordem: c.ordem || 0 });
    setOpcoesTexto((c.opcoes || []).join(", "));
  };

  const [salvar, salvando] = useAcao(async (e) => {
    e.preventDefault();
    const payload = {
      nome: form.nome,
      tipo: form.tipo,
      opcoes: form.tipo === "selecao"
        ? opcoesTexto.split(",").map((o) => o.trim()).filter(Boolean)
        : [],
      ordem: Number(form.ordem) || 0,
    };
    try {
      if (form.id) await api.patch(`/contacts/fields/${form.id}`, payload);
      else await api.post("/contacts/fields", payload);
      setForm(null);
      toast.success("Campo salvo");
      carregar();
      onChanged?.();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  });

  const [remover, removendo] = useAcao(async (c) => {
    if (!(await confirmToast(
      `Excluir o campo "${c.nome}"? O valor dele sai de todas as fichas.`,
      { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/contacts/fields/${c.id}`);
      toast.success("Campo excluído");
      carregar();
      onChanged?.();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  });

  return (
    <div className="border border-line-strong bg-surface p-6 mb-6 zz-panel-hard rounded-lg" data-testid="fields-manager">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="font-heading text-xl font-black tracking-tighter">Campos personalizados</div>
          <p className="text-xs text-ink-2 mt-1">
            Aparecem na ficha de todo contato desta empresa. Ex: número da apólice, curso de interesse, placa.
          </p>
        </div>
        <div className="flex gap-1">
          <button onClick={abrirNovo} className="zz-btn text-xs py-1" data-testid="new-field-btn">
            <Plus size={13} weight="bold" /> Novo campo
          </button>
          <button onClick={onClose} className="p-1.5 hover:bg-surface-3"><X size={15} weight="bold" /></button>
        </div>
      </div>

      {form && (
        <form onSubmit={salvar} className="border border-line bg-surface-2 p-4 mb-4 flex gap-3 items-end flex-wrap rounded-lg"
          data-testid="field-form">
          <div className="flex-1 min-w-[160px]">
            <label className="text-[10px] font-bold uppercase tracking-wider text-ink-2 block mb-1">Nome</label>
            <input required autoFocus className="zz-input h-8 py-1 text-sm" data-testid="field-name"
              value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-ink-2 block mb-1">Tipo</label>
            <select className="zz-input h-8 py-1 text-sm" data-testid="field-type"
              value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
              {TIPOS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
            </select>
          </div>
          {form.tipo === "selecao" && (
            <div className="flex-1 min-w-[200px]">
              <label className="text-[10px] font-bold uppercase tracking-wider text-ink-2 block mb-1">
                Opções (separadas por vírgula)
              </label>
              <input required className="zz-input h-8 py-1 text-sm" data-testid="field-options"
                placeholder="Bronze, Prata, Ouro"
                value={opcoesTexto} onChange={(e) => setOpcoesTexto(e.target.value)} />
            </div>
          )}
          <div className="w-20">
            <label className="text-[10px] font-bold uppercase tracking-wider text-ink-2 block mb-1">Ordem</label>
            <input type="number" className="zz-input h-8 py-1 text-sm" value={form.ordem}
              onChange={(e) => setForm({ ...form, ordem: e.target.value })} />
          </div>
          <button type="submit" className="zz-btn text-xs py-1" data-testid="field-submit"
            disabled={salvando}>{salvando ? "Salvando…" : "Salvar"}</button>
          <button type="button" onClick={() => setForm(null)} className="zz-btn zz-btn-secondary text-xs py-1">
            Cancelar
          </button>
        </form>
      )}

      <div className="border border-line rounded-lg">
        {campos.length === 0 && (
          <div className="p-4 text-center text-xs text-ink-3">
            Nenhum campo personalizado. A ficha usa só os campos padrão.
          </div>
        )}
        {campos.map((c) => (
          <div key={c.id} className="flex items-center gap-3 px-3 py-2 border-b border-line last:border-b-0 hover:bg-surface-2"
            data-testid={`field-row-${c.id}`}>
            <span className="font-semibold text-sm flex-1">{c.nome}</span>
            <span className="text-[10px] font-bold uppercase tracking-wider text-ink-3">
              {TIPOS.find(([v]) => v === c.tipo)?.[1] || c.tipo}
            </span>
            {c.tipo === "selecao" && (
              <span className="text-[10px] font-mono text-ink-3 truncate max-w-[200px]">
                {(c.opcoes || []).join(" · ")}
              </span>
            )}
            <button onClick={() => abrirEdicao(c)} className="p-1 hover:bg-surface-3">
              <PencilSimple size={13} weight="bold" />
            </button>
            <button onClick={() => remover(c)} disabled={removendo}
              className="p-1 hover:bg-danger-soft text-danger">
              <Trash size={13} weight="bold" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
