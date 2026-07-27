import { useEffect, useState, useRef } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PaperPlaneRight, Hand, CheckCircle, X } from "@phosphor-icons/react";
import { toast } from "sonner";
import { STATUS, SessionListItem, MessageBubble, Avatar } from "@/components/atendimento/shared";

export default function InboxPage() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [stage, setStage] = useState("aguardando");
  const [activeId, setActiveId] = useState(null);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const chatEnd = useRef(null);

  const loadSessions = () => api.get("/atendimento/sessions").then((r) => setSessions(r.data));
  const loadActive = async (id) => {
    if (!id) return;
    const { data } = await api.get(`/atendimento/sessions/${id}`);
    setActive(data.session);
    setMessages(data.messages);
  };

  useEffect(() => {
    loadSessions();
  }, []);
  useEffect(() => {
    const t = setInterval(() => {
      loadSessions();
      if (activeId) loadActive(activeId);
    }, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [activeId]);
  useEffect(() => {
    if (activeId) loadActive(activeId);
    else { setActive(null); setMessages([]); }
    // eslint-disable-next-line
  }, [activeId]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length]);

  const counts = STATUS.reduce((acc, s) => {
    acc[s.key] = sessions.filter((x) => x.status_atendimento === s.key).length;
    return acc;
  }, {});
  const visible = sessions.filter((s) => s.status_atendimento === stage);

  const assume = async () => {
    await api.post(`/atendimento/sessions/${activeId}/assume`);
    toast.success("Conversa assumida");
    setStage("em_atendimento");
    await loadActive(activeId); loadSessions();
  };
  const finalize = async () => {
    await api.post(`/atendimento/sessions/${activeId}/finalize`);
    toast.success("Atendimento finalizado");
    await loadActive(activeId); loadSessions();
  };
  const send = async () => {
    if (!input.trim()) return;
    try {
      await api.post(`/atendimento/sessions/${activeId}/send`, { content: input });
      setInput("");
      await loadActive(activeId);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Falha ao enviar");
    }
  };

  const canSend = active?.status_atendimento === "em_atendimento" &&
    (user?.role !== "agent" || active?.atendente_id === user?.id);

  return (
    <div className="h-screen flex flex-col" data-testid="inbox-page">
      <div className="border-b border-slate-900 bg-white px-6 py-4">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Central</div>
        <h1 className="font-heading text-2xl font-black tracking-tighter mb-4">Atendimento</h1>
        <div className="flex items-center gap-2 flex-wrap">
          {STATUS.map((s) => {
            const Icon = s.icon;
            const isActive = stage === s.key;
            return (
              <button
                key={s.key}
                onClick={() => { setStage(s.key); setActiveId(null); }}
                data-testid={`stage-btn-${s.key}`}
                className="flex items-center gap-2 px-3 py-2 border font-bold text-xs uppercase tracking-wider transition-colors"
                style={isActive
                  ? { background: s.color, borderColor: s.color, color: "#fff" }
                  : { background: "#fff", borderColor: "#cbd5e1", color: "#0F172A" }}
              >
                <Icon size={14} weight="bold" />
                {s.label}
                <span
                  className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-[10px] font-mono border"
                  style={isActive ? { borderColor: "#fff" } : { borderColor: "#cbd5e1" }}
                >
                  {counts[s.key] || 0}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="w-80 border-r border-slate-200 bg-white flex flex-col">
          <div className="flex-1 overflow-y-auto">
            {visible.length === 0 && (
              <div className="text-xs text-slate-400 text-center pt-6">Nenhuma conversa aqui.</div>
            )}
            {visible.map((s) => (
              <SessionListItem key={s.id} session={s} active={activeId === s.id} onClick={() => setActiveId(s.id)} />
            ))}
          </div>
        </div>

        {activeId && active ? (
          <div className="flex-1 bg-white flex flex-col" data-testid="chat-panel">
            <div className="p-3 border-b border-slate-900 flex items-start justify-between gap-3">
              <div className="flex items-start gap-3 min-w-0">
                <Avatar name={active.contact?.nome || active.contact?.numero_whatsapp || "—"} photoUrl={active.contact?.foto_url} size={40} />
                <div className="min-w-0">
                  <div className="font-heading text-lg font-black tracking-tight truncate">{active.contact?.nome || "—"}</div>
                  <div className="text-xs font-mono text-slate-500 truncate">{active.contact?.numero_whatsapp}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {["aguardando"].includes(active.status_atendimento) && (
                  <button onClick={assume} className="zz-btn text-xs" data-testid="assume-btn">
                    <Hand size={12} weight="bold" /> Assumir
                  </button>
                )}
                {active.status_atendimento === "em_atendimento" && (
                  <button onClick={finalize} className="zz-btn zz-btn-secondary text-xs" data-testid="finalize-btn">
                    <CheckCircle size={12} weight="bold" /> Finalizar
                  </button>
                )}
                <button onClick={() => setActiveId(null)} className="p-1.5 hover:bg-slate-100" data-testid="close-chat"><X size={16} weight="bold" /></button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-2 bg-[#F0F4F8]">
              {messages.map((m) => (
                <MessageBubble key={m.id} m={m} />
              ))}
              <div ref={chatEnd} />
            </div>

            <div className="p-2 border-t border-slate-200 flex gap-2">
              <input value={input} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && canSend && send()}
                className="zz-input"
                placeholder={canSend ? "Digite uma mensagem..." : "Assuma a conversa para responder"}
                disabled={!canSend} data-testid="chat-input" />
              <button onClick={send} disabled={!canSend || !input.trim()} className="zz-btn" data-testid="chat-send">
                <PaperPlaneRight size={14} weight="bold" />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-slate-500 bg-white">
            <div className="text-center">
              <div>Selecione uma conversa para começar a atender</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
