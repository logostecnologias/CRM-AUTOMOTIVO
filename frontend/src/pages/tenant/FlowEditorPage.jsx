import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ReactFlow, ReactFlowProvider, addEdge, applyEdgeChanges, applyNodeChanges,
  Background, Controls, MiniMap, useReactFlow, MarkerType,
} from "@xyflow/react";
import api from "@/lib/api";
import CustomNode from "@/components/flow/CustomNode";
import NodePalette from "@/components/flow/NodePalette";
import NodeConfigPanel from "@/components/flow/NodeConfigPanel";
import TestChat from "@/components/flow/TestChat";
import { NODE_TYPES } from "@/components/flow/nodeTypes";
import { ArrowLeft, FloppyDisk, Play, Rocket, CheckCircle } from "@phosphor-icons/react";
import { toast, Toaster } from "sonner";

function EditorInner({ flow, reload }) {
  const rf = useReactFlow();
  const nav = useNavigate();
  const wrapperRef = useRef(null);
  const [nodes, setNodes] = useState(flow.nodes || []);
  const [edges, setEdges] = useState(flow.edges || []);
  const [selectedId, setSelectedId] = useState(null);
  const [showTest, setShowTest] = useState(false);
  const [saving, setSaving] = useState(false);

  const nodeTypes = useMemo(() => {
    const map = {};
    Object.keys(NODE_TYPES).forEach((k) => { map[k] = CustomNode; });
    return map;
  }, []);

  const onNodesChange = useCallback((changes) => setNodes((n) => applyNodeChanges(changes, n)), []);
  const onEdgesChange = useCallback((changes) => setEdges((e) => applyEdgeChanges(changes, e)), []);
  const onConnect = useCallback((c) => setEdges((es) => addEdge({ ...c, markerEnd: { type: MarkerType.ArrowClosed } }, es)), []);
  const onSelectionChange = useCallback((sel) => {
    setSelectedId(sel.nodes?.[0]?.id || null);
  }, []);

  const onDrop = useCallback((event) => {
    event.preventDefault();
    const type = event.dataTransfer.getData("application/reactflow");
    if (!type) return;
    const bounds = wrapperRef.current.getBoundingClientRect();
    const position = rf.screenToFlowPosition({ x: event.clientX - bounds.left, y: event.clientY - bounds.top });
    const id = `${type}_${Date.now()}`;
    const defaultData = JSON.parse(JSON.stringify(NODE_TYPES[type].default));
    setNodes((nds) => nds.concat({ id, type, position, data: defaultData }));
  }, [rf]);

  const onDragOver = useCallback((e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }, []);

  const updateNodeData = (id, newData) => {
    setNodes((nds) => nds.map((n) => (n.id === id ? { ...n, data: newData } : n)));
  };

  const deleteNode = (id) => {
    setNodes((nds) => nds.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSelectedId(null);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/flows/${flow.id}`, { nodes, edges });
      toast.success("Fluxo salvo com sucesso");
    } catch (e) {
      toast.error("Erro ao salvar");
    } finally { setSaving(false); }
  };

  const publish = async () => {
    try {
      await api.put(`/flows/${flow.id}`, { nodes, edges });
      await api.post(`/flows/${flow.id}/publish`);
      toast.success("Fluxo publicado! O bot está ativo.");
      reload?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao publicar");
    }
  };

  const openTest = async () => {
    await api.put(`/flows/${flow.id}`, { nodes, edges });
    setShowTest(true);
  };

  const selectedNode = nodes.find((n) => n.id === selectedId);

  return (
    <div className="h-screen flex flex-col" data-testid="flow-editor">
      <div className="h-14 border-b border-slate-900 bg-white flex items-center justify-between px-4">
        <div className="flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => nav("/app/bots")} className="p-1.5 hover:bg-slate-100">
            <ArrowLeft size={18} weight="bold" />
          </button>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Editor de Fluxo</div>
            <div className="font-heading font-black text-lg tracking-tight">{flow.name}</div>
          </div>
          {flow.published_at && (
            <div className="flex items-center gap-1 text-xs text-green-700 bg-green-50 border border-green-500 px-2 py-1">
              <CheckCircle size={12} weight="bold" /> Publicado v{flow.version}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button data-testid="test-flow-btn" onClick={openTest} className="zz-btn zz-btn-secondary">
            <Play size={14} weight="bold" /> Testar
          </button>
          <button data-testid="save-flow-btn" onClick={save} disabled={saving} className="zz-btn zz-btn-secondary">
            <FloppyDisk size={14} weight="bold" /> {saving ? "Salvando..." : "Salvar"}
          </button>
          <button data-testid="publish-flow-btn" onClick={publish} className="zz-btn">
            <Rocket size={14} weight="bold" /> Publicar
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="w-56 border-r border-slate-900 bg-white flex flex-col">
          <NodePalette />
        </div>

        <div ref={wrapperRef} className="flex-1 relative" onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onConnect={onConnect} onSelectionChange={onSelectionChange}
            nodeTypes={nodeTypes} fitView snapToGrid snapGrid={[16, 16]}
            defaultEdgeOptions={{ markerEnd: { type: MarkerType.ArrowClosed } }}
          >
            <Background gap={16} size={1.2} color="#cbd5e1" />
            <Controls />
            <MiniMap zoomable pannable maskColor="rgba(15,23,42,0.05)" />
          </ReactFlow>
        </div>

        {selectedNode && (
          <NodeConfigPanel
            node={selectedNode}
            onChange={updateNodeData}
            onDelete={deleteNode}
            onClose={() => setSelectedId(null)}
          />
        )}

        {showTest && (
          <TestChat flowId={flow.id} onClose={() => setShowTest(false)} />
        )}
      </div>
      <Toaster position="bottom-right" />
    </div>
  );
}

export default function FlowEditorPage() {
  const { flowId } = useParams();
  const [flow, setFlow] = useState(null);
  const [err, setErr] = useState("");

  const load = () => api.get(`/flows/${flowId}`).then((r) => setFlow(r.data)).catch((e) => setErr(e.response?.data?.detail || "Erro"));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [flowId]);

  if (err) return <div className="p-8 text-red-600">{err}</div>;
  if (!flow) return <div className="p-8 text-slate-500">Carregando fluxo...</div>;

  return (
    <ReactFlowProvider>
      <EditorInner flow={flow} reload={load} />
    </ReactFlowProvider>
  );
}
