import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, Trash, PencilSimple } from "@phosphor-icons/react";
import { toast, Toaster } from "sonner";

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [conn, setConn] = useState(null);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "agent", connection_ids: [] });

  const load = async () => {
    const [u, c] = await Promise.all([api.get("/users"), api.get("/whatsapp/status")]);
    setUsers(u.data);
    setConn(c.data);
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm({ name: "", email: "", password: "", role: "agent", connection_ids: [] }); setEditing({}); };
  const openEdit = (u) => {
    setForm({ name: u.name, email: u.email, password: "", role: u.role, connection_ids: u.connection_ids || [] });
    setEditing(u);
  };

  const toggleConn = (cid) => {
    setForm((f) => ({
      ...f,
      connection_ids: f.connection_ids.includes(cid)
        ? f.connection_ids.filter((x) => x !== cid)
        : [...f.connection_ids, cid],
    }));
  };

  const save = async (e) => {
    e.preventDefault();
    try {
      if (editing?.id) {
        const payload = { name: form.name, connection_ids: form.connection_ids };
        if (form.password) payload.password = form.password;
        await api.patch(`/users/${editing.id}`, payload);
      } else {
        await api.post("/users", form);
      }
      setEditing(null);
      toast.success("Usuário salvo");
      load();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao salvar");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Excluir usuário?")) return;
    await api.delete(`/users/${id}`);
    load();
  };

  const connections = conn ? [conn] : []; // only 1 for now — future: list

  return (
    <div className="p-8 max-w-5xl" data-testid="users-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Equipe</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Usuários</h1>
          <p className="text-slate-600 mt-2 text-sm">Cadastre atendentes e defina quais conexões cada um pode ver.</p>
        </div>
        <button data-testid="new-user-btn" onClick={openNew} className="zz-btn"><Plus size={14} weight="bold" /> Novo Usuário</button>
      </div>

      {editing && (
        <form onSubmit={save} className="mb-6 border border-slate-900 bg-white p-4 grid grid-cols-2 gap-4 zz-panel-hard">
          <Field label="Nome"><input required className="zz-input" data-testid="user-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Email"><input required type="email" disabled={!!editing?.id} className="zz-input" data-testid="user-email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label={editing?.id ? "Nova senha (opcional)" : "Senha"}>
            <input required={!editing?.id} className="zz-input" data-testid="user-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Papel">
            <select className="zz-input" value={form.role} disabled={!!editing?.id} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="agent">Atendente</option>
              <option value="tenant_admin">Admin</option>
            </select>
          </Field>
          <div className="col-span-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Conexões liberadas</label>
            {connections.length === 0 ? (
              <div className="text-xs text-slate-500 italic">Nenhuma conexão de WhatsApp criada ainda.</div>
            ) : (
              <div className="space-y-1">
                {connections.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" checked={form.connection_ids.includes(c.id)} onChange={() => toggleConn(c.id)} data-testid={`conn-check-${c.id}`} />
                    {c.evolution_instance_name || c.id.slice(0, 8)} · <span className="font-mono text-slate-500">{c.status}</span>
                  </label>
                ))}
              </div>
            )}
            {form.role === "tenant_admin" && (
              <div className="text-xs text-slate-500 mt-1">Admins ignoram esta restrição (acesso total).</div>
            )}
          </div>
          <div className="col-span-2 flex gap-2 justify-end">
            <button type="button" onClick={() => setEditing(null)} className="zz-btn zz-btn-secondary">Cancelar</button>
            <button type="submit" className="zz-btn" data-testid="user-submit">Salvar</button>
          </div>
        </form>
      )}

      <div className="border border-slate-200 bg-white">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          <div className="col-span-4">Nome</div>
          <div className="col-span-3">Email</div>
          <div className="col-span-2">Papel</div>
          <div className="col-span-2">Conexões</div>
          <div className="col-span-1 text-right">Ações</div>
        </div>
        {users.length === 0 && <div className="p-6 text-sm text-slate-500 text-center">Nenhum usuário.</div>}
        {users.map((u) => (
          <div key={u.id} className="grid grid-cols-12 px-4 py-3 border-b border-slate-100 items-center hover:bg-slate-50" data-testid={`user-row-${u.id}`}>
            <div className="col-span-4 font-semibold">{u.name}</div>
            <div className="col-span-3 font-mono text-xs text-slate-700">{u.email}</div>
            <div className="col-span-2"><span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 border bg-slate-50 border-slate-300 text-slate-700">{u.role}</span></div>
            <div className="col-span-2 font-mono text-xs">{u.role === "tenant_admin" ? "todas" : (u.connection_ids?.length || 0)}</div>
            <div className="col-span-1 flex gap-1 justify-end">
              <button onClick={() => openEdit(u)} className="p-1.5 hover:bg-slate-200"><PencilSimple size={14} weight="bold" /></button>
              <button onClick={() => remove(u.id)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} weight="bold" /></button>
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
