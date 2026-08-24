import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, Trash, PencilSimple } from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import { formatBRL, parseBRLInput } from "@/lib/currency";

const EMPTY = { nome: "", preco_mensal: 0, max_bots: 1, max_conexoes: 1, max_usuarios: 1, retencao_midia_dias: "", max_disparos_mes: "", status: "active" };

// Campo vazio = herda o default do servidor; 0 = guarda pra sempre.
function retentionLabel(dias) {
  if (dias === null || dias === undefined || dias === "") return "padrão";
  return Number(dias) === 0 ? "sempre" : `${dias}d`;
}

// Vazio e 0 significam a mesma coisa aqui (ilimitado) — diferente da
// retenção, onde vazio herda o default e 0 é "nunca apaga".
function disparosLabel(max) {
  if (max === null || max === undefined || max === "" || Number(max) === 0) return "∞";
  return Number(max).toLocaleString("pt-BR");
}

export default function PlansPage() {
  const [plans, setPlans] = useState([]);
  const [editing, setEditing] = useState(null); // null | {} for new, {id,...} for edit
  const [form, setForm] = useState(EMPTY);

  const load = () => api.get("/admin/plans").then((r) => setPlans(r.data));
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(EMPTY); setEditing({}); };
  const openEdit = (p) => {
    setForm({
      nome: p.nome, preco_mensal: p.preco_mensal, max_bots: p.max_bots,
      max_conexoes: p.max_conexoes, max_usuarios: p.max_usuarios,
      retencao_midia_dias: p.retencao_midia_dias ?? "",
      max_disparos_mes: p.max_disparos_mes ?? "", status: p.status,
    });
    setEditing(p);
  };

  const save = async (e) => {
    e.preventDefault();
    // Campo em branco vira null de propósito: é o que diz "herda o default do
    // servidor", diferente de 0, que manda guardar pra sempre.
    const payload = {
      ...form,
      retencao_midia_dias: form.retencao_midia_dias === "" ? null : Number(form.retencao_midia_dias),
      max_disparos_mes: form.max_disparos_mes === "" ? null : Number(form.max_disparos_mes),
    };
    try {
      if (editing?.id) await api.patch(`/admin/plans/${editing.id}`, payload);
      else await api.post("/admin/plans", payload);
      setEditing(null);
      toast.success("Plano salvo");
      load();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao salvar plano");
    }
  };

  const remove = async (id) => {
    if (!(await confirmToast("Excluir plano?", { confirmLabel: "Excluir" }))) return;
    await api.delete(`/admin/plans/${id}`);
    toast.success("Plano excluído");
    load();
  };

  const num = (v) => (v === "" ? "" : Number(v));

  return (
    <div className="p-8" data-testid="admin-plans-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Gestão</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Planos</h1>
          <p className="text-slate-600 mt-2 text-sm">Cadastre os planos disponíveis para as empresas.</p>
        </div>
        <button data-testid="new-plan-btn" onClick={openNew} className="zz-btn"><Plus size={14} weight="bold" /> Novo Plano</button>
      </div>

      {editing && (
        <form onSubmit={save} className="border border-slate-900 bg-white p-6 mb-6 grid grid-cols-3 gap-4 zz-panel-hard" data-testid="plan-form">
          <Field label="Nome">
            <input required autoFocus data-testid="plan-name" className="zz-input" value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })} />
          </Field>
          <Field label="Preço mensal">
            <input required type="text" inputMode="numeric" data-testid="plan-price" className="zz-input"
              value={formatBRL(form.preco_mensal)}
              onChange={(e) => setForm({ ...form, preco_mensal: parseBRLInput(e.target.value) })} />
          </Field>
          <Field label="Status">
            <select className="zz-input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              <option value="active">Ativo</option>
              <option value="inactive">Inativo</option>
            </select>
          </Field>
          <Field label="Máx. Robôs">
            <input required type="number" min="0" data-testid="plan-max-bots" className="zz-input" value={form.max_bots}
              onChange={(e) => setForm({ ...form, max_bots: num(e.target.value) })} />
          </Field>
          <Field label="Máx. Conexões WhatsApp">
            <input required type="number" min="0" data-testid="plan-max-conexoes" className="zz-input" value={form.max_conexoes}
              onChange={(e) => setForm({ ...form, max_conexoes: num(e.target.value) })} />
          </Field>
          <Field label="Máx. Usuários">
            <input required type="number" min="0" data-testid="plan-max-usuarios" className="zz-input" value={form.max_usuarios}
              onChange={(e) => setForm({ ...form, max_usuarios: num(e.target.value) })} />
          </Field>
          <Field label="Retenção de mídia (dias)">
            <input type="number" min="0" data-testid="plan-retencao-midia" className="zz-input"
              placeholder="padrão do servidor" value={form.retencao_midia_dias}
              onChange={(e) => setForm({ ...form, retencao_midia_dias: e.target.value })} />
            <div className="text-[10px] text-slate-500 mt-1">Vazio = padrão do servidor · 0 = nunca apaga</div>
          </Field>
          <Field label="Disparos de campanha/mês">
            <input type="number" min="0" data-testid="plan-max-disparos" className="zz-input"
              placeholder="ilimitado" value={form.max_disparos_mes}
              onChange={(e) => setForm({ ...form, max_disparos_mes: e.target.value })} />
            <div className="text-[10px] text-slate-500 mt-1">Vazio ou 0 = ilimitado · conta mensagem entregue</div>
          </Field>
          <div className="col-span-3 flex gap-2 justify-end">
            <button type="button" onClick={() => setEditing(null)} className="zz-btn zz-btn-secondary">Cancelar</button>
            <button type="submit" data-testid="plan-submit" className="zz-btn">Salvar</button>
          </div>
        </form>
      )}

      <div className="border border-slate-200 bg-white">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          <div className="col-span-2">Nome</div>
          <div className="col-span-2">Preço/mês</div>
          <div className="col-span-1">Robôs</div>
          <div className="col-span-1">Conexões</div>
          <div className="col-span-1">Usuários</div>
          <div className="col-span-1">Disparos</div>
          <div className="col-span-2">Mídia</div>
          <div className="col-span-1">Status</div>
          <div className="col-span-1 text-right">Ações</div>
        </div>
        {plans.length === 0 && <div className="p-6 text-center text-sm text-slate-500">Nenhum plano cadastrado.</div>}
        {plans.map((p) => (
          <div key={p.id} className="grid grid-cols-12 px-4 py-3 border-b border-slate-100 items-center hover:bg-slate-50" data-testid={`plan-row-${p.id}`}>
            <div className="col-span-2 font-semibold">{p.nome}</div>
            <div className="col-span-2 text-sm font-mono">{formatBRL(p.preco_mensal)}</div>
            <div className="col-span-1 text-sm font-mono">{p.max_bots}</div>
            <div className="col-span-1 text-sm font-mono">{p.max_conexoes}</div>
            <div className="col-span-1 text-sm font-mono">{p.max_usuarios}</div>
            <div className="col-span-1 text-sm font-mono text-slate-600">{disparosLabel(p.max_disparos_mes)}</div>
            <div className="col-span-2 text-sm font-mono text-slate-600">{retentionLabel(p.retencao_midia_dias)}</div>
            <div className="col-span-1">
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border ${p.status === "active" ? "bg-green-50 border-green-500 text-green-700" : "bg-red-50 border-red-500 text-red-700"}`}>
                {p.status === "active" ? "ativo" : "inativo"}
              </span>
            </div>
            <div className="col-span-1 flex gap-1 justify-end">
              <button onClick={() => openEdit(p)} className="p-1.5 hover:bg-slate-200"><PencilSimple size={14} weight="bold" /></button>
              <button onClick={() => remove(p.id)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} weight="bold" /></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">{label}</label>
      {children}
    </div>
  );
}
