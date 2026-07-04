import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  ChatCircleDots, House, Robot, WhatsappLogo, UsersThree, Tray, Gear,
  Buildings, ChartLine, SignOut,
} from "@phosphor-icons/react";

const tenantNav = [
  { to: "/app", icon: House, label: "Painel", end: true },
  { to: "/app/bots", icon: Robot, label: "Robôs" },
  { to: "/app/whatsapp", icon: WhatsappLogo, label: "WhatsApp" },
  { to: "/app/contacts", icon: UsersThree, label: "Contatos" },
  { to: "/app/inbox", icon: Tray, label: "Caixa de Entrada" },
  { to: "/app/settings", icon: Gear, label: "Configurações" },
];

const adminNav = [
  { to: "/admin", icon: ChartLine, label: "Métricas Globais", end: true },
  { to: "/admin/tenants", icon: Buildings, label: "Empresas" },
];

export default function AppShell({ variant = "tenant" }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const nav = variant === "admin" ? adminNav : tenantNav;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen flex bg-[#F8F9FA]">
      <aside className="w-60 border-r border-slate-900 bg-white flex flex-col" data-testid="sidebar">
        <div className="px-5 py-5 border-b border-slate-900">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-slate-900 text-white flex items-center justify-center">
              <ChatCircleDots size={20} weight="bold" />
            </div>
            <div>
              <div className="font-heading font-black text-lg leading-none tracking-tighter">ZappZen</div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 font-bold mt-0.5">
                {variant === "admin" ? "Super Admin" : "Painel"}
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 py-3">
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
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-200 p-3">
          <div className="text-xs text-slate-500 mb-1 truncate">{user?.email}</div>
          <button
            data-testid="logout-btn"
            onClick={handleLogout}
            className="zz-btn zz-btn-secondary w-full justify-center"
          >
            <SignOut size={16} weight="bold" /> Sair
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  );
}
