import { useEffect, useState } from "react";
import api from "@/lib/api";
import { ChartLine, Buildings, Users, Robot, ChatCircleDots } from "@phosphor-icons/react";

const items = [
  { key: "tenants_total", label: "Empresas cadastradas", icon: Buildings, color: "#2563EB" },
  { key: "tenants_active", label: "Empresas ativas", icon: Buildings, color: "#10B981" },
  { key: "users_total", label: "Admins de empresa", icon: Users, color: "#F97316" },
  { key: "bots_total", label: "Robôs no sistema", icon: Robot, color: "#0F172A" },
  { key: "conversations_total", label: "Conversas totais", icon: ChatCircleDots, color: "#EC4899" },
  { key: "messages_total", label: "Mensagens totais", icon: ChatCircleDots, color: "#475569" },
];

export default function SuperAdminDashboard() {
  const [m, setM] = useState(null);
  useEffect(() => { api.get("/admin/metrics").then((r) => setM(r.data)); }, []);

  return (
    <div className="p-8" data-testid="admin-dashboard">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-ink-3 mb-2">Painel Super Admin</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Métricas Globais</h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 border border-line bg-surface rounded-lg">
        {items.map((it) => {
          const Icon = it.icon;
          return (
            <div key={it.key} className="border-r border-b border-line p-6 last:border-r-0" data-testid={`admin-metric-${it.key}`}>
              <div className="flex items-center justify-between mb-4">
                <div className="text-xs font-bold uppercase tracking-wider text-ink-3">{it.label}</div>
                <div className="w-8 h-8 flex items-center justify-center border border-line-strong text-white rounded-lg" style={{ background: it.color }}>
                  <Icon size={16} weight="bold" />
                </div>
              </div>
              <div className="font-heading text-5xl font-black tracking-tighter">{m ? m[it.key] : "—"}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
