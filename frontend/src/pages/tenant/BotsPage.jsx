import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Plus, PencilSimple, Copy, Trash, Pause, Play, Star } from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";

export default function BotsPage() {
  const [bots, setBots] = useState([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const nav = useNavigate();

  const load = () => api.get("/bots").then((r) => setBots(r.data));
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const { data } = await api.post("/bots", { name });
      setName(""); setCreating(false);
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

  const setDefault = async (id) => {
    await api.patch(`/bots/${id}/default`);
    toast.success("Bot padrão atualizado");
    load();
  };

  const remove = async (id) => {
    if (!(await confirmToast("Excluir este robô?", { confirmLabel: "Excluir" }))) return;
    await api.delete(`/bots/${id}`);
    toast.success("Robô excluído");
    load();
  };

  return (
    <div className="p-8" data-testid="bots-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Automação</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Robôs</h1>
        </div>
        <button data-testid="new-bot-btn" onClick={() => setCreating(true)} className="zz-btn">
          <Plus size={16} weight="bold" /> Criar Robô
        </button>
      </div>

      {creating && (
        <form onSubmit={create} className="mb-6 border border-slate-900 bg-white p-4 flex gap-3 items-end zz-panel-hard">
          <div className="flex-1">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Nome do Robô</label>
            <input autoFocus data-testid="new-bot-name" className="zz-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Robô de Vendas" />
          </div>
          <button type="submit" className="zz-btn" data-testid="new-bot-submit">Criar</button>
          <button type="button" onClick={() => setCreating(false)} className="zz-btn zz-btn-secondary">Cancelar</button>
        </form>
      )}

      {bots.length === 0 ? (
        <div className="border border-dashed border-slate-300 bg-white p-16 text-center">
          <div className="font-heading text-2xl font-black tracking-tighter mb-2">Nenhum robô ainda.</div>
          <div className="text-sm text-slate-600 mb-4">Crie seu primeiro robô para começar a automatizar conversas.</div>
        </div>
      ) : (
        <div className="border border-slate-200 bg-white">
          <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            <div className="col-span-5">Nome</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-3">Criado em</div>
            <div className="col-span-2 text-right">Ações</div>
          </div>
          {bots.map((b) => (
            <div key={b.id} className="grid grid-cols-12 px-4 py-3 border-b border-slate-100 items-center hover:bg-slate-50" data-testid={`bot-row-${b.id}`}>
              <div className="col-span-5 font-semibold text-slate-900 cursor-pointer flex items-center gap-2" onClick={() => nav(`/app/bots/${b.id}/flow/${b.main_flow_id}`)}>
                {b.name}
                {b.is_default && (
                  <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 bg-amber-100 border border-amber-500 text-amber-800" data-testid={`default-badge-${b.id}`}>Padrão</span>
                )}
              </div>
              <div className="col-span-2">
                <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border ${
                  b.status === "ativo" ? "bg-green-50 border-green-500 text-green-700" :
                  b.status === "pausado" ? "bg-amber-50 border-amber-500 text-amber-700" :
                  "bg-slate-50 border-slate-300 text-slate-600"
                }`}>{b.status}</span>
              </div>
              <div className="col-span-3 text-xs text-slate-500 font-mono">{new Date(b.created_at).toLocaleDateString("pt-BR")}</div>
              <div className="col-span-2 flex gap-1 justify-end">
                <button onClick={() => nav(`/app/bots/${b.id}/flow/${b.main_flow_id}`)} className="p-1.5 hover:bg-slate-200" title="Editar" data-testid={`bot-edit-${b.id}`}><PencilSimple size={14} weight="bold" /></button>
                <button onClick={() => setDefault(b.id)} className={`p-1.5 hover:bg-amber-100 ${b.is_default ? "text-amber-600" : "text-slate-400"}`} title="Definir como padrão" data-testid={`bot-default-${b.id}`}>
                  <Star size={14} weight={b.is_default ? "fill" : "bold"} />
                </button>
                <button onClick={() => toggleStatus(b)} className="p-1.5 hover:bg-slate-200" title={b.status === "ativo" ? "Pausar" : "Ativar"}>
                  {b.status === "ativo" ? <Pause size={14} weight="bold" /> : <Play size={14} weight="bold" />}
                </button>
                <button onClick={() => duplicate(b.id)} className="p-1.5 hover:bg-slate-200" title="Duplicar"><Copy size={14} weight="bold" /></button>
                <button onClick={() => remove(b.id)} className="p-1.5 hover:bg-red-100 text-red-600" title="Excluir"><Trash size={14} weight="bold" /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
