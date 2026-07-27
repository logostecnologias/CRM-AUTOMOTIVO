import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { ChatCircleDots, ArrowRight } from "@phosphor-icons/react";

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
      <div className="hidden lg:flex flex-col justify-between p-12 border-r border-slate-900 bg-white">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 bg-slate-900 text-white flex items-center justify-center">
            <ChatCircleDots size={26} weight="bold" />
          </div>
          <div className="font-heading font-black text-2xl tracking-tighter">ZappZen</div>
        </div>

        <div>
          <div className="text-xs font-bold tracking-[0.25em] uppercase text-slate-500 mb-4">Plataforma</div>
          <h1 className="font-heading text-5xl font-black tracking-tighter leading-[0.95] mb-6">
            Construa bots de WhatsApp<br/>com um <span className="text-blue-600">canvas visual.</span>
          </h1>
          <p className="text-slate-600 text-base leading-relaxed max-w-md">
            Multi-tenant, blocos arrastáveis, integrações via webhook e atendimento humano quando o robô não conseguir resolver.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-3 font-mono text-xs text-slate-500">
          <div className="border border-slate-200 p-3"><div className="text-2xl font-black text-slate-900">10</div>tipos de nó</div>
          <div className="border border-slate-200 p-3"><div className="text-2xl font-black text-slate-900">∞</div>bots por empresa</div>
          <div className="border border-slate-200 p-3"><div className="text-2xl font-black text-slate-900">1</div>painel de tudo</div>
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-6 lg:p-12 bg-[#F8F9FA]">
        <div className="w-full max-w-md">
          <div className="mb-8">
            <div className="text-xs font-bold tracking-[0.2em] uppercase text-slate-500 mb-2">Bem-vindo</div>
            <h2 className="font-heading text-3xl font-black tracking-tighter">Entre na sua conta</h2>
            <p className="text-sm text-slate-600 mt-2">Super admins e admins de empresa fazem login aqui.</p>
          </div>

          <form onSubmit={submit} className="space-y-4" data-testid="login-form">
            <div>
              <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Email</label>
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
              <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Senha</label>
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
              <div data-testid="login-error" className="text-sm text-red-600 bg-red-50 border border-red-500 p-2.5">
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

          <div className="mt-8 text-xs text-slate-500 border-t border-slate-200 pt-4 font-mono">
            <div>Super Admin de teste: <span className="text-slate-800">admin@zappzen.com</span> / <span className="text-slate-800">admin@123</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}
