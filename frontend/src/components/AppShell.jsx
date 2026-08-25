import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useUnreadNotifier } from "@/hooks/useUnreadNotifier";
import { useAtividadesAtrasadas } from "@/hooks/useAtividadesAtrasadas";
import BotaoTema from "@/components/BotaoTema";
import {
  ChatCircleDots, House, Robot, WhatsappLogo, UsersThree, Kanban, Gear,
  Buildings, ChartLine, SignOut, Users, StackSimple, Headset,
  ArrowUUpLeft, Sparkle, CreditCard, Megaphone, Funnel, CheckSquareOffset, ChartBar,
} from "@phosphor-icons/react";

const adminNav = [
  { to: "/admin", icon: ChartLine, label: "Métricas Globais", end: true },
  { to: "/admin/tenants", icon: Buildings, label: "Empresas" },
  { to: "/admin/plans", icon: CreditCard, label: "Planos" },
];

function tenantNav(role) {
  const base = [
    { to: "/app/inbox", icon: Headset, label: "Atendimento" },
    { to: "/app/atendimento", icon: Kanban, label: "Conversas" },
  ];
  if (role === "tenant_admin") {
    base.unshift({ to: "/app", icon: House, label: "Painel", end: true });
    base.push(
      { to: "/app/bots", icon: Robot, label: "Robôs" },
      { to: "/app/ai-agents", icon: Sparkle, label: "Agentes de IA" },
      { to: "/app/whatsapp", icon: WhatsappLogo, label: "WhatsApp" },
      { to: "/app/departments", icon: StackSimple, label: "Departamentos" },
      { to: "/app/users", icon: Users, label: "Usuários" },
      { to: "/app/contacts", icon: UsersThree, label: "Contatos" },
      { to: "/app/campanhas", icon: Megaphone, label: "Campanhas" },
      { to: "/app/funil", icon: Funnel, label: "Funil" },
      { to: "/app/atividades", icon: CheckSquareOffset, label: "Atividades" },
      { to: "/app/relatorios", icon: ChartBar, label: "Relatórios" },
      { to: "/app/settings", icon: Gear, label: "Configurações" },
    );
  }
  return base;
}

export default function AppShell({ variant = "tenant" }) {
  const { user, logout, impersonatedFrom, exitImpersonation } = useAuth();
  const navigate = useNavigate();
  const nav = variant === "admin" ? adminNav : tenantNav(user?.role);
  const { aguardando } = useUnreadNotifier(variant === "tenant");
  const atrasadas = useAtividadesAtrasadas(variant === "tenant" && user?.role === "tenant_admin");

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const handleExit = async () => {
    await exitImpersonation();
    navigate("/admin/tenants");
  };

  return (
    <div className="min-h-screen flex flex-col bg-canvas">
      {impersonatedFrom === "super_admin" && variant === "tenant" && (
        <div className="w-full bg-warning-solid border-b border-line px-6 py-2 flex items-center justify-between text-warning-fg" data-testid="impersonation-bar">
          <div className="text-sm font-bold tracking-wide">
            ⚠ MODO SUPORTE — Você está navegando como Admin desta empresa
          </div>
          <button data-testid="exit-impersonation" onClick={handleExit} className="zz-btn zz-btn-secondary text-xs">
            <ArrowUUpLeft size={14} weight="bold" /> Sair do modo suporte
          </button>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        <aside className="w-60 border-r border-line bg-surface flex flex-col" data-testid="sidebar">
          <div className="px-5 py-6 border-b border-line">
            <div className="flex items-center gap-2">
              <div className="w-9 h-9 bg-brand text-brand-fg rounded-xl flex items-center justify-center shrink-0">
                <ChatCircleDots size={20} weight="bold" />
              </div>
              <div>
                <div className="font-heading font-black text-lg leading-none tracking-tighter">ZappZen</div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-ink-3 font-bold mt-0.5">
                  {variant === "admin" ? "Super Admin" : (user?.role === "agent" ? "Atendente" : "Admin")}
                </div>
              </div>
            </div>
          </div>

          <nav className="flex-1 py-3 overflow-y-auto">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                data-testid={`nav-${item.label.toLowerCase().replace(/\s/g, "-")}`}
                className={({ isActive }) => `zz-nav-item ${isActive ? "active" : ""}`}
              >
                <item.icon size={18} weight="bold" />
                <span>{item.label}</span>
                {item.to === "/app/atividades" && atrasadas > 0 && (
                  <span
                    className="zz-queue-badge ml-auto"
                    data-testid="nav-atividades-badge"
                    title={`${atrasadas} atividade(s) atrasada(s)`}
                  >
                    {atrasadas > 99 ? "99+" : atrasadas}
                  </span>
                )}
                {item.to === "/app/inbox" && aguardando > 0 && (
                  <span
                    className="zz-queue-badge zz-alert-pulse ml-auto"
                    data-testid="nav-queue-badge"
                    title={`${aguardando} conversa(s) aguardando atendimento`}
                  >
                    {aguardando > 99 ? "99+" : aguardando}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          <div className="border-t border-line p-3">
            <div className="text-xs text-ink-3 mb-2 truncate">{user?.email}</div>
            <div className="flex items-center gap-2">
              <button data-testid="logout-btn" onClick={handleLogout} className="zz-btn zz-btn-secondary flex-1 justify-center">
                <SignOut size={16} weight="bold" /> Sair
              </button>
              <BotaoTema />
            </div>
          </div>
        </aside>

        <main className="flex-1 overflow-x-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
