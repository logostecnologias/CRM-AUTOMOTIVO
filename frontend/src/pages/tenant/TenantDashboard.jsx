import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ChatCircleDots, Users, Robot, Tray } from "@phosphor-icons/react";

const items = [
  { key: "active_conversations", label: "Conversas ativas", icon: ChatCircleDots, color: "#10B981" },
  { key: "awaiting_human", label: "Aguardando humano", icon: Tray, color: "#EF4444" },
  { key: "messages_month", label: "Mensagens no mês", icon: ChatCircleDots, color: "#2563EB" },
  { key: "active_bots", label: "Robôs ativos", icon: Robot, color: "#F97316" },
  { key: "total_contacts", label: "Contatos", icon: Users, color: "#0F172A" },
  { key: "total_bots", label: "Total de robôs", icon: Robot, color: "#475569" },
];

export default function TenantDashboard() {
  const { user } = useAuth();
  const [metrics, setMetrics] = useState(null);
  const isAdmin = user?.role === "tenant_admin";
  useEffect(() => {
    if (!isAdmin) return;
    api.get("/dashboard/metrics").then((r) => setMetrics(r.data)).catch(() => {});
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <div className="p-8" data-testid="tenant-dashboard">
        <div className="mb-8">
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Painel</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Olá, {user?.name}.</h1>
          <p className="text-slate-600 mt-2">Suas conversas estão na Central de Atendimento.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8" data-testid="tenant-dashboard">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Painel</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Olá, {user?.name}.</h1>
        <p className="text-slate-600 mt-2">Aqui está um resumo da atividade dos seus robôs.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-0 border border-slate-200 bg-white">
        {items.map((it) => {
          const Icon = it.icon;
          return (
            <div key={it.key} className="border-r border-b border-slate-200 p-6 last:border-r-0" data-testid={`metric-${it.key}`}>
              <div className="flex items-center justify-between mb-4">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-500">{it.label}</div>
                <div className="w-8 h-8 flex items-center justify-center border border-slate-900" style={{ background: it.color, color: it.color === "#FDE047" ? "#0F172A" : "#fff" }}>
                  <Icon size={16} weight="bold" />
                </div>
              </div>
              <div className="font-heading text-5xl font-black tracking-tighter">{metrics ? metrics[it.key] : "—"}</div>
            </div>
          );
        })}
      </div>

      <div className="mt-10 border border-slate-200 bg-white p-6">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Próximos passos</div>
        <ol className="space-y-2 text-sm text-slate-700">
          <li>1. Conecte o WhatsApp da sua empresa (Menu → WhatsApp)</li>
          <li>2. Crie seu primeiro robô e desenhe o fluxo no editor visual</li>
          <li>3. Publique o fluxo e monitore as conversas na Caixa de Entrada</li>
        </ol>
      </div>
    </div>
  );
}
