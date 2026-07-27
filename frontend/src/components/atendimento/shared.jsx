import { useState } from "react";
import { Robot, Timer, Headset, CheckCircle } from "@phosphor-icons/react";

export const STATUS = [
  { key: "bot", label: "Bot", icon: Robot, color: "#2563EB" },
  { key: "aguardando", label: "Aguardando", icon: Timer, color: "#F59E0B" },
  { key: "em_atendimento", label: "Em Atendimento", icon: Headset, color: "#10B981" },
  { key: "finalizado", label: "Finalizado", icon: CheckCircle, color: "#475569" },
];

export function SessionCard({ session, active, onClick }) {
  const last = session.last_message;
  return (
    <button
      onClick={onClick}
      data-testid={`session-card-${session.id}`}
      className={`w-full text-left p-2.5 border ${active ? "border-slate-900 shadow-[2px_2px_0_rgba(15,23,42,0.15)]" : "border-slate-200 bg-white hover:border-slate-400"}`}
    >
      <div className="flex items-center justify-between mb-1 gap-1">
        <div className="text-sm font-semibold truncate">{session.contact?.nome || session.contact?.numero_whatsapp || "—"}</div>
        {session.department && (
          <span className="text-[9px] font-bold uppercase tracking-wider px-1 py-0.5 border border-slate-900 text-white shrink-0" style={{ background: session.department.cor }}>
            {session.department.nome.slice(0, 6)}
          </span>
        )}
      </div>
      {session.connection && (
        <div className="mb-1"><ConnectionBadge connection={session.connection} /></div>
      )}
      <div className="text-xs text-slate-500 truncate">{last?.content || "—"}</div>
      <div className="text-[10px] text-slate-400 mt-1 font-mono">{new Date(session.updated_at).toLocaleString("pt-BR")}</div>
      {session.agent && <div className="text-[10px] text-slate-600 mt-0.5">👤 {session.agent.name}</div>}
    </button>
  );
}

const AVATAR_COLORS = ["#25D366", "#128C7E", "#34B7F1", "#F59E0B", "#8B5CF6", "#EC4899", "#EF4444", "#0EA5E9"];

function avatarColor(seed) {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = seed.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function formatListTime(iso) {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export function Avatar({ name, photoUrl, size = 44 }) {
  const [failed, setFailed] = useState(false);
  const initial = (name.trim()[0] || "?").toUpperCase();
  if (photoUrl && !failed) {
    return (
      <img
        src={photoUrl}
        alt={name}
        onError={() => setFailed(true)}
        className="rounded-full shrink-0 object-cover"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className="rounded-full flex items-center justify-center shrink-0 text-white font-bold"
      style={{ width: size, height: size, background: avatarColor(name), fontSize: size * 0.4 }}
    >
      {initial}
    </div>
  );
}

// WhatsApp-style chat list item (rounded avatar, flat divider) — used by the
// Atendimento inbox. The Kanban's SessionCard (boxed) stays untouched.
export function SessionListItem({ session, active, onClick }) {
  const last = session.last_message;
  const name = session.contact?.nome || session.contact?.numero_whatsapp || "—";
  return (
    <button
      onClick={onClick}
      data-testid={`session-card-${session.id}`}
      className={`w-full text-left px-3 py-2.5 flex items-center gap-3 border-b border-slate-100 transition-colors ${active ? "bg-slate-100" : "hover:bg-slate-50"}`}
    >
      <Avatar name={name} photoUrl={session.contact?.foto_url} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <div className="text-sm font-semibold truncate">{name}</div>
          <div className="text-[10px] text-slate-400 shrink-0">{formatListTime(session.updated_at)}</div>
        </div>
        {session.agent && (
          <div className="text-xs font-bold text-slate-700 truncate mt-0.5">{session.agent.name}</div>
        )}
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <div className="text-xs text-slate-500 truncate">{last?.content || "—"}</div>
          {session.unread_count > 0 && (
            <span className="inline-flex items-center justify-center min-w-[1.15rem] h-[1.15rem] px-1 rounded-full bg-[#25D366] text-white text-[10px] font-bold shrink-0">
              {session.unread_count > 99 ? "99+" : session.unread_count}
            </span>
          )}
        </div>
        {session.department && (
          <div className="mt-1">
            <span
              className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 text-white shrink-0"
              style={{ background: session.department.cor }}
            >
              {session.department.nome}
            </span>
          </div>
        )}
      </div>
    </button>
  );
}

export function MessageBubble({ m }) {
  if (m.direction === "sistema" || m.type === "system") {
    return <div className="text-[11px] text-slate-500 italic text-center py-1">— {m.content} —</div>;
  }
  const isOut = m.direction === "enviada";
  return (
    <div className={`flex ${isOut ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] px-3 py-2 text-sm border ${isOut ? "bg-green-100 border-green-600" : "bg-white border-slate-300"}`}>
        {m.meta?.agent_name && (
          <div className="text-xs font-bold text-slate-700 mb-0.5">{m.meta.agent_name}</div>
        )}
        <div className="whitespace-pre-wrap">{m.content}</div>
        <div className="text-[9px] text-slate-500 mt-1 font-mono">{new Date(m.timestamp).toLocaleTimeString("pt-BR")}</div>
      </div>
    </div>
  );
}

export function StatusBadge({ status }) {
  const s = STATUS.find((x) => x.key === status);
  if (!s) return null;
  return (
    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 border border-slate-900 text-white" style={{ background: s.color }}>
      {s.label}
    </span>
  );
}

export function ConnectionBadge({ connection }) {
  return (
    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 border border-slate-300 bg-slate-50 text-slate-700">
      {connection.nome}
    </span>
  );
}
