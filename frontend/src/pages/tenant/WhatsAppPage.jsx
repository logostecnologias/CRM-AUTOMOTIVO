import { useEffect, useState } from "react";
import api from "@/lib/api";
import { WhatsappLogo, CheckCircle, QrCode, XCircle } from "@phosphor-icons/react";
import { toast, Toaster } from "sonner";

function FakeQR({ value }) {
  // Deterministic pixel grid based on string
  const size = 21;
  const cells = [];
  for (let i = 0; i < size * size; i++) {
    const c = value.charCodeAt(i % value.length) + i * 7;
    cells.push((c % 3) === 0);
  }
  return (
    <div className="grid p-3 bg-white border-2 border-slate-900" style={{ gridTemplateColumns: `repeat(${size}, 1fr)`, gap: 1, width: 260, height: 260 }}>
      {cells.map((on, i) => (
        <div key={i} style={{ background: on ? "#0F172A" : "transparent", aspectRatio: "1/1" }} />
      ))}
    </div>
  );
}

export default function WhatsAppPage() {
  const [conn, setConn] = useState(null);

  const load = () => api.get("/whatsapp/connection").then((r) => setConn(r.data));
  useEffect(() => { load(); }, []);

  const act = async (action) => {
    const { data } = await api.post("/whatsapp/connection", { action });
    setConn(data);
    if (action === "confirm_paired") toast.success("WhatsApp conectado (simulado)");
    if (action === "disconnect") toast.info("Desconectado");
  };

  return (
    <div className="p-8 max-w-4xl" data-testid="whatsapp-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Integração</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Conectar WhatsApp</h1>
        <p className="text-slate-600 mt-2 max-w-2xl">
          Vincule o número de WhatsApp da sua empresa para enviar e receber mensagens automatizadas. <span className="font-semibold text-amber-700">Modo simulado ativo</span> — a conexão real será plugada depois.
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
              </div>
              {conn?.numero && <div className="text-xs text-slate-700 mt-1">Número vinculado: <span className="font-mono">{conn.numero}</span></div>}
            </div>
          </div>
        </div>

        {conn?.status === "desconectado" && (
          <div>
            <p className="text-sm text-slate-700 mb-4">
              Clique em <span className="font-bold">Gerar QR Code</span> para iniciar o pareamento. No WhatsApp do celular, vá em <span className="font-mono">Dispositivos conectados → Conectar dispositivo</span>.
            </p>
            <button data-testid="start-pairing" onClick={() => act("start_pairing")} className="zz-btn">
              <QrCode size={16} weight="bold" /> Gerar QR Code
            </button>
          </div>
        )}

        {conn?.status === "pareando" && conn?.qrcode_atual && (
          <div className="flex gap-8 items-start">
            <FakeQR value={conn.qrcode_atual} />
            <div className="flex-1 space-y-3">
              <div className="text-sm text-slate-700">Escaneie o QR ao lado com o WhatsApp da empresa. Este é um QR simulado para demonstração.</div>
              <div className="text-xs font-mono text-slate-500 break-all border border-slate-200 p-2 bg-slate-50">{conn.qrcode_atual}</div>
              <div className="flex gap-2">
                <button data-testid="confirm-paired" onClick={() => act("confirm_paired")} className="zz-btn">
                  <CheckCircle size={16} weight="bold" /> Simular conexão bem-sucedida
                </button>
                <button onClick={() => act("disconnect")} className="zz-btn zz-btn-secondary">Cancelar</button>
              </div>
            </div>
          </div>
        )}

        {conn?.status === "conectado" && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-green-700">
              <CheckCircle size={20} weight="bold" />
              <span className="font-semibold">Tudo pronto! Seu WhatsApp está recebendo mensagens.</span>
            </div>
            <button data-testid="disconnect-btn" onClick={() => act("disconnect")} className="zz-btn zz-btn-danger">
              <XCircle size={16} weight="bold" /> Desconectar
            </button>
          </div>
        )}
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
