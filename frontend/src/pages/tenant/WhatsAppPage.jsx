import { useEffect, useState } from "react";
import api from "@/lib/api";
import {
  WhatsappLogo, CheckCircle, QrCode, XCircle, ArrowClockwise, Plus, Trash,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";

// O vínculo é escolhido no bot (tela de Robôs / editor de fluxo). Aqui a
// conexão só mostra, em leitura, quem está apontando pra ela.
const LABEL_GATILHO = {
  first_message: "primeira mensagem",
  keyword: "palavra-chave",
  no_response: "sem resposta",
};

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
  const [expandedQrId, setExpandedQrId] = useState(null);

  const load = () => api.get("/whatsapp/connections").then((r) => setConnections(r.data));
  useEffect(() => {
    load();
    api.get("/departments").then((r) => setDepts(r.data)).catch(() => {});
    api.get("/bots").then((r) => setBots(r.data)).catch(() => {});
  }, []);

  // Poll while any connection is pairing, so QR/status updates from the webhook show up.
  useEffect(() => {
    if (connections.some((c) => c.status === "pareando")) {
      const t = setInterval(load, 3000);
      return () => clearInterval(t);
    }
  }, [connections]);

  const createConnection = async (e) => {
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
      toast.success("Conexão criada. Clique em Conectar para gerar o QR Code.");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao criar conexão");
    }
  };

  const connect = async (id) => {
    setBusyId(id);
    try {
      const { data } = await api.post(`/whatsapp/connections/${id}/connect`);
      setConnections((cs) => cs.map((c) => (c.id === id ? data : c)));
      setExpandedQrId(id);
      toast.success("Instância criada. Escaneie o QR Code.");
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao conectar");
    } finally { setBusyId(null); }
  };

  const disconnect = async (id) => {
    setBusyId(id);
    try {
      const { data } = await api.post(`/whatsapp/connections/${id}/disconnect`);
      setConnections((cs) => cs.map((c) => (c.id === id ? data : c)));
      toast.info("Desconectado do WhatsApp");
    } finally { setBusyId(null); }
  };

  const removeConnection = async (id) => {
    if (!(await confirmToast("Excluir esta conexão? Isso desconecta o número e apaga o vínculo.", { confirmLabel: "Excluir" }))) return;
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
    <div className="p-8 max-w-4xl" data-testid="whatsapp-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Integração</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Conexões WhatsApp</h1>
          <p className="text-slate-600 mt-2 max-w-2xl">
            Cada conexão é um número de WhatsApp independente, com sua própria instância e departamento padrão. Os robôs são vinculados na tela de Robôs.
          </p>
        </div>
        <button data-testid="new-connection-btn" onClick={() => setCreating((v) => !v)} className="zz-btn">
          <Plus size={16} weight="bold" /> Nova conexão
        </button>
      </div>

      {creating && (
        <form onSubmit={createConnection} className="mb-6 border border-slate-900 bg-white p-4 grid grid-cols-3 gap-4 zz-panel-hard">
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Nome da conexão</label>
            <input autoFocus required data-testid="new-connection-name" className="zz-input"
              value={newForm.nome} onChange={(e) => setNewForm({ ...newForm, nome: e.target.value })}
              placeholder="Ex: Vendas, Suporte, Loja 2" />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Departamento padrão</label>
            <select className="zz-input" value={newForm.departamento_padrao_id}
              onChange={(e) => setNewForm({ ...newForm, departamento_padrao_id: e.target.value })}>
              <option value="">— nenhum —</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
            </select>
          </div>
          <div className="col-span-3 flex gap-2 justify-end">
            <button type="button" onClick={() => setCreating(false)} className="zz-btn zz-btn-secondary">Cancelar</button>
            <button type="submit" className="zz-btn" data-testid="new-connection-submit">Criar conexão</button>
          </div>
        </form>
      )}

      {connections.length === 0 && !creating && (
        <div className="border border-dashed border-slate-300 bg-white p-16 text-center">
          <div className="font-heading text-2xl font-black tracking-tighter mb-2">Nenhuma conexão ainda.</div>
          <div className="text-sm text-slate-600">Crie a primeira conexão de WhatsApp da empresa.</div>
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
            expanded={expandedQrId === conn.id}
            onToggleExpand={() => setExpandedQrId(expandedQrId === conn.id ? null : conn.id)}
            onConnect={() => connect(conn.id)}
            onDisconnect={() => disconnect(conn.id)}
            onRemove={() => removeConnection(conn.id)}
            onUpdateField={(patch) => updateField(conn.id, patch)}
          />
        ))}
      </div>
    </div>
  );
}

function ConnectionCard({ conn, depts, bots, busy, expanded, onToggleExpand, onConnect, onDisconnect, onRemove, onUpdateField }) {
  const qrSrc = conn.qrcode_atual
    ? (conn.qrcode_atual.startsWith("data:") ? conn.qrcode_atual : `data:image/png;base64,${conn.qrcode_atual}`)
    : null;

  const botsDaConexao = bots.filter((b) => b.connection_id === conn.id);
  // Espelha _pick_bot_for_new_session: só bot desta conexão, ativo e publicado.
  const temBotPrimeiraMensagem = botsDaConexao.some(
    (b) => usavel(b) && (b.trigger || "first_message") === "first_message"
  );

  return (
    <div className="border border-slate-900 bg-white p-5 zz-panel-hard" data-testid={`connection-card-${conn.id}`}>
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 bg-green-500 text-white flex items-center justify-center border border-slate-900 shrink-0">
            <WhatsappLogo size={24} weight="bold" />
          </div>
          <div>
            <div className="font-heading text-xl font-black tracking-tighter">{conn.nome}</div>
            <div className="text-xs font-mono text-slate-500">
              Status: <StatusBadge status={conn.status} />
            </div>
            {conn.numero && <div className="text-xs text-slate-700 mt-1">Número: <span className="font-mono">{conn.numero}</span></div>}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {conn.status === "pareando" && (
            <button onClick={onToggleExpand} className="p-2 border border-slate-300 hover:bg-slate-50" title="Ver QR Code" data-testid={`toggle-qr-${conn.id}`}>
              <QrCode size={14} weight="bold" />
            </button>
          )}
          {(!conn.status || conn.status === "desconectado") && (
            <button onClick={onConnect} disabled={busy} className="zz-btn" data-testid={`connect-btn-${conn.id}`}>
              <QrCode size={14} weight="bold" /> {busy ? "Conectando..." : "Conectar"}
            </button>
          )}
          {(conn.status === "conectado" || conn.status === "pareando") && (
            <button onClick={onDisconnect} disabled={busy} className="zz-btn zz-btn-danger" data-testid={`disconnect-btn-${conn.id}`}>
              <XCircle size={14} weight="bold" /> Desconectar
            </button>
          )}
          <button onClick={onRemove} disabled={busy} className="p-2 border border-slate-300 hover:bg-red-100 text-red-600" title="Excluir conexão" data-testid={`delete-btn-${conn.id}`}>
            <Trash size={14} weight="bold" />
          </button>
        </div>
      </div>

      {conn.status === "pareando" && expanded && (
        <div className="flex gap-8 items-start flex-wrap mt-4 pt-4 border-t border-slate-200">
          {qrSrc ? (
            <img src={qrSrc} alt="QR Code" className="w-56 h-56 border-2 border-slate-900 bg-white p-2" data-testid={`qr-image-${conn.id}`} />
          ) : (
            <div className="w-56 h-56 border-2 border-dashed border-slate-400 flex items-center justify-center text-slate-500 text-sm">
              Aguardando QR Code...
            </div>
          )}
          <div className="flex-1 min-w-[220px] space-y-2">
            <div className="text-sm text-slate-700">
              Escaneie com o WhatsApp deste número. A tela atualiza sozinha quando a conexão for concluída.
            </div>
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-500 p-2">
              O QR expira em ~60s — se expirar, desconecte e conecte novamente.
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-slate-200 grid grid-cols-3 gap-4">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block mb-1.5">Departamento padrão</label>
          <select className="zz-input" style={{ padding: "0.4rem 0.6rem" }}
            value={conn.departamento_padrao_id || ""}
            onChange={(e) => onUpdateField({ departamento_padrao_id: e.target.value || null })}
            data-testid={`dept-select-${conn.id}`}>
            <option value="">— nenhum —</option>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
          </select>
        </div>
        <div className="col-span-2">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block mb-1.5">Robôs desta conexão</label>
          <div className="text-sm text-slate-700" data-testid={`conn-bots-${conn.id}`}>
            {botsDaConexao.length === 0
              ? <span className="italic text-slate-400">nenhum — vincule na tela de Robôs</span>
              : botsDaConexao.map((b) => `${b.name} (${LABEL_GATILHO[b.trigger] || b.trigger})`).join(" · ")}
          </div>
        </div>
      </div>

      {!temBotPrimeiraMensagem && (
        <div className="mt-3 text-xs text-amber-800 bg-amber-50 border border-amber-500 p-2" data-testid={`no-first-bot-warning-${conn.id}`}>
          <strong>Sem bot de primeira mensagem.</strong> Mensagens que não casarem com a palavra-chave vão
          direto para a fila de atendimento humano, sem nenhuma resposta automática para o contato.
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    conectado: "text-green-700",
    pareando: "text-amber-700",
    desconectado: "text-slate-500",
  };
  const label = { conectado: "conectado", pareando: "pareando", desconectado: "desconectado" }[status] || "—";
  return (
    <span className={`inline-flex items-center gap-1 font-bold ${map[status] || "text-slate-500"}`}>
      {status === "conectado" && <CheckCircle size={12} weight="bold" />}
      {status === "pareando" && <ArrowClockwise size={12} weight="bold" />}
      {label}
    </span>
  );
}
