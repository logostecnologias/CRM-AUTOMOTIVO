import { useCallback, useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import {
  Check, Plus, Trash, Phone, ChatText, Users, ListChecks, ArrowCounterClockwise,
} from "@phosphor-icons/react";

export const TIPOS = [
  ["ligacao", "Ligação", Phone],
  ["mensagem", "Mensagem", ChatText],
  ["reuniao", "Reunião", Users],
  ["tarefa", "Tarefa", ListChecks],
];

export function IconeTipo({ tipo, size = 13 }) {
  const Icone = (TIPOS.find(([v]) => v === tipo) || TIPOS[3])[2];
  return <Icone size={size} weight="bold" />;
}

/** "hoje 14:30", "amanhã 09:00", "12/09 16:00" — o formato que se lê de relance. */
export function quando(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const hoje = new Date();
  const dia = (x) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  const amanha = new Date(hoje);
  amanha.setDate(amanha.getDate() + 1);
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (dia(d) === dia(hoje)) return `hoje ${hora}`;
  if (dia(d) === dia(amanha)) return `amanhã ${hora}`;
  return `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${hora}`;
}

/** Sugestão de data para o campo: agora + N dias, no formato do datetime-local. */
export function emDias(dias, hora = 9) {
  const d = new Date();
  d.setDate(d.getDate() + dias);
  if (dias > 0) d.setHours(hora, 0, 0, 0);
  else d.setHours(d.getHours() + 1, 0, 0, 0);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function FormAtividade({ inicial, onSalvar, onCancelar, rotulo = "Criar" }) {
  const [form, setForm] = useState(inicial);
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); onSalvar(form); }}
      className="border border-line bg-surface-2 p-3 space-y-2 rounded-lg"
      data-testid="atividade-form"
    >
      <input required autoFocus className="zz-input h-8 py-1 text-sm" data-testid="atividade-titulo"
        placeholder="Ligar para confirmar a proposta…"
        value={form.titulo} onChange={(e) => setForm({ ...form, titulo: e.target.value })} />
      <div className="flex gap-2">
        <select className="zz-input h-8 py-1 text-sm w-28" data-testid="atividade-tipo"
          value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
          {TIPOS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <input required type="datetime-local" className="zz-input h-8 py-1 text-sm flex-1"
          data-testid="atividade-vence"
          value={form.vence_em} onChange={(e) => setForm({ ...form, vence_em: e.target.value })} />
      </div>
      <div className="flex gap-1.5">
        {[[1, "amanhã"], [3, "3 dias"], [7, "1 semana"]].map(([d, r]) => (
          <button key={d} type="button" onClick={() => setForm({ ...form, vence_em: emDias(d) })}
            className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 border border-line bg-surface hover:bg-surface-2 rounded-full">
            {r}
          </button>
        ))}
        <div className="flex-1" />
        <button type="submit" className="zz-btn text-xs py-1" data-testid="atividade-submit">{rotulo}</button>
        <button type="button" onClick={onCancelar} className="zz-btn zz-btn-secondary text-xs py-1">
          Cancelar
        </button>
      </div>
    </form>
  );
}

export default function Atividades({ vinculo = {}, onMudou, mostrarVinculos = false }) {
  const [itens, setItens] = useState([]);
  const [concluidas, setConcluidas] = useState([]);
  const [verConcluidas, setVerConcluidas] = useState(false);
  const [criando, setCriando] = useState(false);
  // Conclusão em duas etapas: o passo seguinte é perguntado na hora em que a
  // pessoa está pensando no assunto. "Depois eu agendo" é como se perde a venda.
  const [concluindo, setConcluindo] = useState(null);

  const chave = JSON.stringify(vinculo);
  const carregar = useCallback(() => {
    const params = { ...JSON.parse(chave), limit: 50 };
    api.get("/activities", { params }).then((r) => setItens(r.data.items || [])).catch(() => {});
    api.get("/activities", { params: { ...params, concluidas: true, limit: 20 } })
      .then((r) => setConcluidas(r.data.items || [])).catch(() => {});
  }, [chave]);

  useEffect(() => { carregar(); }, [carregar]);

  const atualizou = () => { carregar(); onMudou?.(); };

  const criar = async (form) => {
    try {
      await api.post("/activities", { ...form, ...vinculo });
      setCriando(false);
      atualizou();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const concluir = async (id, proxima) => {
    try {
      const r = await api.post(`/activities/${id}/complete`, proxima ? { proxima } : {});
      setConcluindo(null);
      toast.success(r.data.proxima ? "Concluída e próximo passo agendado" : "Concluída");
      atualizou();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const reabrir = async (id) => {
    try {
      await api.post(`/activities/${id}/reopen`);
      atualizou();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const excluir = async (a) => {
    if (!(await confirmToast(`Excluir "${a.titulo}"?`, { confirmLabel: "Excluir" }))) return;
    await api.delete(`/activities/${a.id}`);
    atualizou();
  };

  return (
    <div data-testid="atividades">
      <div className="flex items-center justify-between mb-2">
        <div className="flex gap-1.5">
          {!criando && (
            <button onClick={() => setCriando(true)} className="zz-btn text-xs py-1"
              data-testid="nova-atividade">
              <Plus size={12} weight="bold" /> Atividade
            </button>
          )}
          {concluidas.length > 0 && (
            <button onClick={() => setVerConcluidas((v) => !v)}
              className="zz-btn zz-btn-secondary text-xs py-1">
              {verConcluidas ? "Ocultar" : `Concluídas (${concluidas.length})`}
            </button>
          )}
        </div>
      </div>

      {criando && (
        <div className="mb-3">
          <FormAtividade inicial={{ titulo: "", tipo: "ligacao", vence_em: emDias(1) }}
            onSalvar={criar} onCancelar={() => setCriando(false)} />
        </div>
      )}

      {itens.length === 0 && !criando && (
        <div className="text-xs text-ink-4 mb-2">
          Nenhum próximo passo agendado.
        </div>
      )}

      <div className="space-y-1.5">
        {itens.map((a) => (
          <div key={a.id} className={`border rounded-lg px-3 py-2 ${
            a.atrasada ? "border-danger bg-danger-soft" : "border-line bg-surface"
          }`} data-testid={`atividade-${a.id}`}>
            <div className="flex items-start gap-2">
              <button onClick={() => setConcluindo(concluindo === a.id ? null : a.id)}
                title="Concluir" data-testid={`concluir-${a.id}`}
                className="w-5 h-5 border border-line-strong hover:bg-success-soft hover:border-success flex items-center justify-center shrink-0 mt-0.5 rounded-sm">
                {concluindo === a.id && <Check size={12} weight="bold" className="text-success" />}
              </button>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold leading-tight">{a.titulo}</div>
                <div className="flex items-center gap-1.5 text-[11px] mt-0.5">
                  <span className="text-ink-3"><IconeTipo tipo={a.tipo} size={11} /></span>
                  <span className={`font-mono ${a.atrasada ? "text-danger font-bold" : "text-ink-3"}`}>
                    {quando(a.vence_em)}{a.atrasada ? " · atrasada" : ""}
                  </span>
                  {mostrarVinculos && a.contact && (
                    <span className="text-ink-2 truncate">· {a.contact.nome}</span>
                  )}
                  {mostrarVinculos && a.deal && (
                    <span className="text-ink-2 truncate">· {a.deal.titulo}</span>
                  )}
                </div>
                {a.descricao && <div className="text-xs text-ink-2 mt-1">{a.descricao}</div>}
              </div>
              <button onClick={() => excluir(a)} className="p-0.5 hover:bg-danger-soft text-danger shrink-0">
                <Trash size={12} weight="bold" />
              </button>
            </div>

            {concluindo === a.id && (
              <div className="mt-2 pt-2 border-t border-line">
                <div className="text-[10px] font-bold uppercase tracking-wider text-ink-2 mb-1.5">
                  Qual é o próximo passo?
                </div>
                <FormAtividade rotulo="Concluir e agendar"
                  inicial={{ titulo: "", tipo: a.tipo, vence_em: emDias(3) }}
                  onSalvar={(form) => concluir(a.id, form)}
                  onCancelar={() => setConcluindo(null)} />
                <button onClick={() => concluir(a.id, null)}
                  className="text-[11px] text-ink-2 underline mt-1.5"
                  data-testid={`concluir-sem-proxima-${a.id}`}>
                  Concluir sem agendar próximo passo
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {verConcluidas && (
        <div className="mt-3 space-y-1">
          {concluidas.map((a) => (
            <div key={a.id} className="flex items-center gap-2 px-3 py-1.5 border border-line bg-surface-2 rounded-lg"
              data-testid={`concluida-${a.id}`}>
              <Check size={12} weight="bold" className="text-success shrink-0" />
              <span className="text-xs text-ink-3 line-through flex-1 truncate">{a.titulo}</span>
              <span className="text-[10px] font-mono text-ink-4 shrink-0">
                {new Date(a.concluida_em).toLocaleDateString("pt-BR")}
              </span>
              <button onClick={() => reabrir(a.id)} title="Reabrir" className="p-0.5 hover:bg-surface-3">
                <ArrowCounterClockwise size={11} weight="bold" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
