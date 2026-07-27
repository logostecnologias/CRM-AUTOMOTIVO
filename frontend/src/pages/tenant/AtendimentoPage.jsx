import { useEffect, useState, useRef } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PaperPlaneRight, Hand, CheckCircle, X } from "@phosphor-icons/react";
import { toast } from "sonner";
import { STATUS, SessionCard, MessageBubble, StatusBadge, ConnectionBadge } from "@/components/atendimento/shared";

export default function AtendimentoPage() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [depts, setDepts] = useState([]);
  const [connections, setConnections] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [deptFilter, setDeptFilter] = useState("");
  const [connFilter, setConnFilter] = useState("");
  const chatEnd = useRef(null);

  const loadSessions = () => {
    const params = {};
    if (deptFilter) params.department_id = deptFilter;
    if (connFilter) params.connection_id = connFilter;
    return api.get("/atendimento/sessions", { params }).then((r) => setSessions(r.data));
  };
  const loadActive = async (id) => {
    if (!id) return;
    const { data } = await api.get(`/atendimento/sessions/${id}`);
    setActive(data.session);
    setMessages(data.messages);
  };

  useEffect(() => {
    loadSessions();
    api.get("/departments").then((r) => setDepts(r.data));
    api.get("/whatsapp/connections").then((r) => setConnections(r.data)).catch(() => {});
  }, []);
  useEffect(() => { loadSessions(); /* eslint-disable-next-line */ }, [deptFilter, connFilter]);
  useEffect(() => {
    const t = setInterval(() => {
      loadSessions();
      if (activeId) loadActive(activeId);
    }, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [activeId, deptFilter, connFilter]);
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

  const assume = async () => {
    await api.post(`/atendimento/sessions/${activeId}/assume`);
    toast.success("Conversa assumida");
    await loadActive(activeId); loadSessions();
  };
  const finalize = async () => {
    await api.post(`/atendimento/sessions/${activeId}/finalize`);
    toast.success("Atendimento finalizado");
    await loadActive(activeId); loadSessions();
  };
  const reassign = async (deptId) => {
    await api.patch(`/atendimento/sessions/${activeId}/department`, { department_id: deptId || null });
    toast.success("Departamento reatribuído");
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
    <div className="h-screen flex flex-col" data-testid="atendimento-page">
      <div className="border-b border-slate-900 bg-white px-6 py-4 flex items-center justify-between">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500">Central</div>
          <h1 className="font-heading text-2xl font-black tracking-tighter">CRM</h1>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Conexão:</label>
            <select data-testid="connection-filter" className="zz-input" style={{ width: "auto" }} value={connFilter} onChange={(e) => setConnFilter(e.target.value)}>
              <option value="">Todas</option>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Depto:</label>
            <select data-testid="dept-filter" className="zz-input" style={{ width: "auto" }} value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)}>
              <option value="">Todos</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Kanban */}
        <div className="flex-1 grid grid-cols-4 gap-0 overflow-hidden">
          {STATUS.map((col) => {
            const Icon = col.icon;
            const list = sessions.filter((s) => s.status_atendimento === col.key);
            return (
              <div key={col.key} className="border-r border-slate-200 flex flex-col min-w-0 bg-[#F8F9FA]" data-testid={`column-${col.key}`}>
                <div className="px-3 py-2.5 border-b border-slate-200 flex items-center justify-between bg-white">
                  <div className="flex items-center gap-2">
                    <div className="w-5 h-5 flex items-center justify-center border border-slate-900 text-white" style={{ background: col.color }}>
                      <Icon size={12} weight="bold" />
                    </div>
                    <div className="text-xs font-bold uppercase tracking-wider">{col.label}</div>
                  </div>
                  <div className="text-xs font-mono font-bold" data-testid={`count-${col.key}`}>{counts[col.key] || 0}</div>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                  {list.length === 0 && <div className="text-xs text-slate-400 text-center pt-4">Vazio</div>}
                  {list.map((s) => (
                    <SessionCard key={s.id} session={s} active={activeId === s.id} onClick={() => setActiveId(s.id)} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {/* Right chat pane */}
        {activeId && active && (
          <div className="w-[420px] border-l border-slate-900 bg-white flex flex-col" data-testid="chat-panel">
            <div className="p-3 border-b border-slate-900 flex items-start justify-between">
              <div className="min-w-0">
                <div className="font-heading text-lg font-black tracking-tight truncate">{active.contact?.nome || "—"}</div>
                <div className="text-xs font-mono text-slate-500 truncate">{active.contact?.numero_whatsapp}</div>
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  <StatusBadge status={active.status_atendimento} />
                  {active.connection && <ConnectionBadge connection={active.connection} />}
                  {active.department && (
                    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 border border-slate-900 text-white" style={{ background: active.department.cor }}>
                      {active.department.nome}
                    </span>
                  )}
                  {active.agent && (
                    <span className="text-[10px] text-slate-500">👤 {active.agent.name}</span>
                  )}
                </div>
              </div>
              <button onClick={() => setActiveId(null)} className="p-1.5 hover:bg-slate-100" data-testid="close-chat"><X size={16} weight="bold" /></button>
            </div>

            <div className="px-3 py-2 border-b border-slate-200 flex items-center gap-2">
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Depto:</label>
              <select className="zz-input" style={{ padding: "0.3rem 0.5rem" }} value={active.departamento_id || ""} onChange={(e) => reassign(e.target.value)} data-testid="reassign-dept">
                <option value="">— nenhum —</option>
                {depts.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
              </select>
              <div className="flex-1" />
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
        )}
      </div>
    </div>
  );
}
