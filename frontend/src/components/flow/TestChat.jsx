import { useState, useRef, useEffect } from "react";
import api from "@/lib/api";
import { X, PaperPlaneRight, ArrowClockwise } from "@phosphor-icons/react";

export default function TestChat({ flowId, onClose }) {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  const startSim = async () => {
    setLoading(true);
    setMessages([]);
    try {
      const { data } = await api.post(`/flows/${flowId}/test`, { start: true });
      setSessionId(data.session_id);
      applyOutputs(data.outputs);
    } catch (e) {
      setMessages([{ role: "system", text: "Erro ao iniciar simulação" }]);
    } finally { setLoading(false); }
  };

  useEffect(() => { if (flowId) startSim(); /* eslint-disable-next-line */ }, [flowId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const applyOutputs = (outputs) => {
    const items = outputs.map((o, i) => {
      if (o.type === "text") return { role: "bot", text: o.content };
      if (o.type === "menu") return { role: "bot", text: o.content, options: o.options };
      if (o.type === "media") return { role: "bot", text: `[${o.media_type}] ${o.url}${o.caption ? " — " + o.caption : ""}` };
      if (o.type === "system") return { role: "system", text: o.content };
      if (o.type === "delay") return { role: "system", text: `⏱ Aguardando ${o.seconds}s...` };
      return { role: "system", text: JSON.stringify(o) };
    });
    setMessages((m) => [...m, ...items]);
  };

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg) return;
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setInput("");
    setLoading(true);
    try {
      const { data } = await api.post(`/flows/${flowId}/test`, { session_id: sessionId, message: msg });
      applyOutputs(data.outputs);
      if (data.status === "finalizada") {
        setMessages((m) => [...m, { role: "system", text: "— Conversa encerrada —" }]);
      }
    } catch (e) {
      setMessages((m) => [...m, { role: "system", text: "Erro no motor de fluxo" }]);
    } finally { setLoading(false); }
  };

  return (
    <div className="w-[380px] border-l border-slate-900 bg-white flex flex-col h-full" data-testid="test-chat">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-900 bg-slate-900 text-white">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-300">Simulação</div>
          <div className="font-heading text-lg font-black tracking-tight">Testar Fluxo</div>
        </div>
        <div className="flex gap-2">
          <button data-testid="restart-test" onClick={startSim} className="p-1.5 hover:bg-slate-800" title="Reiniciar">
            <ArrowClockwise size={16} weight="bold" />
          </button>
          <button data-testid="close-test-chat" onClick={onClose} className="p-1.5 hover:bg-slate-800">
            <X size={16} weight="bold" />
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3 bg-[#F0F4F8]">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] px-3 py-2 text-sm border ${
                m.role === "user"
                  ? "bg-green-100 border-green-600 text-slate-900"
                  : m.role === "system"
                  ? "bg-white border-slate-300 text-slate-500 italic text-xs mx-auto"
                  : "bg-white border-slate-900 text-slate-900"
              }`}
            >
              <div className="whitespace-pre-wrap">{m.text}</div>
              {m.options && (
                <div className="mt-2 space-y-1">
                  {m.options.map((o, j) => (
                    <button
                      key={j}
                      onClick={() => send(String(j + 1))}
                      className="block w-full text-left text-xs px-2 py-1 bg-slate-50 border border-slate-400 hover:bg-slate-100"
                      data-testid={`menu-option-${j}`}
                    >
                      {j + 1}. {o}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && <div className="text-xs text-slate-500 text-center">processando...</div>}
      </div>

      <div className="p-3 border-t border-slate-200 flex gap-2">
        <input
          data-testid="test-chat-input"
          className="zz-input" value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Digite uma mensagem..." disabled={loading}
        />
        <button data-testid="test-chat-send" onClick={() => send()} disabled={loading || !input} className="zz-btn">
          <PaperPlaneRight size={14} weight="bold" />
        </button>
      </div>
    </div>
  );
}
