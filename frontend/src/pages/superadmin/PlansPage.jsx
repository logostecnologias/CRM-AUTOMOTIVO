import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import Modal from "@/components/ui/Modal";
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

  // A trava de clique repetido vem do Modal.
  const save = async () => {
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

  const [remove, removendo] = useAcao(async (id) => {
    if (!(await confirmToast("Excluir plano?", { confirmLabel: "Excluir" }))) return;
    await api.delete(`/admin/plans/${id}`);
    toast.success("Plano excluído");
    load();
  });

  const num = (v) => (v === "" ? "" : Number(v));

  return (
    <div className="zz-page" data-testid="admin-plans-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Planos</h1>
          <p className="text-ink-2 mt-2 text-sm">Cadastre os planos disponíveis para as empresas.</p>
        </div>
        <button data-testid="new-plan-btn" onClick={openNew} className="zz-btn"><Plus size={14} weight="bold" /> Novo Plano</button>
      </div>

      {editing && (
        <Modal titulo={editing?.id ? "Editar plano" : "Novo plano"}
          descricao="Os limites são aplicados de verdade: a empresa leva 403 ao passar de qualquer um."
          onFechar={() => setEditing(null)} onSalvar={save} largo testId="plan-form"
          corpoClasse="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
            <div className="text-[10px] text-ink-3 mt-1">Vazio = padrão do servidor · 0 = nunca apaga</div>
          </Field>
          <Field label="Disparos de campanha/mês">
            <input type="number" min="0" data-testid="plan-max-disparos" className="zz-input"
              placeholder="ilimitado" value={form.max_disparos_mes}
              onChange={(e) => setForm({ ...form, max_disparos_mes: e.target.value })} />
            <div className="text-[10px] text-ink-3 mt-1">Vazio ou 0 = ilimitado · conta mensagem entregue</div>
          </Field>
        </Modal>
      )}

      <div className="border border-line bg-surface rounded-lg">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-line text-[10px] font-bold uppercase tracking-wider text-ink-3">
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
        {plans.length === 0 && <div className="p-6 text-center text-sm text-ink-3">Nenhum plano cadastrado.</div>}
        {plans.map((p) => (
          <div key={p.id} className="grid grid-cols-12 px-4 py-3 border-b border-line items-center hover:bg-surface-2" data-testid={`plan-row-${p.id}`}>
            <div className="col-span-2 font-semibold">{p.nome}</div>
            <div className="col-span-2 text-sm font-mono">{formatBRL(p.preco_mensal)}</div>
            <div className="col-span-1 text-sm font-mono">{p.max_bots}</div>
            <div className="col-span-1 text-sm font-mono">{p.max_conexoes}</div>
            <div className="col-span-1 text-sm font-mono">{p.max_usuarios}</div>
            <div className="col-span-1 text-sm font-mono text-ink-2">{disparosLabel(p.max_disparos_mes)}</div>
            <div className="col-span-2 text-sm font-mono text-ink-2">{retentionLabel(p.retencao_midia_dias)}</div>
            <div className="col-span-1">
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border rounded-full ${p.status === "active" ? "bg-success-soft border-success text-success" : "bg-danger-soft border-danger text-danger"}`}>
                {p.status === "active" ? "ativo" : "inativo"}
              </span>
            </div>
            <div className="col-span-1 flex gap-1 justify-end">
              <button onClick={() => openEdit(p)} className="p-1.5 hover:bg-surface-3"><PencilSimple size={14} weight="bold" /></button>
              <button onClick={() => remove(p.id)} disabled={removendo}
                className="p-1.5 hover:bg-danger-soft text-danger"><Trash size={14} weight="bold" /></button>
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
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
    </div>
  );
}
