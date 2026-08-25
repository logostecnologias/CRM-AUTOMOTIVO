import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { NODE_TYPES } from "./nodeTypes";
import { Warning } from "@phosphor-icons/react";

function CustomNode({ id, data, selected, type }) {
  const meta = NODE_TYPES[type] || NODE_TYPES.text;
  const Icon = meta.icon;
  const headerBg = meta.color;
  const headerFg = meta.textColor || "#0F172A";
  const hasTarget = meta.hasTarget !== false;

  // For Menu, outputs are dynamic based on options + invalid
  let outputs = meta.outputs;
  if (type === "menu") {
    const opts = data.options || [];
    outputs = [
      ...opts.map((o, i) => ({ id: o.id || `opt_${i}`, label: o.label || `Opção ${i + 1}` })),
      { id: "invalid", label: "Inválido" },
    ];
  }

  return (
    <div className={`zz-node relative ${selected ? "selected" : ""}`} data-testid={`node-${type}`}>
      {data._warning && (
        <div className="zz-node-warning" title={data._warning}>
          <Warning size={12} weight="bold" style={{ display: "inline" }} />
        </div>
      )}

      {hasTarget && (
        <Handle type="target" position={Position.Left} style={{ top: 24 }} />
      )}

      <div className="zz-node-header" style={{ background: headerBg, color: headerFg }}>
        <Icon size={16} weight="bold" />
        <span className="truncate">{data.label || meta.label}</span>
      </div>

      <div className="zz-node-body">
        {type === "start" && (
          <div className="text-xs text-ink-3">
            Gatilho: <span className="font-mono text-ink">{data.trigger || "first_message"}</span>
          </div>
        )}
        {type === "text" && (
          <div className="text-xs text-ink line-clamp-3 whitespace-pre-wrap">
            {data.text || <span className="text-ink-4 italic">Nenhuma mensagem definida</span>}
          </div>
        )}
        {type === "menu" && (
          <div className="space-y-1">
            <div className="text-xs text-ink line-clamp-2">{data.text || "Pergunta do menu"}</div>
            <div className="text-[10px] font-mono text-ink-3">{(data.options || []).length} opções</div>
          </div>
        )}
        {type === "save_variable" && (
          <div className="text-xs font-mono">
            <span className="text-ink-3">{"{"}</span>
            <span className="text-warning font-bold">{data.variable_name || "?"}</span>
            <span className="text-ink-3">{"}"}</span>
            <span className="text-ink-3"> = </span>
            <span className="text-ink">{data.source === "fixed" ? `"${data.value}"` : "resposta"}</span>
          </div>
        )}
        {type === "condition" && (
          <div className="text-xs font-mono text-ink">
            {data.variable_name || "?"} {data.operator || "=="} "{data.value}"
          </div>
        )}
        {type === "media" && (
          <div className="text-xs text-ink">
            {data.media_type || "image"} · {data.url ? "url definida" : <span className="italic text-ink-4">sem url</span>}
          </div>
        )}
        {type === "delay" && (
          <div className="text-xs">Aguardar <span className="font-mono font-bold">{data.seconds || 1}s</span></div>
        )}
        {type === "webhook" && (
          <div className="text-xs font-mono truncate">
            <span className="text-info font-bold">{data.method || "GET"}</span> {data.url || "https://..."}
          </div>
        )}
        {type === "human_handoff" && (
          <div className="text-xs text-ink">
            Vai para a fila de{" "}
            {data.department_id
              ? <span className="font-mono text-danger">{data.department_name || data.department_id}</span>
              : <span className="italic text-ink-3">departamento padrão da conexão</span>}
          </div>
        )}
        {type === "transfer_bot" && (
          <div className="text-xs text-ink">
            Passa a conversa para: <span className="font-mono text-info">{data.target_bot_name || data.target_bot_id || <span className="italic text-ink-4">selecione um bot</span>}</span>
          </div>
        )}
        {type === "end" && (
          <div className="text-xs text-ink">A sessão do contato é finalizada.</div>
        )}
      </div>

      {/* Output handles */}
      {outputs.length === 1 && (
        <Handle
          type="source"
          position={Position.Right}
          id={outputs[0].id}
          style={{ top: 24 }}
        />
      )}
      {outputs.length > 1 && (
        <div className="border-t border-line bg-surface-2">
          {outputs.map((o, i) => (
            <div
              key={o.id}
              className="relative text-[11px] font-medium px-3 py-1.5 border-b border-line last:border-b-0 text-ink"
              style={{ paddingRight: 20 }}
            >
              {o.label}
              <Handle
                type="source"
                position={Position.Right}
                id={o.id}
                style={{ top: "50%", transform: "translateY(-50%)" }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default memo(CustomNode);
