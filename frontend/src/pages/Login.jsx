import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import {
  ChatCircleDots, ArrowRight, Headset, Sparkle, Robot,
  UsersThree, CalendarCheck, Megaphone,
} from "@phosphor-icons/react";
import BotaoTema from "@/components/BotaoTema";

const RECURSOS = [
  { icone: Headset, titulo: "Central de Atendimento", linha: "Fila, times e histórico de cada conversa" },
  { icone: Sparkle, titulo: "Agentes de IA", linha: "Respondem sozinhos e chamam gente na hora certa" },
  { icone: Robot, titulo: "Fluxos automáticos", linha: "Editor visual, menus e integrações" },
  { icone: UsersThree, titulo: "CRM e funil", linha: "Ficha do contato, negócios e próximo passo" },
  { icone: CalendarCheck, titulo: "Agenda", linha: "Horário marcado pelo WhatsApp, com lembrete" },
  { icone: Megaphone, titulo: "Campanhas", linha: "Disparo por modelo aprovado, com métrica" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      const u = await login(email, password);
      if (u.role === "super_admin") nav("/admin");
      else if (u.role === "agent") nav("/app/inbox");
      else nav("/app");
    } catch (ex) {
      setErr(formatApiErrorDetail(ex.response?.data?.detail) || ex.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2">
      {/* Left brand panel */}
      <div className="hidden lg:flex flex-col justify-between p-12 border-r border-line bg-surface">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-brand text-brand-fg rounded-2xl flex items-center justify-center">
            <ChatCircleDots size={26} weight="bold" />
          </div>
          <div className="font-heading font-black text-2xl tracking-tighter">ZappZen</div>
        </div>

        <div>
          <h1 className="font-heading text-4xl xl:text-5xl font-black tracking-tighter leading-[0.95] mb-5">
            Todo o WhatsApp da sua<br/>empresa em <span className="text-info">um só painel.</span>
          </h1>
          <p className="text-ink-2 text-base leading-relaxed max-w-md mb-8">
            Atendimento em equipe, agentes de IA, CRM com funil, agenda e campanhas. Várias empresas no mesmo lugar.
          </p>

          {/* O que a tela mostra e o que o produto faz, nao uma funcionalidade
              dele. Ate 2026-09-23 o painel vendia so o editor de fluxos
              ("canvas visual", "10 tipos de no"), que hoje e um item entre
              seis: quem chega procurando atendimento, CRM ou agenda lia uma
              pagina sobre outra coisa. Os itens seguem os grupos da barra
              lateral, entao a promessa da tela publica e o menu de dentro
              dizem a mesma coisa. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 max-w-lg">
            {RECURSOS.map(({ icone: Icone, titulo, linha }) => (
              <div key={titulo} className="flex gap-2.5">
                <Icone size={17} weight="bold" className="text-ink-3 shrink-0 mt-0.5" />
                <div>
                  <div className="text-sm font-bold text-ink leading-tight">{titulo}</div>
                  <div className="text-xs text-ink-3 leading-snug mt-0.5">{linha}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="font-mono text-[11px] text-ink-3 tracking-wide">
          Multiempresa · Em português
        </div>
      </div>

      {/* Right form */}
      <div className="relative flex items-center justify-center p-6 lg:p-12 bg-canvas">
        <div className="absolute top-5 right-5">
          <BotaoTema />
        </div>
        <div className="w-full max-w-md">
          <div className="mb-8">
            <div className="text-xs font-bold tracking-[0.2em] uppercase text-ink-3 mb-2">Bem-vindo</div>
            <h2 className="font-heading text-3xl font-black tracking-tighter">Entre na sua conta</h2>
            <p className="text-sm text-ink-2 mt-2">Toda a equipe entra por aqui.</p>
          </div>

          <form onSubmit={submit} className="space-y-4" data-testid="login-form">
            <div>
              <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Email</label>
              <input
                data-testid="login-email"
                type="email" required autoFocus
                className="zz-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="voce@empresa.com"
              />
            </div>
            <div>
              <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Senha</label>
              <input
                data-testid="login-password"
                type="password" required
                className="zz-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>

            {err && (
              <div data-testid="login-error" className="text-sm text-danger bg-danger-soft border border-danger p-2.5 rounded-lg">
                {err}
              </div>
            )}

            <button
              data-testid="login-submit"
              type="submit" disabled={loading}
              className="zz-btn w-full justify-center"
            >
              {loading ? "Entrando..." : "Entrar"} <ArrowRight size={16} weight="bold" />
            </button>
          </form>

          {/* Nada de credencial de exemplo aqui. Esta é a única tela pública do
              produto: o que aparece nela está na internet, indexável, e ia no
              bundle de produção. O e-mail do super admin é real e continua
              sendo — publicá-lo entrega metade do login de quem pode entrar em
              qualquer empresa, e deixa o resto por conta da força bruta. Havia
              uma linha igual com o usuário comum, tirada em 222679c. */}

          {/* Âncora comum, não Link do React Router: as páginas legais são
              arquivos estáticos servidos pelo Caddy, fora do SPA. Um Link
              tentaria resolvê-las como rota e cairia no fallback do index.html.

              Ficam aqui porque é a única tela pública do produto, e a revisão
              da Meta espera alcançar a política de privacidade a partir dela. */}
          <div className="mt-4 text-xs text-ink-3 flex gap-4">
            <a href="/privacidade.html" className="hover:text-ink">Privacidade</a>
            <a href="/termos.html" className="hover:text-ink">Termos de Uso</a>
          </div>
        </div>
      </div>
    </div>
  );
}
