import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useUnreadNotifier } from "@/hooks/useUnreadNotifier";
import { useAtividadesAtrasadas } from "@/hooks/useAtividadesAtrasadas";
import BotaoTema from "@/components/BotaoTema";
import LogoMarca from "@/components/LogoMarca";
import { t } from "@/lib/textos";
import {
  House, Robot, WhatsappLogo, UsersThree, Kanban, Gear,
  Buildings, ChartLine, SignOut, Users, StackSimple, Headset,
  ArrowUUpLeft, Sparkle, CreditCard, Megaphone, Funnel, CheckSquareOffset, ChartBar,
  CalendarCheck, Phone, ClipboardText, Car, LinkSimple, Globe, CaretRight,
} from "@phosphor-icons/react";

// A barra lateral e uma lista de grupos, nao uma lista de itens: com quase 20
// telas em sequencia, achar uma tela seria ler a lista inteira. Os grupos
// seguem o dia de uma revenda: atender, o patio (o estoque), vender, captar
// lead, automatizar e analisar. O grupo sem titulo existe para o Painel, que
// nao pertence a nenhum assunto.
//
// `label` e `titulo` sao a chave de `lib/textos.js`: a tela mostra `t(label)`,
// e o `data-testid` continua saindo da chave, para nao mudar com o vocabulario.
//
// `emBreve` marca a tela que ainda nao existe: aparece no menu para mostrar o
// caminho do produto, mas nao e link.
const adminNav = [
  {
    itens: [
      { to: "/admin", icon: ChartLine, label: "Visão geral", end: true },
      { to: "/admin/tenants", icon: Buildings, label: "Empresas" },
      { to: "/admin/plans", icon: CreditCard, label: "Planos" },
    ],
  },
];

// Configuracao fica recolhida: o dia a dia nao passa por ali, e aberta ela
// empurraria o resto do menu para baixo da dobra. Abre sozinha quando a tela
// atual e uma das dela.
const CONFIGURACAO = {
  titulo: "Configuração",
  recolhivel: true,
  icon: Gear,
  itens: [
    { to: "/app/whatsapp", icon: WhatsappLogo, label: "WhatsApp" },
    { to: "/app/telefone", icon: Phone, label: "Telefone" },
    { to: "/app/departments", icon: StackSimple, label: "Departamentos" },
    { to: "/app/users", icon: Users, label: "Usuários" },
    { to: "/app/settings", icon: Gear, label: "Ajustes" },
  ],
};

function tenantNav(role) {
  const atendimento = {
    titulo: "Atendimento",
    itens: [
      { to: "/app/inbox", icon: Headset, label: "Atendimento" },
      { to: "/app/atendimento", icon: Kanban, label: "Conversas" },
      // Fora do bloco de admin de proposito: quem atende o telefone marca,
      // remarca e cancela o dia inteiro. So a configuracao (servicos, grade,
      // feriados) e restrita, e isso e decidido dentro da propria tela.
      { to: "/app/agenda", icon: CalendarCheck, label: "Agenda" },
    ],
  };

  // Atendente ve um grupo so, e titulo de grupo unico e ruido: fica sem titulo.
  if (role !== "tenant_admin") return [{ itens: atendimento.itens }];

  return [
    { itens: [{ to: "/app", icon: House, label: "Painel", end: true }] },
    atendimento,
    {
      titulo: "Pátio",
      itens: [
        { to: "/app/estoque", icon: Car, label: "Estoque", emBreve: true },
        { to: "/app/catalogo", icon: LinkSimple, label: "Catálogo", emBreve: true },
      ],
    },
    {
      titulo: "Vendas",
      itens: [
        { to: "/app/funil", icon: Funnel, label: "Funil" },
        { to: "/app/contacts", icon: UsersThree, label: "Contatos" },
        { to: "/app/atividades", icon: CheckSquareOffset, label: "Atividades" },
      ],
    },
    {
      // De onde vem o lead.
      titulo: "Captação",
      itens: [
        { to: "/app/campanhas", icon: Megaphone, label: "Campanhas" },
        { to: "/app/formularios", icon: ClipboardText, label: "Formulários" },
        { to: "/app/portais", icon: Globe, label: "Portais", emBreve: true },
      ],
    },
    {
      titulo: "Automação",
      itens: [
        { to: "/app/bots", icon: Robot, label: "Robôs" },
        { to: "/app/ai-agents", icon: Sparkle, label: "Agentes de IA" },
      ],
    },
    {
      titulo: "Análise",
      itens: [{ to: "/app/relatorios", icon: ChartBar, label: "Relatórios" }],
    },
    CONFIGURACAO,
  ];
}

const testId = (texto) => texto.toLowerCase().replace(/\s/g, "-");

const iniciais = (nome = "") =>
  nome.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase() || "?";

function ItemMenu({ item, atrasadas, aguardando }) {
  const Icone = item.icon;
  if (item.emBreve) {
    return (
      <div className="zz-nav-item em-breve" aria-disabled="true" data-testid={`nav-${testId(item.label)}`}
        title="Em construção">
        <Icone size={18} />
        <span>{t(item.label)}</span>
        <span className="zz-nav-selo">Em breve</span>
      </div>
    );
  }
  return (
    <NavLink
      to={item.to}
      end={item.end}
      data-testid={`nav-${testId(item.label)}`}
      className={({ isActive }) => `zz-nav-item ${isActive ? "active" : ""}`}
    >
      <Icone size={18} />
      <span className="truncate">{t(item.label)}</span>
      {item.to === "/app/atividades" && atrasadas > 0 && (
        <span
          className="zz-queue-badge ml-auto"
          data-testid="nav-atividades-badge"
          title={`${atrasadas} ${t("atividade")}(s) atrasada(s)`}
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
  );
}

function GrupoRecolhivel({ grupo, children }) {
  const { pathname } = useLocation();
  const contemAtual = grupo.itens.some((i) => pathname === i.to || pathname.startsWith(`${i.to}/`));
  const [aberto, setAberto] = useState(contemAtual);
  useEffect(() => { if (contemAtual) setAberto(true); }, [contemAtual]);
  const Icone = grupo.icon;
  return (
    <div>
      <div className="zz-nav-sep" />
      <button
        type="button"
        className="zz-nav-item w-[calc(100%-1.5rem)] text-left"
        aria-expanded={aberto}
        onClick={() => setAberto((a) => !a)}
        data-testid={`nav-grupo-${testId(grupo.titulo)}`}
      >
        <Icone size={18} />
        <span>{t(grupo.titulo)}</span>
        <CaretRight size={12} weight="bold" className={`zz-nav-seta ${aberto ? "aberta" : ""}`} />
      </button>
      {aberto && <div className="pl-3">{children}</div>}
    </div>
  );
}

export default function AppShell({ variant = "tenant" }) {
  const { user, logout, impersonatedFrom, exitImpersonation, marca } = useAuth();
  const navigate = useNavigate();
  const nav = variant === "admin" ? adminNav : tenantNav(user?.role);
  const { aguardando } = useUnreadNotifier(variant === "tenant");
  const atrasadas = useAtividadesAtrasadas(variant === "tenant" && user?.role === "tenant_admin");
  const papel = variant === "admin" ? "Super Admin" : (user?.role === "agent" ? "Atendente" : "Admin");

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const handleExit = async () => {
    await exitImpersonation();
    navigate("/admin/tenants");
  };

  return (
    <div className="h-dvh overflow-hidden flex flex-col bg-canvas">
      {impersonatedFrom === "super_admin" && variant === "tenant" && (
        <div className="w-full bg-warning-solid border-b border-line px-6 py-2 flex items-center justify-between text-warning-fg" data-testid="impersonation-bar">
          <div className="text-sm font-bold tracking-wide">
            ⚠ MODO SUPORTE — Você está navegando como Admin desta {t("empresa")}
          </div>
          <button data-testid="exit-impersonation" onClick={handleExit} className="zz-btn zz-btn-secondary text-xs">
            <ArrowUUpLeft size={14} weight="bold" /> Sair do modo suporte
          </button>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        <aside className="zz-sidebar w-[248px] shrink-0 flex flex-col" data-testid="sidebar">
          <div className="px-6 pt-7 pb-4">
            <LogoMarca marca={marca} legenda={papel} />
          </div>

          <nav className="flex-1 pb-4 overflow-y-auto">
            {nav.map((grupo, i) => {
              const itens = grupo.itens.map((item) => (
                <ItemMenu key={item.to} item={item} atrasadas={atrasadas} aguardando={aguardando} />
              ));
              if (grupo.recolhivel) {
                return <GrupoRecolhivel key={grupo.titulo} grupo={grupo}>{itens}</GrupoRecolhivel>;
              }
              return (
                <div key={grupo.titulo || `grupo-${i}`}>
                  {grupo.titulo && (
                    <div className="zz-nav-grupo" data-testid={`nav-grupo-${testId(grupo.titulo)}`}>
                      {t(grupo.titulo)}
                    </div>
                  )}
                  {itens}
                </div>
              );
            })}
          </nav>

          <div className="zz-nav-rodape px-4 py-4">
            <div className="flex items-center gap-3">
              <div className="zz-nav-avatar" aria-hidden>{iniciais(user?.name || user?.email)}</div>
              <div className="min-w-0 flex-1">
                <div className="text-[0.8rem] font-semibold truncate" style={{ color: "var(--nav-fg-forte)" }}>
                  {user?.name || user?.email}
                </div>
                <div className="text-[0.7rem] truncate" title={user?.email}>{user?.email}</div>
              </div>
            </div>
            <div className="flex items-center gap-2 mt-3">
              <BotaoTema />
              <button
                type="button"
                data-testid="logout-btn"
                onClick={handleLogout}
                className="zz-btn-icon flex-1 !w-auto !rounded-[10px] gap-2 text-[0.8rem] font-medium"
              >
                <SignOut size={15} /> Sair
              </button>
            </div>
          </div>
        </aside>

        <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
