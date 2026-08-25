import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, PauseCircle, PlayCircle, Trash, SignIn } from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import { formatBRL } from "@/lib/currency";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function TenantsPage() {
  const [tenants, setTenants] = useState([]);
  const [plans, setPlans] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", plan_id: "", admin_name: "", admin_email: "", admin_password: "" });
  const [err, setErr] = useState("");
  const nav = useNavigate();
  const { refresh } = useAuth();

  const impersonate = async (t) => {
    try {
      await api.post(`/admin/tenants/${t.id}/impersonate`);
      await refresh();
      nav("/app");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao entrar na empresa");
    }
  };

  const load = () => api.get("/admin/tenants").then((r) => setTenants(r.data));
  const loadPlans = () => api.get("/admin/plans").then((r) => setPlans(r.data));
  useEffect(() => { load(); loadPlans(); }, []);

  const create = async (e) => {
    e.preventDefault(); setErr("");
    try {
      await api.post("/admin/tenants", form);
      setShowForm(false);
      setForm({ name: "", plan_id: "", admin_name: "", admin_email: "", admin_password: "" });
      toast.success("Empresa criada com sucesso");
      load();
    } catch (ex) {
      setErr(ex.response?.data?.detail || "Erro ao criar empresa");
    }
  };

  const changePlan = async (t, planId) => {
    if (!planId || planId === t.plan_id) return;
    try {
      const { data } = await api.patch(`/admin/tenants/${t.id}`, { plan_id: planId });
      if (data.plan_warnings?.length) {
        toast.warning(`Plano alterado, mas a empresa está acima do limite: ${data.plan_warnings.join(" · ")}`, { duration: 8000 });
      } else {
        toast.success("Plano atualizado");
      }
      load();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao atualizar plano");
    }
  };

  const toggle = async (t) => {
    const next = t.status === "active" ? "suspended" : "active";
    await api.patch(`/admin/tenants/${t.id}`, { status: next });
    load();
  };

  const remove = async (id) => {
    if (!(await confirmToast("Excluir empresa e TODOS os dados vinculados?", { confirmLabel: "Excluir tudo" }))) return;
    await api.delete(`/admin/tenants/${id}`);
    toast.success("Empresa excluída");
    load();
  };

  return (
    <div className="zz-page" data-testid="admin-tenants-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-ink-3 mb-2">Gestão</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Empresas</h1>
        </div>
        <button data-testid="new-tenant-btn" onClick={() => setShowForm(!showForm)} className="zz-btn">
          <Plus size={16} weight="bold" /> Nova Empresa
        </button>
      </div>

      {showForm && (
        <form onSubmit={create} className="border border-line-strong bg-surface p-6 mb-6 grid grid-cols-1 sm:grid-cols-2 gap-4 zz-panel-hard rounded-lg">
          <Field label="Nome da Empresa"><input required data-testid="tenant-name" className="zz-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Plano">
            {plans.length === 0 ? (
              <div className="text-xs text-ink-3 italic py-2">Nenhum plano cadastrado — crie um em "Planos" primeiro.</div>
            ) : (
              <select required data-testid="tenant-plan" className="zz-input" value={form.plan_id} onChange={(e) => setForm({ ...form, plan_id: e.target.value })}>
                <option value="" disabled>Selecione um plano</option>
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>{p.nome} — {formatBRL(p.preco_mensal)}/mês</option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Nome do Admin"><input required data-testid="admin-name" className="zz-input" value={form.admin_name} onChange={(e) => setForm({ ...form, admin_name: e.target.value })} /></Field>
          <Field label="Email do Admin"><input required type="email" data-testid="admin-email" className="zz-input" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} /></Field>
          <Field label="Senha inicial do Admin"><input required data-testid="admin-password" className="zz-input" value={form.admin_password} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></Field>
          <div className="col-span-2 flex gap-2 justify-end items-center">
            {err && <div className="text-sm text-danger mr-auto">{err}</div>}
            <button type="button" onClick={() => setShowForm(false)} className="zz-btn zz-btn-secondary">Cancelar</button>
            <button type="submit" data-testid="tenant-submit" className="zz-btn">Criar Empresa</button>
          </div>
        </form>
      )}

      <div className="border border-line bg-surface rounded-lg">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-line text-[10px] font-bold uppercase tracking-wider text-ink-3">
          <div className="col-span-3">Nome</div>
          <div className="col-span-3">Plano</div>
          <div className="col-span-2">Status</div>
          <div className="col-span-1">Robôs</div>
          <div className="col-span-2">Criado em</div>
          <div className="col-span-1 text-right">Ações</div>
        </div>
        {tenants.length === 0 && <div className="p-6 text-center text-sm text-ink-3">Nenhuma empresa cadastrada.</div>}
        {tenants.map((t) => (
          <div key={t.id} className="grid grid-cols-12 px-4 py-3 border-b border-line items-center hover:bg-surface-2" data-testid={`tenant-row-${t.id}`}>
            <div className="col-span-3 font-semibold">{t.name}</div>
            <div className="col-span-3 pr-3">
              {plans.length === 0 ? (
                <span className="text-xs italic text-ink-4">nenhum plano cadastrado</span>
              ) : (
                <select
                  className="zz-input text-xs py-1"
                  data-testid={`tenant-plan-${t.id}`}
                  value={t.plan_id || ""}
                  onChange={(e) => changePlan(t, e.target.value)}
                >
                  {!t.plan_id && <option value="" disabled>sem plano</option>}
                  {plans.map((p) => (
                    <option key={p.id} value={p.id}>{p.nome} — {formatBRL(p.preco_mensal)}</option>
                  ))}
                </select>
              )}
            </div>
            <div className="col-span-2">
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border rounded-full ${t.status === "active" ? "bg-success-soft border-success text-success" : "bg-danger-soft border-danger text-danger"}`}>{t.status}</span>
            </div>
            <div className="col-span-1 font-mono text-sm">{t.bots_count}</div>
            <div className="col-span-2 text-xs text-ink-3 font-mono">{new Date(t.created_at).toLocaleDateString("pt-BR")}</div>
            <div className="col-span-1 flex gap-1 justify-end">
              <button onClick={() => impersonate(t)} className="p-1.5 hover:bg-info-soft text-info" title="Entrar na empresa" data-testid={`impersonate-${t.id}`}><SignIn size={16} weight="bold" /></button>
              <button onClick={() => toggle(t)} className="p-1.5 hover:bg-surface-3" title={t.status === "active" ? "Suspender" : "Reativar"}>
                {t.status === "active" ? <PauseCircle size={16} weight="bold" /> : <PlayCircle size={16} weight="bold" />}
              </button>
              <button onClick={() => remove(t.id)} className="p-1.5 hover:bg-danger-soft text-danger" title="Excluir"><Trash size={16} weight="bold" /></button>
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
