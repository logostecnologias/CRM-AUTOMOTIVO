import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Buildings, Lock, Megaphone, User, Warning } from "@phosphor-icons/react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatBRL } from "@/lib/currency";
import { rotuloPapel } from "@/lib/papeis";
import { t } from "@/lib/textos";
import AvisoGrupo from "@/components/whatsapp/AvisoGrupo";

const SENHA_MINIMA = 8;

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

  const { empresa } = dados;

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
          <div className="flex justify-between">
            <span className="text-ink-3">Situação</span>
            <span>{empresa.status === "active" ? "Ativa" : "Suspensa"}</span>
          </div>
        </div>

        {empresa.status !== "active" && (
          <div className="mt-4 flex items-start gap-2 border border-danger bg-danger-soft text-danger p-3 rounded-lg text-xs">
            <Warning size={14} weight="bold" className="shrink-0 mt-0.5" />
            <span>Esta {t("empresa")} está suspensa. Fale com o suporte para reativar.</span>
          </div>
        )}
      </Bloco>

    </>
  );
}

const NOME_EVENTO = {
  LeadSubmitted: "Lead", QualifiedLead: "Lead qualificado",
  InitiateCheckout: "Proposta", Purchase: "Compra",
};

/**
 * Conversions API do Meta: o funil devolve ao Meta quem virou lead e quem
 * comprou, para a campanha otimizar pelo perfil do comprador e não só por
 * quem manda mensagem. Qual etapa dispara qual evento fica na configuração do
 * funil; aqui fica a conexão.
 */
function MetaConversoes() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({ ativo: false, dataset_id: "", token: "", test_event_code: "" });
  const [salvando, setSalvando] = useState(false);
  const [testando, setTestando] = useState(false);
  const [eventos, setEventos] = useState([]);

  const carregarEventos = () =>
    api.get("/meta-conversoes/eventos").then((r) => setEventos(r.data.items)).catch(() => {});

  useEffect(() => {
    api.get("/meta-conversoes").then((r) => {
      setCfg(r.data);
      setForm({ ativo: r.data.ativo, dataset_id: r.data.dataset_id, token: "",
                test_event_code: r.data.test_event_code });
    }).catch(() => setCfg(false));
    carregarEventos();
  }, []);

  const salvar = async (e) => {
    e.preventDefault();
    setSalvando(true);
    try {
      // Token em branco = manter o gravado. Para apagar existe o link próprio.
      const corpo = { ...form, token: form.token.trim() ? form.token.trim() : undefined };
      const r = await api.put("/meta-conversoes", corpo);
      setCfg(r.data);
      setForm({ ...form, token: "" });
      toast.success(form.ativo ? "Integração com o Meta ligada" : "Configuração salva");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Não foi possível salvar");
    } finally {
      setSalvando(false);
    }
  };

  const apagarToken = async () => {
    try {
      const r = await api.put("/meta-conversoes", { ...form, token: "" });
      setCfg(r.data);
      toast.success("Token removido: passa a usar o da conexão de WhatsApp");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Não foi possível remover");
    }
  };

  const testar = async () => {
    setTestando(true);
    try {
      await api.post("/meta-conversoes/testar");
      toast.success("O Meta recebeu o evento de teste. Confira em Testar eventos.");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Falha no teste");
    } finally {
      setTestando(false);
    }
  };

  if (cfg === false) return null;

  return (
    <Bloco icone={Megaphone} titulo="Meta Ads · conversões do funil"
      hint={`Quando um ${t("negócio")} entra numa etapa, o Meta recebe o evento dela (Lead, Lead qualificado, Compra com valor). Com isso a campanha passa a procurar gente com o perfil de quem compra, não só de quem manda mensagem. Qual etapa envia qual evento se escolhe em Funil → Etapas.`}>
      {!cfg ? <div className="text-sm text-ink-3">Carregando…</div> : (
        <>
          <form onSubmit={salvar} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Campo label="ID do dataset (pixel)"
              hint="Gerenciador de Eventos → Fontes de dados → o número do conjunto de dados ligado ao seu WhatsApp.">
              <input className="zz-input font-mono" inputMode="numeric" value={form.dataset_id}
                data-testid="meta-dataset" placeholder="ex.: 123456789012345"
                onChange={(e) => setForm({ ...form, dataset_id: e.target.value })} />
            </Campo>
            <Campo label="Token de acesso"
              hint={cfg.token
                ? <>Gravado: <span className="font-mono">{cfg.token}</span> · <button type="button" className="underline" onClick={apagarToken}>remover</button></>
                : "Opcional. Em branco, usa o token da conexão de WhatsApp (precisa da permissão de eventos)."}>
              <input type="password" className="zz-input font-mono" value={form.token}
                autoComplete="off" data-testid="meta-token"
                placeholder={cfg.token ? "manter o gravado" : "EAA…"}
                onChange={(e) => setForm({ ...form, token: e.target.value })} />
            </Campo>
            <Campo label="Código de teste"
              hint="Opcional. Com ele, os eventos aparecem só em Testar eventos e não contam nos resultados. Apague quando terminar de testar.">
              <input className="zz-input font-mono" value={form.test_event_code}
                data-testid="meta-teste" placeholder="TEST12345"
                onChange={(e) => setForm({ ...form, test_event_code: e.target.value })} />
            </Campo>
            <Campo label="Envio">
              <label className="flex items-center gap-2 text-sm pt-2">
                <input type="checkbox" checked={form.ativo} data-testid="meta-ativo"
                  onChange={(e) => setForm({ ...form, ativo: e.target.checked })} />
                Enviar eventos do funil ao Meta
              </label>
            </Campo>
            <div className="sm:col-span-2 flex justify-end gap-2">
              <button type="button" className="zz-btn zz-btn-secondary" onClick={testar}
                disabled={testando || !cfg.dataset_id} data-testid="meta-testar">
                {testando ? "Testando…" : "Enviar evento de teste"}
              </button>
              <button type="submit" className="zz-btn" disabled={salvando} data-testid="meta-salvar">
                {salvando ? "Salvando…" : "Salvar"}
              </button>
            </div>
          </form>

          <div className="mt-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-2">Últimos envios</h3>
              <button type="button" className="text-xs underline text-ink-3" onClick={carregarEventos}>atualizar</button>
            </div>
            {eventos.length === 0 ? (
              <div className="text-xs text-ink-3">Nenhum evento enviado ainda.</div>
            ) : (
              <div className="border border-line rounded-lg divide-y divide-line text-xs" data-testid="meta-eventos">
                {eventos.map((ev) => (
                  <div key={ev.id} className="flex items-center gap-3 px-3 py-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${ev.status === "enviado" ? "bg-success" : "bg-danger"}`} />
                    <span className="font-semibold w-28 shrink-0">{NOME_EVENTO[ev.evento] || ev.evento}</span>
                    <span className="text-ink-2 truncate flex-1">
                      {ev.etapa}
                      {ev.valor ? ` · ${formatBRL(ev.valor)}` : ""}
                      {" · "}{ev.canal === "business_messaging" ? "clique do anúncio" : "telefone/e-mail"}
                      {ev.teste ? " · teste" : ""}
                      {ev.erro && <span className="text-danger"> · {ev.erro}</span>}
                    </span>
                    <span className="text-ink-3 shrink-0">{new Date(ev.created_at).toLocaleString("pt-BR")}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Bloco>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  return (
    <div className="zz-page-form" data-testid="settings-page">
      <div className="mb-8">
        <h1 className="font-heading text-4xl font-black tracking-tighter">Ajustes</h1>
      </div>
      <MinhaConta />
      <Empresa />
      {user?.role === "tenant_admin" && <MetaConversoes />}
      {user?.role === "tenant_admin" && <AvisoGrupo Bloco={Bloco} Campo={Campo} />}
    </div>
  );
}
