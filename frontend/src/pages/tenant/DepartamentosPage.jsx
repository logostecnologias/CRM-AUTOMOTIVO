import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, Trash, PencilSimple } from "@phosphor-icons/react";
import { toast, Toaster } from "sonner";

const DEFAULT_COLORS = ["#2563EB", "#10B981", "#F97316", "#EC4899", "#8B5CF6", "#EF4444", "#0F172A", "#F59E0B"];

export default function DepartamentosPage() {
  const [depts, setDepts] = useState([]);
  const [editing, setEditing] = useState(null); // null | {} for new, {id,...} for edit
  const [form, setForm] = useState({ nome: "", cor: DEFAULT_COLORS[0] });

  const load = () => api.get("/departments").then((r) => setDepts(r.data));
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm({ nome: "", cor: DEFAULT_COLORS[0] }); setEditing({}); };
  const openEdit = (d) => { setForm({ nome: d.nome, cor: d.cor }); setEditing(d); };

  const save = async (e) => {
    e.preventDefault();
    try {
      if (editing?.id) await api.patch(`/departments/${editing.id}`, form);
      else await api.post("/departments", form);
      setEditing(null);
      toast.success("Departamento salvo");
      load();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao salvar");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Excluir departamento?")) return;
    await api.delete(`/departments/${id}`);
    load();
  };

  return (
    <div className="p-8 max-w-4xl" data-testid="departments-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Organização</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Departamentos</h1>
          <p className="text-slate-600 mt-2 text-sm">Agrupe conexões e conversas por área (ex: Vendas, Suporte, Financeiro).</p>
        </div>
        <button data-testid="new-dept-btn" onClick={openNew} className="zz-btn"><Plus size={14} weight="bold" /> Novo</button>
      </div>

      {editing && (
        <form onSubmit={save} className="mb-6 border border-slate-900 bg-white p-4 flex gap-3 items-end zz-panel-hard" data-testid="dept-form">
          <div className="flex-1">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Nome</label>
            <input required autoFocus className="zz-input" data-testid="dept-name" value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Cor</label>
            <div className="flex gap-1">
              {DEFAULT_COLORS.map((c) => (
                <button key={c} type="button" onClick={() => setForm({ ...form, cor: c })}
                  className={`w-7 h-7 border-2 ${form.cor === c ? "border-slate-900" : "border-slate-300"}`}
                  style={{ background: c }} />
              ))}
            </div>
          </div>
          <button type="submit" className="zz-btn" data-testid="dept-submit">Salvar</button>
          <button type="button" onClick={() => setEditing(null)} className="zz-btn zz-btn-secondary">Cancelar</button>
        </form>
      )}

      <div className="border border-slate-200 bg-white">
        {depts.length === 0 && <div className="p-6 text-sm text-slate-500 text-center">Nenhum departamento cadastrado.</div>}
        {depts.map((d) => (
          <div key={d.id} className="flex items-center justify-between px-4 py-3 border-b border-slate-100 hover:bg-slate-50" data-testid={`dept-row-${d.id}`}>
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 border border-slate-900" style={{ background: d.cor }} />
              <span className="font-semibold">{d.nome}</span>
              <span className="text-xs font-mono text-slate-500">{d.cor}</span>
            </div>
            <div className="flex gap-1">
              <button onClick={() => openEdit(d)} className="p-1.5 hover:bg-slate-200"><PencilSimple size={14} weight="bold" /></button>
              <button onClick={() => remove(d.id)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} weight="bold" /></button>
            </div>
          </div>
        ))}
      </div>
      <Toaster position="bottom-right" />
    </div>
  );
}
