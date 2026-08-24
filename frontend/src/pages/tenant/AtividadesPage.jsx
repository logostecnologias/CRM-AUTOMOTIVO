import { useCallback, useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import {
  Check, Plus, Trash, Warning, CalendarBlank, X, ArrowCounterClockwise, User, Funnel,
} from "@phosphor-icons/react";
import { TIPOS, IconeTipo, quando, emDias } from "@/components/activities/Atividades";

// Os limites de "hoje" e "semana" saem daqui, no fuso de quem está olhando: o
// servidor não sabe em que fuso o navegador está, e calcular lá faria a agenda
// de fim de tarde mostrar as tarefas de amanhã.
function fimDoDia() {
  const d = new Date();
  d.setHours(23, 59, 59, 999);
  return d.toISOString();
}

function fimDaSemana() {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  d.setHours(23, 59, 59, 999);
  return d.toISOString();
}

const ABAS = [
  ["atrasadas", "Atrasadas"],
  ["hoje", "Hoje"],
  ["semana", "Próximos 7 dias"],
  ["todas", "Todas as pendentes"],
  ["concluidas", "Concluídas"],
];

export default function AtividadesPage() {
  const [aba, setAba] = useState("hoje");
  const [itens, setItens] = useState([]);
  const [resumo, setResumo] = useState({ atrasadas: 0, hoje: 0, semana: 0, pendentes: 0 });
  const [usuarios, setUsuarios] = useState([]);
  const [responsavel, setResponsavel] = useState("");
  const [criando, setCriando] = useState(null);
  const [concluindo, setConcluindo] = useState(null);
  const [proxima, setProxima] = useState(null);

  const carregar = useCallback(() => {
    const params = { limit: 200 };
    if (responsavel) params.responsavel_id = responsavel;
    if (aba === "atrasadas") params.atrasadas = true;
    else if (aba === "hoje") params.ate = fimDoDia();
    else if (aba === "semana") params.ate = fimDaSemana();
    else if (aba === "concluidas") params.concluidas = true;
    api.get("/activities", { params }).then((r) => setItens(r.data.items || [])).catch(() => {});
    api.get("/activities/summary", {
      params: { hoje_ate: fimDoDia(), semana_ate: fimDaSemana(),
                responsavel_id: responsavel || undefined },
    }).then((r) => setResumo(r.data)).catch(() => {});
  }, [aba, responsavel]);

  useEffect(() => { carregar(); }, [carregar]);
  useEffect(() => {
    api.get("/users").then((r) => setUsuarios(r.data)).catch(() => {});
  }, []);

  const criar = async (e) => {
    e.preventDefault();
    try {
      await api.post("/activities", {
        titulo: criando.titulo,
        tipo: criando.tipo,
        vence_em: new Date(criando.vence_em).toISOString(),
        responsavel_id: criando.responsavel_id || null,
        contact_id: criando.contato?.id || null,
      });
      setCriando(null);
      toast.success("Atividade criada");
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const concluir = async (id, comProxima) => {
    try {
      const corpo = comProxima
        ? { proxima: { ...proxima, vence_em: new Date(proxima.vence_em).toISOString() } }
        : {};
      const r = await api.post(`/activities/${id}/complete`, corpo);
      setConcluindo(null);
      setProxima(null);
      toast.success(r.data.proxima ? "Concluída e próximo passo agendado" : "Concluída");
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const reabrir = async (id) => {
    await api.post(`/activities/${id}/reopen`);
    carregar();
  };

  const excluir = async (a) => {
    if (!(await confirmToast(`Excluir "${a.titulo}"?`, { confirmLabel: "Excluir" }))) return;
    await api.delete(`/activities/${a.id}`);
    carregar();
  };

  const abrirConclusao = (a) => {
    setConcluindo(a.id);
    setProxima({ titulo: "", tipo: a.tipo, vence_em: emDias(3) });
  };

  return (
    <div className="p-8 max-w-5xl" data-testid="atividades-page">
      <div className="flex items-end justify-between mb-6">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Agenda</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Atividades</h1>
          <p className="text-slate-600 mt-2 text-sm">
            O que precisa acontecer, e com quem. Ao concluir, agende o próximo passo na mesma tela.
          </p>
        </div>
        <div className="flex gap-2">
          <select className="zz-input max-w-[200px]" data-testid="atividade-responsavel-filtro"
            value={responsavel} onChange={(e) => setResponsavel(e.target.value)}>
            <option value="">Todos os responsáveis</option>
            {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
          </select>
          <button onClick={() => setCriando({
            titulo: "", tipo: "ligacao", vence_em: emDias(1), responsavel_id: "", contato: null,
          })} className="zz-btn" data-testid="nova-atividade-btn">
            <Plus size={14} weight="bold" /> Nova atividade
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 mb-6">
        {[["Atrasadas", resumo.atrasadas, "border-red-500 bg-red-50"],
          ["Para hoje", resumo.hoje, "border-amber-500 bg-amber-50"],
          ["Próximos 7 dias", resumo.semana, "border-slate-300 bg-white"],
          ["Total pendente", resumo.pendentes, "border-slate-300 bg-white"]].map(([r, v, cls]) => (
          <div key={r} className={`border px-4 py-3 ${cls}`}>
            <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600">{r}</div>
            <div className="font-heading text-2xl font-black tracking-tighter">{v}</div>
          </div>
        ))}
      </div>

      {criando && (
        <form onSubmit={criar} className="border border-slate-900 bg-white p-4 mb-6 grid grid-cols-4 gap-3 items-end zz-panel-hard"
          data-testid="nova-atividade-form">
          <div className="col-span-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">
              O que precisa ser feito
            </label>
            <input required autoFocus className="zz-input" data-testid="nova-atividade-titulo"
              value={criando.titulo} onChange={(e) => setCriando({ ...criando, titulo: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Tipo</label>
            <select className="zz-input" value={criando.tipo}
              onChange={(e) => setCriando({ ...criando, tipo: e.target.value })}>
              {TIPOS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">Quando</label>
            <input required type="datetime-local" className="zz-input" data-testid="nova-atividade-quando"
              value={criando.vence_em}
              onChange={(e) => setCriando({ ...criando, vence_em: e.target.value })} />
          </div>
          <div className="col-span-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">
              Responsável
            </label>
            <select className="zz-input" value={criando.responsavel_id}
              onChange={(e) => setCriando({ ...criando, responsavel_id: e.target.value })}>
              <option value="">Eu mesmo</option>
              {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
            </select>
          </div>
          <div className="col-span-2 flex gap-2 justify-end">
            <button type="button" onClick={() => setCriando(null)} className="zz-btn zz-btn-secondary">
              Cancelar
            </button>
            <button type="submit" className="zz-btn" data-testid="nova-atividade-submit">Criar</button>
          </div>
        </form>
      )}

      <div className="flex gap-1 mb-4 border-b border-slate-200">
        {ABAS.map(([v, r]) => (
          <button key={v} onClick={() => setAba(v)} data-testid={`aba-${v}`}
            className={`px-3 py-2 text-xs font-bold uppercase tracking-wider border-b-2 -mb-px ${
              aba === v ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}>
            {r}
            {v === "atrasadas" && resumo.atrasadas > 0 && (
              <span className="ml-1.5 text-red-600">{resumo.atrasadas}</span>
            )}
          </button>
        ))}
      </div>

      {itens.length === 0 ? (
        <div className="border border-dashed border-slate-300 bg-white p-16 text-center">
          <CalendarBlank size={28} weight="bold" className="mx-auto mb-3 text-slate-400" />
          <div className="font-heading text-2xl font-black tracking-tighter mb-2">
            {aba === "atrasadas" ? "Nada atrasado." : aba === "concluidas" ? "Nada concluído ainda."
              : "Nenhuma atividade nesta janela."}
          </div>
          <div className="text-sm text-slate-600">
            {aba === "atrasadas" ? "Agenda em dia." : "Crie uma atividade ou mude a janela."}
          </div>
        </div>
      ) : (
        <div className="border border-slate-200 bg-white">
          {itens.map((a) => (
            <div key={a.id} className={`border-b border-slate-100 last:border-b-0 ${
              a.atrasada ? "bg-red-50" : ""
            }`} data-testid={`atividade-linha-${a.id}`}>
              <div className="flex items-start gap-3 px-4 py-3">
                {aba === "concluidas" ? (
                  <Check size={16} weight="bold" className="text-green-700 shrink-0 mt-0.5" />
                ) : (
                  <button onClick={() => abrirConclusao(a)} title="Concluir"
                    data-testid={`linha-concluir-${a.id}`}
                    className="w-5 h-5 border border-slate-400 hover:bg-green-100 hover:border-green-600 shrink-0 mt-0.5" />
                )}
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-semibold ${aba === "concluidas" ? "line-through text-slate-500" : ""}`}>
                    {a.titulo}
                  </div>
                  <div className="flex items-center gap-2 text-[11px] mt-0.5 flex-wrap">
                    <span className="text-slate-500 flex items-center gap-1">
                      <IconeTipo tipo={a.tipo} size={11} />
                      {(TIPOS.find(([v]) => v === a.tipo) || [])[1]}
                    </span>
                    <span className={`font-mono ${a.atrasada ? "text-red-700 font-bold" : "text-slate-500"}`}>
                      {aba === "concluidas"
                        ? `concluída ${quando(a.concluida_em)}`
                        : quando(a.vence_em)}
                      {a.atrasada ? " · atrasada" : ""}
                    </span>
                    {a.contact && (
                      <a href={`/app/contacts?contato=${a.contact.id}`}
                        className="text-slate-700 flex items-center gap-1 hover:underline">
                        <User size={11} weight="bold" /> {a.contact.nome}
                      </a>
                    )}
                    {a.deal && (
                      <a href={`/app/funil?negocio=${a.deal.id}`}
                        className="text-slate-700 flex items-center gap-1 hover:underline">
                        <Funnel size={11} weight="bold" /> {a.deal.titulo}
                      </a>
                    )}
                  </div>
                  {a.descricao && <div className="text-xs text-slate-600 mt-1">{a.descricao}</div>}
                </div>
                {aba === "concluidas" && (
                  <button onClick={() => reabrir(a.id)} title="Reabrir" className="p-1 hover:bg-slate-200">
                    <ArrowCounterClockwise size={13} weight="bold" />
                  </button>
                )}
                <button onClick={() => excluir(a)} className="p-1 hover:bg-red-100 text-red-600 shrink-0">
                  <Trash size={13} weight="bold" />
                </button>
              </div>

              {concluindo === a.id && proxima && (
                <div className="px-4 pb-3 pl-12">
                  <div className="border border-slate-300 bg-slate-50 p-3">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-2">
                      Qual é o próximo passo?
                    </div>
                    <div className="flex gap-2 mb-2">
                      <input autoFocus className="zz-input h-8 py-1 text-sm flex-1"
                        data-testid="proxima-titulo" placeholder="Ligar de novo, enviar contrato…"
                        value={proxima.titulo}
                        onChange={(e) => setProxima({ ...proxima, titulo: e.target.value })} />
                      <select className="zz-input h-8 py-1 text-sm w-28" value={proxima.tipo}
                        onChange={(e) => setProxima({ ...proxima, tipo: e.target.value })}>
                        {TIPOS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
                      </select>
                      <input type="datetime-local" className="zz-input h-8 py-1 text-sm"
                        data-testid="proxima-quando" value={proxima.vence_em}
                        onChange={(e) => setProxima({ ...proxima, vence_em: e.target.value })} />
                    </div>
                    <div className="flex gap-2 items-center">
                      <button onClick={() => concluir(a.id, true)} disabled={!proxima.titulo.trim()}
                        className="zz-btn text-xs py-1 disabled:opacity-40" data-testid="concluir-com-proxima">
                        Concluir e agendar
                      </button>
                      <button onClick={() => concluir(a.id, false)}
                        className="text-[11px] text-slate-600 underline" data-testid="concluir-so">
                        Concluir sem próximo passo
                      </button>
                      <div className="flex-1" />
                      <button onClick={() => { setConcluindo(null); setProxima(null); }}
                        className="p-1 hover:bg-slate-200"><X size={13} weight="bold" /></button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {resumo.atrasadas > 0 && aba !== "atrasadas" && (
        <button onClick={() => setAba("atrasadas")}
          className="mt-4 flex items-center gap-2 text-sm text-red-700 hover:underline">
          <Warning size={14} weight="bold" />
          {resumo.atrasadas} atividade(s) atrasada(s) esperando
        </button>
      )}
    </div>
  );
}
