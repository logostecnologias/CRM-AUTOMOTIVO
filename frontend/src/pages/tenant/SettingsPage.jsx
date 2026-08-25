import { useAuth } from "@/context/AuthContext";

export default function SettingsPage() {
  const { user } = useAuth();
  return (
    <div className="zz-page-form" data-testid="settings-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-ink-3 mb-2">Conta</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Configurações</h1>
      </div>

      <div className="border border-line bg-surface p-6 mb-4 rounded-lg">
        <div className="text-xs font-bold uppercase tracking-wider text-ink-3 mb-3">Perfil</div>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between border-b border-line pb-2"><span className="text-ink-3">Nome</span><span className="font-semibold">{user?.name}</span></div>
          <div className="flex justify-between border-b border-line pb-2"><span className="text-ink-3">Email</span><span className="font-mono">{user?.email}</span></div>
          <div className="flex justify-between"><span className="text-ink-3">Papel</span><span className="font-mono">{user?.role}</span></div>
        </div>
      </div>

      <div className="border border-line bg-surface p-6 rounded-lg">
        <div className="text-xs font-bold uppercase tracking-wider text-ink-3 mb-3">Empresa</div>
        <div className="text-sm text-ink-2">Tenant ID: <span className="font-mono text-ink">{user?.tenant_id}</span></div>
      </div>
    </div>
  );
}
