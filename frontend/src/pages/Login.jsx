import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { ArrowRight, Eye, EyeSlash } from "@phosphor-icons/react";
import BotaoTema from "@/components/BotaoTema";
import LogoMarca from "@/components/LogoMarca";
import CarroShowroom from "@/components/login/CarroShowroom";

// A entrada é o showroom: o carro à esquerda, o formulário à direita, e quase
// nenhum texto. O carro reage ao formulário (farol, rodas, arranque) e é o
// que dá vida à tela; quem só quer entrar não precisa olhar para ele.
export default function LoginPage() {
  const { login, marca } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [verSenha, setVerSenha] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const [foco, setFoco] = useState(false);
  const [piscando, setPiscando] = useState(false);
  const [giro, setGiro] = useState(0);
  const [tranco, setTranco] = useState(false);
  const timers = useRef([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const depois = (fn, ms) => timers.current.push(setTimeout(fn, ms));

  // Cada tecla gira as rodas um pouco: o carro "anda" junto com quem digita.
  const digitou = (setter) => (e) => {
    setter(e.target.value);
    setGiro((g) => g + 40);
  };

  const piscar = () => {
    setPiscando(true);
    depois(() => setPiscando(false), 180);
    depois(() => setPiscando(true), 320);
    depois(() => setPiscando(false), 500);
  };

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
      setTranco(true);
      depois(() => setTranco(false), 500);
    } finally { setLoading(false); }
  };

  const farolAceso = (foco || loading) !== piscando;

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-[1.35fr_1fr] bg-canvas">
      {/* Showroom */}
      <div className="zz-sidebar relative flex flex-col justify-between min-h-[300px] lg:min-h-screen p-8 lg:p-12 overflow-hidden">
        <div className="relative z-10">
          <LogoMarca marca={marca} grande />
        </div>

        <div className="absolute inset-0">
          <CarroShowroom farol={farolAceso} giro={giro} andando={loading} erro={tranco} onPiscar={piscar} />
        </div>

        <div className="relative z-10 hidden lg:block zz-nav-legenda">
          Seu pátio, sem ponto morto.
        </div>
      </div>

      {/* Entrada */}
      <div className="relative flex items-center justify-center p-6 py-10 lg:p-12">
        <div className="absolute top-5 right-5">
          <BotaoTema />
        </div>
        <div className="w-full max-w-sm zz-entrada">
          <h1 className="font-heading text-[2rem] font-semibold tracking-tight leading-tight">Entrar</h1>
          <p className="text-sm text-ink-3 mt-1.5 mb-8">Bem-vindo de volta.</p>

          <form onSubmit={submit} className="space-y-4" data-testid="login-form"
            onFocus={() => setFoco(true)}
            /* Passar do e-mail para a senha também é "blur": sem conferir para
               onde o foco foi, o farol piscaria a cada troca de campo. */
            onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setFoco(false); }}>
            <div>
              <label htmlFor="login-email" className="text-xs font-medium text-ink-2 block mb-1.5">E-mail</label>
              <input
                id="login-email"
                data-testid="login-email"
                type="email" required autoFocus autoComplete="username"
                className="zz-input h-12"
                value={email}
                onChange={digitou(setEmail)}
                placeholder="voce@suarevenda.com.br"
              />
            </div>
            <div>
              <label htmlFor="login-password" className="text-xs font-medium text-ink-2 block mb-1.5">Senha</label>
              <div className="relative">
                <input
                  id="login-password"
                  data-testid="login-password"
                  type={verSenha ? "text" : "password"} required autoComplete="current-password"
                  className="zz-input h-12 pr-11"
                  value={password}
                  onChange={digitou(setPassword)}
                  placeholder="••••••••"
                />
                <button type="button" onClick={() => setVerSenha((v) => !v)}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 w-9 h-9 grid place-items-center rounded-lg text-ink-3 hover:text-ink hover:bg-surface-3 transition-colors"
                  aria-label={verSenha ? "Esconder senha" : "Mostrar senha"} data-testid="login-ver-senha">
                  {verSenha ? <EyeSlash size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </div>

            {err && (
              <div data-testid="login-error" role="alert"
                className="text-sm text-danger bg-danger-soft border border-danger/30 px-3 py-2.5 rounded-xl">
                {err}
              </div>
            )}

            <button
              data-testid="login-submit"
              type="submit" disabled={loading}
              className="zz-btn w-full justify-center h-12 mt-2 group"
            >
              {loading ? "Entrando…" : "Entrar"}
              <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </button>
          </form>

          {/* Nada de credencial de exemplo aqui. Esta é a única tela pública do
              produto: o que aparece nela está na internet, indexável, e ia no
              bundle de produção.

              Âncora comum, não Link do React Router: as páginas legais são
              arquivos estáticos servidos pelo Caddy, fora do SPA. Ficam aqui
              porque é a única tela pública do produto, e a revisão da Meta
              espera alcançar a política de privacidade a partir dela. */}
          <div className="mt-10 text-xs text-ink-3 flex gap-5">
            <a href="/privacidade.html" className="hover:text-ink transition-colors">Privacidade</a>
            <a href="/termos.html" className="hover:text-ink transition-colors">Termos de Uso</a>
          </div>
        </div>
      </div>
    </div>
  );
}
