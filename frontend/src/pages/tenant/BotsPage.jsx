import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Plus, PencilSimple, Copy, Trash, Pause, Play } from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import { rotuloGatilho } from "@/components/flow/nodeTypes";

export default function BotsPage() {
  const [bots, setBots] = useState([]);
  const [connections, setConnections] = useState([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const nav = useNavigate();

  const load = () => api.get("/bots").then((r) => setBots(r.data));
  useEffect(() => {
    load();
    api.get("/whatsapp/connections").then((r) => setConnections(r.data)).catch(() => {});
  }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const { data } = await api.post("/bots", { name, connection_id: connectionId || null });
      setName(""); setConnectionId(""); setCreating(false);
      toast.success("Robô criado");
      nav(`/app/bots/${data.id}/flow/${data.main_flow_id}`);
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao criar robô");
    }
  };

  const duplicate = async (id) => {
    try {
      await api.post(`/bots/${id}/duplicate`);
      toast.success("Robô duplicado");
      load();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Erro ao duplicar robô");
    }
  };

  const toggleStatus = async (bot) => {
    const next = bot.status === "ativo" ? "pausado" : "ativo";
    await api.patch(`/bots/${bot.id}`, { status: next });
    load();
  };

  const remove = async (id) => {
    if (!(await confirmToast("Excluir este robô?", { confirmLabel: "Excluir" }))) return;
    await api.delete(`/bots/${id}`);
    toast.success("Robô excluído");
    load();
  };

  return (
    <div className="zz-page" data-testid="bots-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-ink-3 mb-2">Automação</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Robôs</h1>
        </div>
        <button data-testid="new-bot-btn" onClick={() => setCreating(true)} className="zz-btn">
          <Plus size={16} weight="bold" /> Criar Robô
        </button>
      </div>

      {creating && (
        <form onSubmit={create} className="mb-6 border border-line-strong bg-surface p-5 flex gap-3 items-end zz-panel-hard rounded-lg">
          <div className="flex-1">
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Nome do Robô</label>
            <input autoFocus data-testid="new-bot-name" className="zz-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Robô de Vendas" />
          </div>
          <div className="w-56">
            <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Conexão</label>
            <select className="zz-input" data-testid="new-bot-connection" value={connectionId}
              onChange={(e) => setConnectionId(e.target.value)}>
              <option value="">— nenhuma —</option>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select>
          </div>
          <button type="submit" className="zz-btn" data-testid="new-bot-submit">Criar</button>
          <button type="button" onClick={() => setCreating(false)} className="zz-btn zz-btn-secondary">Cancelar</button>
        </form>
      )}

      {bots.length === 0 ? (
        <div className="border border-dashed border-line rounded-xl bg-surface p-16 text-center">
          <div className="font-heading text-2xl font-black tracking-tighter mb-2">Nenhum robô ainda.</div>
          <div className="text-sm text-ink-2 mb-4">Crie seu primeiro robô para começar a automatizar conversas.</div>
        </div>
      ) : (
        <div className="border border-line bg-surface rounded-lg">
          <div className="grid grid-cols-12 px-4 py-2 border-b border-line text-[10px] font-bold uppercase tracking-wider text-ink-3">
            <div className="col-span-4">Nome</div>
            <div className="col-span-2">Gatilho</div>
            <div className="col-span-2">Conexão</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-2 text-right">Ações</div>
          </div>
          {bots.map((b) => (
            <div key={b.id} className="grid grid-cols-12 px-4 py-3 border-b border-line items-center hover:bg-surface-2" data-testid={`bot-row-${b.id}`}>
              <div className="col-span-4 font-semibold text-ink cursor-pointer" onClick={() => nav(`/app/bots/${b.id}/flow/${b.main_flow_id}`)}>
                {b.name}
              </div>
              <div className="col-span-2 text-xs" data-testid={`bot-trigger-${b.id}`}>
                {b.trigger === "no_response"
                  ? <span className="text-ink-3">{rotuloGatilho(b.trigger)}</span>
                  : rotuloGatilho(b.trigger)}
              </div>
              <div className="col-span-2 text-xs" data-testid={`bot-connection-${b.id}`}>
                {b.connection?.nome || <span className="italic text-warning">sem conexão</span>}
              </div>
              <div className="col-span-2">
                <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border rounded-full ${
                  b.status === "ativo" ? "bg-success-soft border-success text-success" :
                  b.status === "pausado" ? "bg-warning-soft border-warning text-warning" :
                  "bg-surface-2 border-line text-ink-2"
                }`}>{b.status}</span>
              </div>
              <div className="col-span-2 flex gap-1 justify-end">
                <button onClick={() => nav(`/app/bots/${b.id}/flow/${b.main_flow_id}`)} className="p-1.5 hover:bg-surface-3" title="Editar" data-testid={`bot-edit-${b.id}`}><PencilSimple size={14} weight="bold" /></button>
                <button onClick={() => toggleStatus(b)} className="p-1.5 hover:bg-surface-3" title={b.status === "ativo" ? "Pausar" : "Ativar"}>
                  {b.status === "ativo" ? <Pause size={14} weight="bold" /> : <Play size={14} weight="bold" />}
                </button>
                <button onClick={() => duplicate(b.id)} className="p-1.5 hover:bg-surface-3" title="Duplicar"><Copy size={14} weight="bold" /></button>
                <button onClick={() => remove(b.id)} className="p-1.5 hover:bg-danger-soft text-danger" title="Excluir"><Trash size={14} weight="bold" /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
