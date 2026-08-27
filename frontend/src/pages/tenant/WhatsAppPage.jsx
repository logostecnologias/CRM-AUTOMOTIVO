import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import {
  WhatsappLogo, CheckCircle, XCircle, ArrowClockwise, Plus, Trash, Key,
  WarningCircle, Eye, EyeSlash,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";

// O vínculo bot ↔ conexão é escolhido no bot (tela de Robôs / editor de fluxo).
// Aqui os bots só servem pra saber se a conexão tem quem atenda.
//
// Mesmas condições que o motor aplica em _load_bot_flow: bot pausado ou com
// fluxo não publicado simplesmente não roda.
const usavel = (b) => b && b.status === "ativo" && b.publicado;

export default function WhatsAppPage() {
  const [connections, setConnections] = useState([]);
  const [depts, setDepts] = useState([]);
  const [bots, setBots] = useState([]);
  const [creating, setCreating] = useState(false);
  const [newForm, setNewForm] = useState({ nome: "", departamento_padrao_id: "" });
  const [busyId, setBusyId] = useState(null);
  const [editandoId, setEditandoId] = useState(null);

  const load = () => api.get("/whatsapp/connections").then((r) => setConnections(r.data));
  useEffect(() => {
    load();
    api.get("/departments").then((r) => setDepts(r.data)).catch(() => {});
    api.get("/bots").then((r) => setBots(r.data)).catch(() => {});
  }, []);

  const [createConnection, criando] = useAcao(async (e) => {
    e.preventDefault();
    if (!newForm.nome.trim()) return;
    try {
      const { data } = await api.post("/whatsapp/connections", {
        nome: newForm.nome,
        departamento_padrao_id: newForm.departamento_padrao_id || null,
      });
      setConnections((cs) => [...cs, data]);
      setNewForm({ nome: "", departamento_padrao_id: "" });
      setCreating(false);
      setEditandoId(data.id);
      toast.success("Conexão criada. Agora cadastre o número da Cloud API.");
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || "Erro ao criar conexão");
    }
  });

  const salvarCredenciais = async (id, corpo) => {
    setBusyId(id);
    try {
      const { data } = await api.post(`/whatsapp/connections/${id}/credenciais`, corpo);
      setConnections((cs) => cs.map((c) => (c.id === id ? data : c)));
      setEditandoId(null);
      if (data.aviso) toast.warning(data.aviso, { duration: 12000 });
      else toast.success("Número validado e webhook assinado.");
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || "Não foi possível validar",
        { duration: 10000 });
    } finally { setBusyId(null); }
  };

  const verificar = async (id) => {
    setBusyId(id);
    try {
      const { data } = await api.post(`/whatsapp/connections/${id}/verificar`);
      setConnections((cs) => cs.map((c) => (c.id === id ? data : c)));
      toast.success("Conexão verificada");
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || "Falha ao verificar");
      load();
    } finally { setBusyId(null); }
  };

  const removeConnection = async (id) => {
    if (!(await confirmToast("Excluir esta conexão? O número deixa de receber e enviar por aqui.", { confirmLabel: "Excluir" }))) return;
    setBusyId(id);
    try {
      await api.delete(`/whatsapp/connections/${id}`);
      setConnections((cs) => cs.filter((c) => c.id !== id));
      toast.success("Conexão excluída");
    } finally { setBusyId(null); }
  };

  const updateField = async (id, patch) => {
    const { data } = await api.patch(`/whatsapp/connections/${id}`, patch);
    setConnections((cs) => cs.map((c) => (c.id === id ? data : c)));
    toast.success("Conexão atualizada");
  };

  return (
    <div className="zz-page" data-testid="whatsapp-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Conexões WhatsApp</h1>
          <p className="text-ink-2 mt-2 max-w-2xl">
            Cada conexão é um número da API oficial do WhatsApp (Cloud API da Meta),
            com seu próprio departamento padrão. Os robôs são vinculados na tela de Robôs.
          </p>
        </div>
        <button data-testid="new-connection-btn" onClick={() => setCreating((v) => !v)} className="zz-btn">
          <Plus size={16} weight="bold" /> Nova conexão
        </button>
      </div>

      {creating && (
        <form onSubmit={createConnection} className="mb-6 border border-line-strong bg-surface p-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 zz-panel-hard rounded-lg">
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Nome da conexão</label>
            <input autoFocus required data-testid="new-connection-name" className="zz-input"
              value={newForm.nome} onChange={(e) => setNewForm({ ...newForm, nome: e.target.value })}
              placeholder="Ex: Vendas, Suporte, Loja 2" />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Departamento padrão</label>
            <select className="zz-input" value={newForm.departamento_padrao_id}
              onChange={(e) => setNewForm({ ...newForm, departamento_padrao_id: e.target.value })}>
              <option value="">— nenhum —</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2 lg:col-span-3 flex gap-2 justify-end">
            <button type="button" onClick={() => setCreating(false)} className="zz-btn zz-btn-secondary">Cancelar</button>
            <button type="submit" className="zz-btn" data-testid="new-connection-submit"
              disabled={criando}>{criando ? "Criando…" : "Criar conexão"}</button>
          </div>
        </form>
      )}

      {connections.length === 0 && !creating && (
        <div className="border border-dashed border-line rounded-xl bg-surface p-16 text-center">
          <div className="font-heading text-2xl font-black tracking-tighter mb-2">Nenhuma conexão ainda.</div>
          <div className="text-sm text-ink-2">Crie a primeira conexão de WhatsApp da empresa.</div>
        </div>
      )}

      <div className="space-y-4">
        {connections.map((conn) => (
          <ConnectionCard
            key={conn.id}
            conn={conn}
            depts={depts}
            bots={bots}
            busy={busyId === conn.id}
            editando={editandoId === conn.id}
            onEditar={() => setEditandoId(editandoId === conn.id ? null : conn.id)}
            onSalvarCredenciais={(corpo) => salvarCredenciais(conn.id, corpo)}
            onVerificar={() => verificar(conn.id)}
            onRemove={() => removeConnection(conn.id)}
            onUpdateField={(patch) => updateField(conn.id, patch)}
          />
        ))}
      </div>
    </div>
  );
}

function ConnectionCard({ conn, depts, bots, busy, editando, onEditar, onSalvarCredenciais,
                          onVerificar, onRemove, onUpdateField }) {
  const botsDaConexao = bots.filter((b) => b.connection_id === conn.id);
  // Espelha _pick_bot_for_new_session: só bot desta conexão, ativo e publicado.
  const temBotPrimeiraMensagem = botsDaConexao.some(
    (b) => usavel(b) && (b.trigger || "first_message") === "first_message"
  );
  const cadastrado = Boolean(conn.phone_number_id);

  return (
    <div className="border border-line-strong bg-surface p-6 zz-panel-hard rounded-lg" data-testid={`connection-card-${conn.id}`}>
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 bg-success-solid text-success-fg flex items-center justify-center border border-line-strong shrink-0 rounded-full">
            <WhatsappLogo size={24} weight="bold" />
          </div>
          <div>
            <div className="font-heading text-xl font-black tracking-tighter">{conn.nome}</div>
            <div className="text-xs font-mono text-ink-3">
              Status: <StatusBadge status={conn.status} />
              {conn.qualidade && <QualidadeBadge nota={conn.qualidade} />}
            </div>
            {conn.numero_exibicao && (
              <div className="text-xs text-ink mt-1">
                <span className="font-mono">{conn.numero_exibicao}</span>
                {conn.nome_verificado && <span className="text-ink-2"> · {conn.nome_verificado}</span>}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {cadastrado && (
            <button onClick={onVerificar} disabled={busy} className="zz-btn zz-btn-secondary"
              data-testid={`verify-btn-${conn.id}`}>
              <ArrowClockwise size={14} weight="bold" /> {busy ? "Verificando…" : "Verificar"}
            </button>
          )}
          <button onClick={onEditar} disabled={busy} className="zz-btn" data-testid={`creds-btn-${conn.id}`}>
            <Key size={14} weight="bold" /> {cadastrado ? "Credenciais" : "Cadastrar número"}
          </button>
          <button onClick={onRemove} disabled={busy} className="p-3 border border-line hover:bg-danger-soft text-danger rounded-lg" title="Excluir conexão" data-testid={`delete-btn-${conn.id}`}>
            <Trash size={14} weight="bold" />
          </button>
        </div>
      </div>

      {conn.status === "erro" && conn.ultimo_erro && (
        <div className="mt-4 text-xs text-danger bg-danger-soft border border-danger p-3 rounded-lg flex gap-2"
          data-testid={`conn-error-${conn.id}`}>
          <WarningCircle size={16} weight="bold" className="shrink-0 mt-px" />
          <div>
            <strong>A Meta recusou esta conexão.</strong> {conn.ultimo_erro}
          </div>
        </div>
      )}

      {cadastrado && conn.webhook_assinado === false && (
        <div className="mt-4 text-xs text-warning bg-warning-soft border border-warning p-3 rounded-lg">
          <strong>Webhook não assinado.</strong> O número envia mensagens, mas as respostas
          dos contatos não chegam até o app ser assinado na conta da Meta. Cadastre as
          credenciais de novo com um token que tenha a permissão
          <span className="font-mono"> whatsapp_business_management</span>.
        </div>
      )}

      {editando && (
        <FormCredenciais conn={conn} busy={busy} onSalvar={onSalvarCredenciais} />
      )}

      <div className="mt-4 pt-4 border-t border-line grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-ink-3 block mb-1.5">Departamento padrão</label>
          <select className="zz-input" style={{ padding: "0.4rem 0.6rem" }}
            value={conn.departamento_padrao_id || ""}
            onChange={(e) => onUpdateField({ departamento_padrao_id: e.target.value || null })}
            data-testid={`dept-select-${conn.id}`}>
            <option value="">— nenhum —</option>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
          </select>
        </div>
      </div>

      {!temBotPrimeiraMensagem && (
        <div className="mt-3 text-xs text-warning bg-warning-soft border border-warning p-2 rounded-lg" data-testid={`no-first-bot-warning-${conn.id}`}>
          <strong>Sem bot de primeira mensagem.</strong> Mensagens que não casarem com a palavra-chave vão
          direto para a fila de atendimento humano, sem nenhuma resposta automática para o contato.
        </div>
      )}
    </div>
  );
}

// O token nunca volta do servidor, só a máscara. Por isso o campo nasce vazio
// numa conexão já cadastrada: deixá-lo em branco mantém o que está guardado, e
// preenchê-lo troca a credencial. Devolver o token para "preencher o campo de
// edição" o faria trafegar a cada abertura de tela.
function FormCredenciais({ conn, busy, onSalvar }) {
  const [form, setForm] = useState({
    phone_number_id: conn.phone_number_id || "",
    waba_id: conn.waba_id || "",
    token: "",
  });
  const [vendoToken, setVendoToken] = useState(false);

  const [enviar, enviando] = useAcao(async (e) => {
    e.preventDefault();
    await onSalvar({
      phone_number_id: form.phone_number_id.trim(),
      waba_id: form.waba_id.trim(),
      token: form.token.trim() || null,
    });
  });

  return (
    <form onSubmit={enviar} className="mt-4 pt-4 border-t border-line"
      data-testid={`creds-form-${conn.id}`}>
      <div className="text-xs text-ink-2 mb-3 max-w-3xl">
        Os três valores estão no painel da Meta, em <strong>WhatsApp &gt; Configuração da API</strong>.
        O número é validado agora: se algo estiver errado, nada é gravado.
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-ink-3 block mb-1.5">
            ID do número (phone number ID)
          </label>
          <input required className="zz-input" inputMode="numeric"
            value={form.phone_number_id} placeholder="106540352242922"
            onChange={(e) => setForm({ ...form, phone_number_id: e.target.value })}
            data-testid={`pnid-${conn.id}`} />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-ink-3 block mb-1.5">
            ID da conta (WABA ID)
          </label>
          <input required className="zz-input" inputMode="numeric"
            value={form.waba_id} placeholder="102290129340398"
            onChange={(e) => setForm({ ...form, waba_id: e.target.value })}
            data-testid={`waba-${conn.id}`} />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-ink-3 block mb-1.5">
            Token de acesso {conn.token_mascara && <span className="font-mono normal-case text-ink-2">({conn.token_mascara})</span>}
          </label>
          <div className="relative">
            <input className="zz-input pr-10" type={vendoToken ? "text" : "password"}
              autoComplete="new-password"
              value={form.token} required={!conn.token_mascara}
              placeholder={conn.token_mascara ? "deixe vazio para manter" : "EAAG…"}
              onChange={(e) => setForm({ ...form, token: e.target.value })}
              data-testid={`token-${conn.id}`} />
            <button type="button" onClick={() => setVendoToken((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink"
              title={vendoToken ? "Ocultar" : "Mostrar"}>
              {vendoToken ? <EyeSlash size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
      </div>
      <div className="flex justify-end mt-4">
        <button type="submit" className="zz-btn" disabled={busy || enviando}
          data-testid={`save-creds-${conn.id}`}>
          {busy || enviando ? "Validando com a Meta…" : "Validar e salvar"}
        </button>
      </div>
    </form>
  );
}

function StatusBadge({ status }) {
  const map = {
    conectado: "text-success",
    erro: "text-danger",
    desconectado: "text-ink-3",
  };
  const label = { conectado: "conectado", erro: "com erro", desconectado: "sem número" }[status] || "—";
  return (
    <span className={`inline-flex items-center gap-1 font-bold ${map[status] || "text-ink-3"}`}>
      {status === "conectado" && <CheckCircle size={12} weight="bold" />}
      {status === "erro" && <XCircle size={12} weight="bold" />}
      {label}
    </span>
  );
}

// A nota de qualidade é da Meta e vale dinheiro: nota baixa reduz o limite
// diário de conversas iniciadas pela empresa, e chega a suspender o número.
// Quem precisa saber a tempo de mudar o conteúdo dos disparos é o cliente.
function QualidadeBadge({ nota }) {
  const cor = { GREEN: "text-success", YELLOW: "text-warning", RED: "text-danger" }[nota] || "text-ink-3";
  const rotulo = { GREEN: "qualidade alta", YELLOW: "qualidade média", RED: "qualidade baixa" }[nota] || nota;
  return <span className={`ml-2 font-bold ${cor}`}>· {rotulo}</span>;
}
