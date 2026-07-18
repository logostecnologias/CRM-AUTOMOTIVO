import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, PauseCircle, PlayCircle, Trash, SignIn } from "@phosphor-icons/react";
import { toast, Toaster } from "sonner";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function TenantsPage() {
  const [tenants, setTenants] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", plan: "starter", admin_name: "", admin_email: "", admin_password: "" });
  const [err, setErr] = useState("");
  const nav = useNavigate();
  const { refresh } = useAuth();

  const impersonate = async (t) => {
    await api.post(`/admin/tenants/${t.id}/impersonate`);
    await refresh();
    nav("/app");
  };

  const load = () => api.get("/admin/tenants").then((r) => setTenants(r.data));
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault(); setErr("");
    try {
      await api.post("/admin/tenants", form);
      setShowForm(false);
      setForm({ name: "", plan: "starter", admin_name: "", admin_email: "", admin_password: "" });
      toast.success("Empresa criada com sucesso");
      load();
    } catch (ex) {
      setErr(ex.response?.data?.detail || "Erro ao criar empresa");
    }
  };

  const toggle = async (t) => {
    const next = t.status === "active" ? "suspended" : "active";
    await api.patch(`/admin/tenants/${t.id}`, { status: next });
    load();
  };

  const remove = async (id) => {
    if (!window.confirm("Excluir empresa e TODOS os dados vinculados?")) return;
    await api.delete(`/admin/tenants/${id}`);
    load();
  };

  return (
    <div className="p-8" data-testid="admin-tenants-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Gestão</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Empresas</h1>
        </div>
        <button data-testid="new-tenant-btn" onClick={() => setShowForm(!showForm)} className="zz-btn">
          <Plus size={16} weight="bold" /> Nova Empresa
        </button>
      </div>

      {showForm && (
        <form onSubmit={create} className="border border-slate-900 bg-white p-6 mb-6 grid grid-cols-2 gap-4 zz-panel-hard">
          <Field label="Nome da Empresa"><input required data-testid="tenant-name" className="zz-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Plano">
            <select className="zz-input" value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })}>
              <option>starter</option><option>pro</option><option>enterprise</option>
            </select>
          </Field>
          <Field label="Nome do Admin"><input required data-testid="admin-name" className="zz-input" value={form.admin_name} onChange={(e) => setForm({ ...form, admin_name: e.target.value })} /></Field>
          <Field label="Email do Admin"><input required type="email" data-testid="admin-email" className="zz-input" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} /></Field>
          <Field label="Senha inicial do Admin"><input required data-testid="admin-password" className="zz-input" value={form.admin_password} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></Field>
          <div className="col-span-2 flex gap-2 justify-end items-center">
            {err && <div className="text-sm text-red-600 mr-auto">{err}</div>}
            <button type="button" onClick={() => setShowForm(false)} className="zz-btn zz-btn-secondary">Cancelar</button>
            <button type="submit" data-testid="tenant-submit" className="zz-btn">Criar Empresa</button>
          </div>
        </form>
      )}

      <div className="border border-slate-200 bg-white">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          <div className="col-span-4">Nome</div>
          <div className="col-span-2">Plano</div>
          <div className="col-span-2">Status</div>
          <div className="col-span-1">Robôs</div>
          <div className="col-span-2">Criado em</div>
          <div className="col-span-1 text-right">Ações</div>
        </div>
        {tenants.length === 0 && <div className="p-6 text-center text-sm text-slate-500">Nenhuma empresa cadastrada.</div>}
        {tenants.map((t) => (
          <div key={t.id} className="grid grid-cols-12 px-4 py-3 border-b border-slate-100 items-center hover:bg-slate-50" data-testid={`tenant-row-${t.id}`}>
            <div className="col-span-4 font-semibold">{t.name}</div>
            <div className="col-span-2 text-xs font-mono">{t.plan}</div>
            <div className="col-span-2">
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border ${t.status === "active" ? "bg-green-50 border-green-500 text-green-700" : "bg-red-50 border-red-500 text-red-700"}`}>{t.status}</span>
            </div>
            <div className="col-span-1 font-mono text-sm">{t.bots_count}</div>
            <div className="col-span-2 text-xs text-slate-500 font-mono">{new Date(t.created_at).toLocaleDateString("pt-BR")}</div>
            <div className="col-span-1 flex gap-1 justify-end">
              <button onClick={() => impersonate(t)} className="p-1.5 hover:bg-blue-100 text-blue-600" title="Entrar na empresa" data-testid={`impersonate-${t.id}`}><SignIn size={16} weight="bold" /></button>
              <button onClick={() => toggle(t)} className="p-1.5 hover:bg-slate-200" title={t.status === "active" ? "Suspender" : "Reativar"}>
                {t.status === "active" ? <PauseCircle size={16} weight="bold" /> : <PlayCircle size={16} weight="bold" />}
              </button>
              <button onClick={() => remove(t.id)} className="p-1.5 hover:bg-red-100 text-red-600" title="Excluir"><Trash size={16} weight="bold" /></button>
            </div>
          </div>
        ))}
      </div>
      <Toaster position="bottom-right" />
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
