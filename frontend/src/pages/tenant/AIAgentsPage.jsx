import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import {
  Sparkle, CheckCircle, XCircle, ArrowSquareOut, ArrowClockwise, Trash, Key,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import ListaAgentes from "@/components/ia/ListaAgentes";

// Custo mensal estimado por modelo, para a empresa escolher com número na
// frente em vez de pelo nome. A carga de referência é a de um cliente médio:
// 50 atendimentos/dia x 6 respostas x 30 dias = 9.000 respostas, cada uma com
// ~1.800 tokens de entrada (dos quais ~1.500 vêm do cache) e ~120 de saída.
//
// A conta é feita aqui, e não no servidor, porque é uma projeção para a tela —
// o consumo real vem medido de `ai_usage`, e é ele que aparece embaixo.
const RESPOSTAS_MES = 9000;
const ENTRADA_NAO_CACHEADA = 330;
const ENTRADA_CACHEADA = 1500;
const SAIDA = 120;
// Câmbio só para dar ordem de grandeza em reais. Não é cotação — o valor real
// é cobrado em dólar pelo provedor, direto na conta do cliente.
const USD_BRL = 5.5;

function custoMensal(modelo) {
  const cacheLeitura = modelo.cache_leitura ?? modelo.entrada * 0.1;
  const usd =
    (RESPOSTAS_MES *
      (ENTRADA_NAO_CACHEADA * modelo.entrada +
        ENTRADA_CACHEADA * cacheLeitura +
        SAIDA * modelo.saida)) /
    1_000_000;
  return { usd, brl: usd * USD_BRL };
}

const brl = (v) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: v < 10 ? 2 : 0 });

export default function AIAgentsPage() {
  const [provedores, setProvedores] = useState([]);
  const [conexao, setConexao] = useState(null);
  const [consumo, setConsumo] = useState(null);
  const [plataforma, setPlataforma] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [ocupado, setOcupado] = useState(false);
  const [editando, setEditando] = useState(false);
  const [form, setForm] = useState({ provedor: "", modelo: "", chave_api: "" });

  const load = async () => {
    const { data } = await api.get("/ai/connection");
    setConexao(data.conexao);
    setConsumo(data.consumo);
    setPlataforma(data.plataforma_disponivel);
    return data.conexao;
  };

  useEffect(() => {
    Promise.all([api.get("/ai/providers"), load()])
      .then(([p, c]) => {
        setProvedores(p.data);
        const inicial = c?.provedor || p.data[0]?.id || "";
        setForm({
          provedor: inicial,
          modelo: c?.modelo || p.data.find((x) => x.id === inicial)?.modelos[0]?.id || "",
          chave_api: "",
        });
      })
      .catch((ex) => toast.error(formatApiErrorDetail(ex.response?.data?.detail)))
      .finally(() => setCarregando(false));
  }, []);

  const provedorAtual = provedores.find((p) => p.id === form.provedor);

  const escolherProvedor = (id) => {
    const p = provedores.find((x) => x.id === id);
    // Trocar de provedor invalida a chave digitada: ela é de outro serviço.
    setForm({ provedor: id, modelo: p?.modelos[0]?.id || "", chave_api: "" });
  };

  const salvar = async (e) => {
    e.preventDefault();
    setOcupado(true);
    try {
      const { data } = await api.put("/ai/connection", {
        provedor: form.provedor,
        modelo: form.modelo,
        chave_api: form.chave_api || undefined,
      });
      setConexao(data);
      setForm((f) => ({ ...f, chave_api: "" }));
      setEditando(false);
      toast.success("Conta de IA conectada e testada com sucesso.");
      load();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setOcupado(false);
    }
  };

  const testar = async () => {
    setOcupado(true);
    try {
      const { data } = await api.post("/ai/connection/test");
      if (data.ok) toast.success("Conexão funcionando.");
      else toast.error(data.erro);
      load();
    } finally {
      setOcupado(false);
    }
  };

  const desconectar = async () => {
    if (
      !(await confirmToast(
        "Desconectar a conta de IA? Os agentes param de responder até você conectar de novo.",
        { confirmLabel: "Desconectar" },
      ))
    )
      return;
    setOcupado(true);
    try {
      await api.delete("/ai/connection");
      setConexao(null);
      setEditando(false);
      toast.success("Conta de IA desconectada.");
      load();
    } finally {
      setOcupado(false);
    }
  };

  if (carregando) return <div className="p-8 text-ink-3 text-sm">Carregando…</div>;

  const conectada = conexao?.status === "conectada";
  const mostrarFormulario = !conexao || editando;

  return (
    <div className="p-8 max-w-4xl" data-testid="ai-agents-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-ink-3 mb-2">Automação</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Agentes de IA</h1>
        <p className="text-ink-2 mt-2 max-w-2xl text-sm">
          Conecte a conta de IA da sua empresa para que os agentes possam atender e responder
          automaticamente. O consumo é cobrado direto na sua conta do provedor, sem intermediário.
        </p>
      </div>

      {/* ---------------- Estado da conexão ---------------- */}
      {conexao && (
        <div
          className={`mb-6 border rounded-lg p-4 flex items-start gap-3 ${
            conectada ? "border-line-strong bg-surface zz-panel-hard" : "border-danger bg-danger-soft"
          }`}
          data-testid="ai-connection-status"
        >
          <div
            className={`w-9 h-9 shrink-0 flex items-center justify-center text-white ${
              conectada ? "bg-brand" : "bg-danger-solid"
            }`}
          >
            {conectada ? <CheckCircle size={18} weight="bold" /> : <XCircle size={18} weight="bold" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-bold text-sm">
              {conectada ? "Conectada" : "Com problema"} — {conexao.provedor_rotulo}
            </div>
            <div className="text-xs text-ink-2 mt-0.5">
              Modelo <span className="font-mono">{conexao.modelo}</span> · chave{" "}
              <span className="font-mono">{conexao.mascara}</span>
              {conexao.verificada_em && (
                <> · verificada em {new Date(conexao.verificada_em).toLocaleString("pt-BR")}</>
              )}
            </div>
            {conexao.ultimo_erro && (
              <div className="text-xs text-danger mt-1.5 font-medium">{conexao.ultimo_erro}</div>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            <button className="zz-btn zz-btn-secondary text-xs py-1" onClick={testar} disabled={ocupado} data-testid="ai-test-btn">
              <ArrowClockwise size={14} weight="bold" /> Testar
            </button>
            <button
              className="zz-btn zz-btn-secondary text-xs py-1"
              onClick={() => setEditando((v) => !v)}
              data-testid="ai-edit-btn"
            >
              <Key size={14} weight="bold" /> Alterar
            </button>
            <button
              className="zz-btn zz-btn-secondary text-xs py-1 text-danger"
              onClick={desconectar}
              disabled={ocupado}
              data-testid="ai-disconnect-btn"
            >
              <Trash size={14} weight="bold" />
            </button>
          </div>
        </div>
      )}

      {/* ---------------- Consumo ---------------- */}
      {consumo && conexao && (
        <div className="mb-6 border border-line bg-surface p-5 flex gap-8 rounded-lg" data-testid="ai-usage">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-3">Respostas no mês</div>
            <div className="font-heading text-2xl font-black tabular-nums">{consumo.chamadas.toLocaleString("pt-BR")}</div>
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-3">Tokens</div>
            <div className="font-heading text-2xl font-black tabular-nums">{consumo.tokens.toLocaleString("pt-BR")}</div>
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-3">Custo estimado</div>
            <div className="font-heading text-2xl font-black tabular-nums">
              {brl(consumo.custo_usd * USD_BRL)}
            </div>
            <div className="text-[10px] text-ink-3">US$ {consumo.custo_usd.toFixed(2)} na sua conta</div>
          </div>
        </div>
      )}

      {/* ---------------- Formulário de conexão ---------------- */}
      {mostrarFormulario && (
        <form onSubmit={salvar} className="border border-line-strong bg-surface zz-panel-hard rounded-lg" data-testid="ai-connect-form">
          <div className="p-5 border-b border-line">
            <div className="text-xs font-bold uppercase tracking-wider text-ink-2 mb-3">
              1. Escolha o provedor
            </div>
            <div className="grid grid-cols-2 gap-3">
              {provedores.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => escolherProvedor(p.id)}
                  data-testid={`ai-provider-${p.id}`}
                  className={`border rounded-lg p-3 text-left transition-colors ${
                    form.provedor === p.id
                      ? "border-brand bg-brand text-brand-fg"
                      : "border-line hover:border-line-strong"
                  }`}
                >
                  <div className="font-bold text-sm">{p.rotulo}</div>
                </button>
              ))}
            </div>
          </div>

          {provedorAtual && (
            <>
              <div className="p-5 border-b border-line">
                <div className="text-xs font-bold uppercase tracking-wider text-ink-2 mb-3">
                  2. Escolha o modelo
                </div>
                <div className="space-y-2">
                  {provedorAtual.modelos.map((m) => {
                    const c = custoMensal(m);
                    return (
                      <label
                        key={m.id}
                        className={`flex items-start gap-3 border rounded-lg p-3 cursor-pointer transition-colors ${
                          form.modelo === m.id ? "border-info bg-info-soft" : "border-line hover:border-line-strong"
                        }`}
                      >
                        <input
                          type="radio"
                          name="modelo"
                          className="mt-1"
                          checked={form.modelo === m.id}
                          onChange={() => setForm({ ...form, modelo: m.id })}
                          data-testid={`ai-model-${m.id}`}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="font-bold text-sm">{m.rotulo}</div>
                          <div className="text-xs text-ink-2">{m.nota}</div>
                        </div>
                        <div className="text-right shrink-0">
                          <div className="font-heading font-black text-sm tabular-nums">~{brl(c.brl)}</div>
                          <div className="text-[10px] text-ink-3">por mês</div>
                        </div>
                      </label>
                    );
                  })}
                </div>
                <p className="text-[11px] text-ink-3 mt-2">
                  Estimativa para 50 atendimentos por dia (~9.000 respostas no mês). O valor é cobrado
                  em dólar direto na sua conta do provedor.
                </p>
              </div>

              <div className="p-5">
                <div className="text-xs font-bold uppercase tracking-wider text-ink-2 mb-3">
                  3. Cole a chave de API
                </div>
                <div className="flex gap-2 mb-3">
                  <a
                    href={provedorAtual.console_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="zz-btn zz-btn-secondary text-xs py-1"
                    data-testid="ai-open-console"
                  >
                    <ArrowSquareOut size={14} weight="bold" /> Abrir o console da {provedorAtual.rotulo}
                  </a>
                </div>
                <input
                  type="password"
                  className="zz-input font-mono"
                  autoComplete="off"
                  placeholder={
                    conexao && conexao.provedor === form.provedor
                      ? "Deixe em branco para manter a chave atual"
                      : `Cole aqui a chave (começa com ${provedorAtual.id === "anthropic" ? "sk-ant-" : "sk-"})`
                  }
                  value={form.chave_api}
                  onChange={(e) => setForm({ ...form, chave_api: e.target.value })}
                  data-testid="ai-key-input"
                />
                <p className="text-[11px] text-ink-3 mt-2">
                  A chave é guardada cifrada e nunca é exibida de volta — só os últimos dígitos. Ao
                  salvar, fazemos uma chamada de teste para confirmar que ela funciona no modelo
                  escolhido.
                </p>

                <div className="flex gap-2 mt-4">
                  <button type="submit" className="zz-btn" disabled={ocupado} data-testid="ai-save-btn">
                    {ocupado ? "Testando…" : conexao ? "Salvar e testar" : "Conectar"}
                  </button>
                  {conexao && (
                    <button type="button" className="zz-btn zz-btn-secondary text-xs py-1" onClick={() => setEditando(false)}>
                      Cancelar
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </form>
      )}

      {/* ---------------- Agentes ---------------- */}
      {/* Renderizada mesmo sem conexão: dá para configurar o agente antes de
          conectar a conta, e a própria lista avisa que ele não vai responder
          enquanto não houver credencial. */}
      <ListaAgentes conexaoOk={conectada || plataforma} />

      {/* ---------------- Rede de segurança ---------------- */}
      {!conexao && (
        <div className="mt-6 border border-line bg-surface-2 p-5 flex gap-3 rounded-lg" data-testid="ai-fallback-note">
          <Sparkle size={18} weight="bold" className="text-ink-3 shrink-0 mt-0.5" />
          <p className="text-xs text-ink-2">
            {plataforma ? (
              <>
                Sem conta conectada, os agentes usam a IA inclusa no seu plano, dentro do limite
                mensal contratado. Conectar a conta da empresa remove esse limite e passa o custo
                para a sua conta no provedor.
              </>
            ) : (
              <>
                Enquanto nenhuma conta estiver conectada, os agentes de IA não conseguem responder.
                A conexão leva menos de um minuto.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
