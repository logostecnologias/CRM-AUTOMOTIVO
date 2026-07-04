import { useAuth } from "@/context/AuthContext";

export default function SettingsPage() {
  const { user } = useAuth();
  return (
    <div className="p-8 max-w-3xl" data-testid="settings-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Conta</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Configurações</h1>
      </div>

      <div className="border border-slate-200 bg-white p-6 mb-4">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Perfil</div>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between border-b border-slate-100 pb-2"><span className="text-slate-500">Nome</span><span className="font-semibold">{user?.name}</span></div>
          <div className="flex justify-between border-b border-slate-100 pb-2"><span className="text-slate-500">Email</span><span className="font-mono">{user?.email}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Papel</span><span className="font-mono">{user?.role}</span></div>
        </div>
      </div>

      <div className="border border-slate-200 bg-white p-6">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Empresa</div>
        <div className="text-sm text-slate-600">Tenant ID: <span className="font-mono text-slate-800">{user?.tenant_id}</span></div>
      </div>
    </div>
  );
}
