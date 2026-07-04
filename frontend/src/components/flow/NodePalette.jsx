import { NODE_TYPES, NODE_ORDER } from "./nodeTypes";

export default function NodePalette({ onDragStart }) {
  const onDragStartInternal = (event, nodeType) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
    onDragStart?.(nodeType);
  };

  return (
    <div className="p-3 space-y-1 overflow-y-auto flex-1" data-testid="node-palette">
      <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-2 px-1">
        Blocos disponíveis
      </div>
      {NODE_ORDER.filter((t) => t !== "start").map((type) => {
        const meta = NODE_TYPES[type];
        const Icon = meta.icon;
        return (
          <div
            key={type}
            draggable
            onDragStart={(e) => onDragStartInternal(e, type)}
            data-testid={`palette-${type}`}
            className="flex items-center gap-2 p-2 border border-slate-200 bg-white cursor-grab hover:border-slate-900 active:cursor-grabbing transition-colors"
          >
            <div
              className="w-7 h-7 flex items-center justify-center border border-slate-900"
              style={{ background: meta.color, color: meta.textColor || "#0F172A" }}
            >
              <Icon size={14} weight="bold" />
            </div>
            <div className="text-xs font-semibold text-slate-800">{meta.label}</div>
          </div>
        );
      })}
    </div>
  );
}
