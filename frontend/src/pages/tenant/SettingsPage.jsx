import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Buildings, ChartBar, Lock, User, Warning } from "@phosphor-icons/react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatBRL } from "@/lib/currency";
import { rotuloPapel } from "@/lib/papeis";
import { t } from "@/lib/textos";

const SENHA_MINIMA = 8;

/** Acima daqui a barra muda de cor: o teto deixa de ser informação e vira aviso. */
const ALERTA = 0.8;

function Bloco({ icone: Icone, titulo, hint, children }) {
  return (
    <section className="border border-line bg-surface p-6 mb-4 rounded-lg">
      <div className="flex items-center gap-2 mb-1">
        <Icone size={14} weight="bold" className="text-ink-3" />
        <h2 className="text-xs font-bold uppercase tracking-wider text-ink-3">{titulo}</h2>
      </div>
      {hint && <p className="text-xs text-ink-3 mb-4">{hint}</p>}
      <div className={hint ? "" : "mt-4"}>{children}</div>
    </section>
  );
}

function Campo({ label, children, hint }) {
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
      {hint && <div className="text-[10px] text-ink-3 mt-1">{hint}</div>}
    </div>
  );
}

/**
 * Uma linha de "usado de limite".
 *
 * Limite nulo é ilimitado — e aí não há barra nenhuma. Desenhar uma barra
 * vazia sugeriria um teto que não existe, que é justamente o que esta tela
 * veio corrigir.
 */
function LinhaUso({ linha }) {
  const { usado, limite, label, janela, nota } = linha;
  const ilimitado = limite === null || limite === undefined;
  const pct = ilimitado ? 0 : Math.min(100, Math.round((usado / limite) * 100));
  const estourou = !ilimitado && usado >= limite;
  const perto = !ilimitado && !estourou && usado / limite >= ALERTA;
  const cor = estourou ? "bg-danger" : perto ? "bg-warning" : "bg-brand";

  return (
    <div data-testid={`uso-${linha.chave}`}>
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <span className="text-sm text-ink">
          {label}
          {janela && <span className="text-ink-3 text-xs"> · no {janela}</span>}
        </span>
        <span className="text-xs font-mono text-ink-2 shrink-0">
          {usado.toLocaleString("pt-BR")}{" "}
          <span className="text-ink-3">
            {ilimitado ? "· ilimitado" : `de ${limite.toLocaleString("pt-BR")}`}
          </span>
        </span>
      </div>

      {!ilimitado && (
        <div className="h-2 bg-surface-3 border border-line rounded-full overflow-hidden">
          <div className={`h-full ${cor}`} style={{ width: `${pct}%` }} />
        </div>
      )}

      {(estourou || perto || nota) && (
        <div className={`text-[10px] mt-1 ${
          estourou ? "text-danger font-bold" : perto ? "text-warning" : "text-ink-3"
        }`}>
          {estourou
            ? "Limite atingido — novas criações são recusadas."
            : perto
              ? "Perto do limite do plano."
              : nota}
        </div>
      )}
    </div>
  );
}

function MinhaConta() {
  const { user, refresh, impersonatedFrom } = useAuth();
  const [nome, setNome] = useState(user?.name || "");
  const [salvandoNome, setSalvandoNome] = useState(false);
  const [senha, setSenha] = useState({ atual: "", nova: "", repetir: "" });
  const [trocando, setTrocando] = useState(false);

  useEffect(() => { setNome(user?.name || ""); }, [user?.name]);

  const nomeMudou = nome.trim() && nome.trim() !== (user?.name || "");

  const salvarNome = async (e) => {
    e.preventDefault();
    setSalvandoNome(true);
    try {
      await api.patch("/settings/conta", { name: nome.trim() });
      // O nome vai no prefixo de toda mensagem que este usuário envia, então o
      // resto da interface precisa enxergar o novo valor sem recarregar a página.
      await refresh?.();
      toast.success("Nome atualizado");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Não foi possível salvar o nome");
    } finally {
      setSalvandoNome(false);
    }
  };

  const trocarSenha = async (e) => {
    e.preventDefault();
    if (senha.nova !== senha.repetir) {
      toast.error("A nova senha e a repetição não conferem");
      return;
    }
    setTrocando(true);
    try {
      await api.post("/settings/senha", { senha_atual: senha.atual, nova_senha: senha.nova });
      setSenha({ atual: "", nova: "", repetir: "" });
      toast.success("Senha alterada");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Não foi possível alterar a senha");
    } finally {
      setTrocando(false);
    }
  };

  // No modo suporte a sessão é do super admin com o papel trocado: os campos
  // abaixo mostrariam o email dele como se fosse o admin da empresa, e o
  // backend recusa as duas escritas (`routes/settings.py`).
  if (impersonatedFrom) {
    return (
      <Bloco icone={User} titulo="Minha conta">
        <p className="text-sm text-ink-2" data-testid="conta-modo-suporte">
          Você está em modo suporte, com a sua própria conta ({user?.email}). Os usuários
          desta {t("empresa")}, com o email de acesso de cada um, estão em <strong>Usuários</strong>,
          onde também se define uma senha nova.
        </p>
      </Bloco>
    );
  }

  return (
    <>
      <Bloco icone={User} titulo="Minha conta">
        <form onSubmit={salvarNome} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label="Nome" hint="Aparece no início das mensagens que você envia no atendimento.">
            <input className="zz-input" value={nome} data-testid="conta-nome"
              onChange={(e) => setNome(e.target.value)} />
          </Campo>
          <Campo label="Email" hint="O email de acesso é alterado em Usuários.">
            <input className="zz-input" value={user?.email || ""} disabled />
          </Campo>
          <Campo label="Papel">
            <div className="text-sm text-ink pt-2">{rotuloPapel(user?.role)}</div>
          </Campo>
          <div className="flex items-end justify-end">
            <button type="submit" className="zz-btn" disabled={!nomeMudou || salvandoNome}
              data-testid="conta-salvar">
              {salvandoNome ? "Salvando…" : "Salvar nome"}
            </button>
          </div>
        </form>
      </Bloco>

      <Bloco icone={Lock} titulo="Senha"
        hint="A senha atual é exigida mesmo com você já conectado: a sessão dura muito tempo, e sem ela uma máquina destravada bastaria para tomar a conta.">
        <form onSubmit={trocarSenha} className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Campo label="Senha atual">
            <input type="password" className="zz-input" value={senha.atual} required
              autoComplete="current-password" data-testid="senha-atual"
              onChange={(e) => setSenha({ ...senha, atual: e.target.value })} />
          </Campo>
          <Campo label="Nova senha" hint={`Mínimo de ${SENHA_MINIMA} caracteres.`}>
            <input type="password" className="zz-input" value={senha.nova} required
              minLength={SENHA_MINIMA} autoComplete="new-password" data-testid="senha-nova"
              onChange={(e) => setSenha({ ...senha, nova: e.target.value })} />
          </Campo>
          <Campo label="Repetir nova senha">
            <input type="password" className="zz-input" value={senha.repetir} required
              autoComplete="new-password" data-testid="senha-repetir"
              onChange={(e) => setSenha({ ...senha, repetir: e.target.value })} />
          </Campo>
          <div className="sm:col-span-3 flex justify-end">
            <button type="submit" className="zz-btn" disabled={trocando} data-testid="senha-salvar">
              {trocando ? "Alterando…" : "Alterar senha"}
            </button>
          </div>
        </form>
      </Bloco>
    </>
  );
}

function retencaoLabel(plano) {
  if (!plano) return "padrão do servidor";
  const d = plano.retencao_midia_dias;
  if (d === null || d === undefined) return "padrão do servidor";
  if (d === 0) return "sem expiração";
  return `${d} dias`;
}

function Empresa() {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);

  useEffect(() => {
    api.get("/settings/empresa")
      .then((r) => setDados(r.data))
      .catch((e) => setErro(e.response?.data?.detail || `Não foi possível carregar os dados da ${t("empresa")}`));
  }, []);

  if (erro) {
    return <Bloco icone={Buildings} titulo={t("Empresa")}><div className="text-sm text-danger">{erro}</div></Bloco>;
  }
  if (!dados) {
    return <Bloco icone={Buildings} titulo={t("Empresa")}><div className="text-sm text-ink-3">Carregando…</div></Bloco>;
  }

  const { empresa, plano, uso } = dados;

  return (
    <>
      <Bloco icone={Buildings} titulo={t("Empresa")}>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between border-b border-line pb-2">
            <span className="text-ink-3">Nome</span>
            <span className="font-semibold" data-testid="empresa-nome">{empresa.nome}</span>
          </div>
          <div className="flex justify-between border-b border-line pb-2">
            <span className="text-ink-3">Cliente desde</span>
            <span>{empresa.criada_em ? new Date(empresa.criada_em).toLocaleDateString("pt-BR") : "—"}</span>
          </div>
          <div className="flex justify-between border-b border-line pb-2">
            <span className="text-ink-3">Plano</span>
            <span data-testid="empresa-plano">
              {plano
                ? <>{plano.nome} <span className="text-ink-3">· {formatBRL(plano.preco_mensal)}/mês</span></>
                : <span className="text-ink-3">nenhum plano vinculado</span>}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-ink-3">Retenção de mídia</span>
            <span>{retencaoLabel(plano)}</span>
          </div>
        </div>

        {empresa.status !== "active" && (
          <div className="mt-4 flex items-start gap-2 border border-danger bg-danger-soft text-danger p-3 rounded-lg text-xs">
            <Warning size={14} weight="bold" className="shrink-0 mt-0.5" />
            <span>Esta {t("empresa")} está suspensa. Fale com o suporte para reativar.</span>
          </div>
        )}
      </Bloco>

      <Bloco icone={ChartBar} titulo="Uso do plano"
        hint="O que já foi consumido de cada limite. Ao bater o teto a criação é recusada — este painel existe para você ver isso chegando.">
        <div className="space-y-4">
          {uso.map((l) => <LinhaUso key={l.chave} linha={l} />)}
        </div>
      </Bloco>
    </>
  );
}

export default function SettingsPage() {
  return (
    <div className="zz-page-form" data-testid="settings-page">
      <div className="mb-8">
        <h1 className="font-heading text-4xl font-black tracking-tighter">Ajustes</h1>
      </div>
      <MinhaConta />
      <Empresa />
    </div>
  );
}
