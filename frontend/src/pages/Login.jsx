import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { ChatCircleDots, ArrowRight } from "@phosphor-icons/react";
import BotaoTema from "@/components/BotaoTema";

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
          <h1 className="font-heading text-5xl font-black tracking-tighter leading-[0.95] mb-6">
            Construa bots de WhatsApp<br/>com um <span className="text-info">canvas visual.</span>
          </h1>
          <p className="text-ink-2 text-base leading-relaxed max-w-md">
            Várias empresas num só painel, blocos arrastáveis, integrações via webhook e atendimento humano quando o robô não conseguir resolver.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-3 font-mono text-xs text-ink-3">
          <div className="border border-line p-4 rounded-lg"><div className="text-2xl font-black text-ink">10</div>tipos de nó</div>
          <div className="border border-line p-4 rounded-lg"><div className="text-2xl font-black text-ink">∞</div>bots por empresa</div>
          <div className="border border-line p-4 rounded-lg"><div className="text-2xl font-black text-ink">1</div>painel de tudo</div>
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
            <p className="text-sm text-ink-2 mt-2">Super admins e admins de empresa fazem login aqui.</p>
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
