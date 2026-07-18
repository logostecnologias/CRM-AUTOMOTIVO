import { useEffect, useState } from "react";
import api from "@/lib/api";
import { WhatsappLogo, CheckCircle, QrCode, XCircle, ArrowClockwise } from "@phosphor-icons/react";
import { toast, Toaster } from "sonner";

export default function WhatsAppPage() {
  const [conn, setConn] = useState(null);
  const [depts, setDepts] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = () => api.get("/whatsapp/status").then((r) => setConn(r.data));
  useEffect(() => {
    load();
    api.get("/departments").then((r) => setDepts(r.data)).catch(() => {});
  }, []);

  // Poll while pairing to catch status update from webhook
  useEffect(() => {
    if (conn?.status === "pareando") {
      const t = setInterval(load, 3000);
      return () => clearInterval(t);
    }
  }, [conn?.status]);

  const connect = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/whatsapp/connect");
      setConn(data);
      toast.success("Instância criada. Escaneie o QR Code.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao conectar");
    } finally { setLoading(false); }
  };

  const disconnect = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/whatsapp/disconnect");
      setConn(data);
      toast.info("Desconectado do WhatsApp");
    } finally { setLoading(false); }
  };

  const setDefaultDept = async (deptId) => {
    const { data } = await api.patch("/whatsapp/connection", { departamento_padrao_id: deptId || null });
    setConn(data);
    toast.success("Departamento padrão atualizado");
  };

  const qrSrc = conn?.qrcode_atual
    ? (conn.qrcode_atual.startsWith("data:") ? conn.qrcode_atual : `data:image/png;base64,${conn.qrcode_atual}`)
    : null;

  return (
    <div className="p-8 max-w-4xl" data-testid="whatsapp-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Integração</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Conectar WhatsApp</h1>
        <p className="text-slate-600 mt-2 max-w-2xl">
          Vincule o número da empresa via <span className="font-semibold">Evolution API</span>. Após escanear o QR, a instância se conecta e o bot ativo começa a responder mensagens reais.
        </p>
      </div>

      <div className="border border-slate-900 bg-white p-6 zz-panel-hard">
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-green-500 text-white flex items-center justify-center border border-slate-900">
              <WhatsappLogo size={28} weight="bold" />
            </div>
            <div>
              <div className="font-heading text-2xl font-black tracking-tighter">WhatsApp Business</div>
              <div className="text-xs font-mono text-slate-500">
                Status: <StatusBadge status={conn?.status} />
                {conn?.evolution_instance_name && (
                  <> · Instância <span className="text-slate-700">{conn.evolution_instance_name}</span></>
                )}
              </div>
              {conn?.numero && <div className="text-xs text-slate-700 mt-1">Número: <span className="font-mono">{conn.numero}</span></div>}
            </div>
          </div>
          <button data-testid="refresh-status" onClick={load} className="p-2 border border-slate-300 hover:bg-slate-50" title="Atualizar">
            <ArrowClockwise size={14} weight="bold" />
          </button>
        </div>

        {(!conn || conn.status === "desconectado") && (
          <div>
            <p className="text-sm text-slate-700 mb-4">
              Clique em <span className="font-bold">Conectar WhatsApp</span> para criar a instância no Evolution API. Um QR Code será gerado; escaneie-o em <span className="font-mono">Dispositivos conectados → Conectar dispositivo</span>.
            </p>
            <button data-testid="start-pairing" onClick={connect} disabled={loading} className="zz-btn">
              <QrCode size={16} weight="bold" /> {loading ? "Criando instância..." : "Conectar WhatsApp"}
            </button>
          </div>
        )}

        {conn?.status === "pareando" && (
          <div className="flex gap-8 items-start flex-wrap">
            {qrSrc ? (
              <img src={qrSrc} alt="QR Code" className="w-64 h-64 border-2 border-slate-900 bg-white p-2" data-testid="qr-image" />
            ) : (
              <div className="w-64 h-64 border-2 border-dashed border-slate-400 flex items-center justify-center text-slate-500 text-sm">
                Aguardando QR do Evolution...
              </div>
            )}
            <div className="flex-1 min-w-[240px] space-y-3">
              <div className="text-sm text-slate-700">
                Escaneie o QR ao lado com o WhatsApp da empresa. A tela atualiza automaticamente quando a conexão for concluída.
              </div>
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-500 p-2">
                O QR expira em ~60s — se expirar, clique em Atualizar ou refaça a conexão.
              </div>
              <button onClick={disconnect} className="zz-btn zz-btn-secondary">Cancelar</button>
            </div>
          </div>
        )}

        {conn?.status === "conectado" && (
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-2 text-green-700">
              <CheckCircle size={20} weight="bold" />
              <span className="font-semibold">WhatsApp conectado. O bot ativo já está respondendo mensagens.</span>
            </div>
            <button data-testid="disconnect-btn" onClick={disconnect} disabled={loading} className="zz-btn zz-btn-danger">
              <XCircle size={16} weight="bold" /> Desconectar
            </button>
          </div>
        )}
      </div>

      <div className="mt-6 border border-slate-200 bg-white p-4" data-testid="dept-default-block">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">Departamento padrão desta conexão</div>
        <p className="text-xs text-slate-500 mb-2">Novas conversas iniciadas nesta conexão entrarão neste departamento por padrão.</p>
        <select
          className="zz-input" style={{ maxWidth: 340 }}
          value={conn?.departamento_padrao_id || ""}
          onChange={(e) => setDefaultDept(e.target.value)}
          data-testid="default-dept-select"
        >
          <option value="">— nenhum —</option>
          {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
        </select>
      </div>

      <div className="mt-6 text-xs text-slate-500 border border-slate-200 bg-white p-4">
        <div className="font-bold uppercase tracking-wider text-slate-600 mb-2">Como funciona</div>
        <ol className="list-decimal ml-4 space-y-1">
          <li>Ao conectar, criamos uma instância <span className="font-mono">zappzen_{"{"}tenant_id{"}"}</span> no Evolution API e apontamos o webhook para nosso backend.</li>
          <li>Ao escanear o QR, o Evolution notifica o webhook e o status vira <span className="font-mono">conectado</span>.</li>
          <li>Mensagens recebidas caem no motor de fluxos, que responde pelo bot ativo publicado.</li>
          <li>Conversas transferidas para humano aparecem na Caixa de Entrada e você responde direto pelo painel.</li>
        </ol>
      </div>
      <Toaster position="bottom-right" />
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    conectado: "text-green-700",
    pareando: "text-amber-700",
    desconectado: "text-slate-500",
  };
  return <span className={map[status] || "text-slate-500"}>{status || "—"}</span>;
}
