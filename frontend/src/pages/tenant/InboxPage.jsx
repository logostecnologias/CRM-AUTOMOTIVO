import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PaperPlaneRight, User, ChatCircleDots } from "@phosphor-icons/react";

export default function InboxPage() {
  const [sessions, setSessions] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");

  const loadSessions = () => api.get("/sessions", { params: { status: "aguardando_humano" } }).then((r) => setSessions(r.data));
  useEffect(() => { loadSessions(); }, []);

  const openSession = async (id) => {
    setActive(id);
    const { data } = await api.get(`/sessions/${id}/messages`);
    setMessages(data.messages);
  };

  const send = async () => {
    if (!input.trim()) return;
    const { data } = await api.post(`/sessions/${active}/messages`, { content: input });
    setMessages((m) => [...m, data]);
    setInput("");
  };

  return (
    <div className="h-screen flex" data-testid="inbox-page">
      <div className="w-72 border-r border-slate-200 bg-white flex flex-col">
        <div className="p-4 border-b border-slate-200">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Atendimento</div>
          <div className="font-heading text-xl font-black tracking-tighter">Caixa de Entrada</div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessions.length === 0 && (
            <div className="p-6 text-xs text-slate-500 text-center">
              Nenhuma conversa aguardando atendimento humano.
            </div>
          )}
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => openSession(s.id)}
              data-testid={`session-${s.id}`}
              className={`w-full text-left p-3 border-b border-slate-100 flex gap-2 hover:bg-slate-50 ${active === s.id ? "bg-slate-100 border-l-2 border-l-slate-900" : ""}`}
            >
              <div className="w-8 h-8 bg-slate-100 border border-slate-300 flex items-center justify-center">
                <User size={14} weight="bold" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate">Contato {s.contact_id?.slice(0, 6)}</div>
                <div className="text-xs text-slate-500">{new Date(s.updated_at).toLocaleString("pt-BR")}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 flex flex-col bg-[#F0F4F8]">
        {!active ? (
          <div className="flex-1 flex items-center justify-center text-slate-500">
            <div className="text-center">
              <ChatCircleDots size={48} weight="thin" className="mx-auto mb-3" />
              <div>Selecione uma conversa para começar a atender</div>
            </div>
          </div>
        ) : (
          <>
            <div className="p-4 border-b border-slate-200 bg-white font-semibold">Conversa</div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {messages.map((m) => (
                <div key={m.id} className={`flex ${m.direction === "enviada" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[70%] px-3 py-2 text-sm border ${m.direction === "enviada" ? "bg-green-100 border-green-600" : "bg-white border-slate-300"}`}>
                    {m.content}
                  </div>
                </div>
              ))}
            </div>
            <div className="p-3 border-t border-slate-200 bg-white flex gap-2">
              <input value={input} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                className="zz-input" placeholder="Digite uma resposta..." data-testid="inbox-input" />
              <button onClick={send} className="zz-btn" data-testid="inbox-send">
                <PaperPlaneRight size={14} weight="bold" />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
