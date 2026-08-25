import { useEffect, useState } from "react";
import api from "@/lib/api";
import { formatBRL } from "@/lib/currency";
import { X, TrendUp } from "@phosphor-icons/react";

const JANELAS = [
  ["30", "Últimos 30 dias"],
  ["90", "Últimos 90 dias"],
  ["365", "Últimos 12 meses"],
  ["", "Desde sempre"],
];

function desdeIso(dias) {
  if (!dias) return undefined;
  const d = new Date();
  d.setDate(d.getDate() - Number(dias));
  return d.toISOString();
}

function Caixa({ rotulo, valor, hint }) {
  return (
    <div className="border border-line bg-surface px-4 py-3 rounded-lg">
      <div className="text-[9px] font-bold uppercase tracking-wider text-ink-3">{rotulo}</div>
      <div className="font-heading text-2xl font-black tracking-tighter">{valor}</div>
      {hint && <div className="text-[10px] text-ink-3 mt-0.5">{hint}</div>}
    </div>
  );
}

export default function FunilMetricas({ pipelineId, onClose }) {
  const [dados, setDados] = useState(null);
  const [janela, setJanela] = useState("90");

  useEffect(() => {
    setDados(null);
    api.get("/deals/metrics", { params: { pipeline_id: pipelineId, desde: desdeIso(janela) } })
      .then((r) => setDados(r.data)).catch(() => setDados(null));
  }, [pipelineId, janela]);

  return (
    <div className="border border-line-strong bg-surface-2 p-6 mb-4 zz-panel-hard rounded-lg" data-testid="funil-metricas">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-2">
          <TrendUp size={18} weight="bold" />
          <div className="font-heading text-xl font-black tracking-tighter">Desempenho do funil</div>
        </div>
        <div className="flex gap-2 items-center">
          <select className="zz-input h-8 py-1 text-xs" data-testid="metricas-janela"
            value={janela} onChange={(e) => setJanela(e.target.value)}>
            {JANELAS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
          </select>
          {onClose && (
            <button onClick={onClose} className="p-1.5 hover:bg-surface-3">
              <X size={15} weight="bold" />
            </button>
          )}
        </div>
      </div>

      {!dados ? (
        <div className="text-xs text-ink-3 py-4">Carregando…</div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2 mb-4">
            <Caixa rotulo="Em aberto" valor={formatBRL(dados.resumo.aberto.valor)}
              hint={`${dados.resumo.aberto.n} negócio(s)`} />
            <Caixa rotulo="Ganho na janela" valor={formatBRL(dados.janela.ganho.valor)}
              hint={`${dados.janela.ganho.n} fechado(s)`} />
            <Caixa rotulo="Conversão"
              valor={dados.conversao != null ? `${dados.conversao}%` : "—"}
              hint="sobre negócios decididos" />
            <Caixa rotulo="Ticket médio"
              valor={dados.ticket_medio != null ? formatBRL(dados.ticket_medio) : "—"} />
            <Caixa rotulo="Ciclo médio"
              valor={dados.ciclo_medio_dias != null ? `${dados.ciclo_medio_dias}d` : "—"}
              hint="da criação ao ganho" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-2">
                Retorno por campanha
              </div>
              {dados.por_campanha.length === 0 ? (
                <div className="text-xs text-ink-3 border border-dashed border-line rounded-xl bg-surface p-3">
                  Nenhum negócio ganho veio de campanha nesta janela.
                </div>
              ) : (
                <div className="border border-line bg-surface rounded-lg">
                  {dados.por_campanha.map((c) => (
                    <div key={c.campanha_id} className="flex items-center gap-2 px-3 py-2 border-b border-line last:border-b-0">
                      <span className="text-sm font-semibold flex-1 truncate">{c.nome}</span>
                      <span className="text-[10px] font-mono text-ink-3">{c.n} ganho(s)</span>
                      <span className="text-sm font-mono font-bold">{formatBRL(c.valor)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-2">
                Por que perdemos
              </div>
              {dados.motivos_perda.length === 0 ? (
                <div className="text-xs text-ink-3 border border-dashed border-line rounded-xl bg-surface p-3">
                  Nenhuma perda registrada nesta janela.
                </div>
              ) : (
                <div className="border border-line bg-surface rounded-lg">
                  {dados.motivos_perda.map((m) => (
                    <div key={m.motivo} className="flex items-center gap-2 px-3 py-2 border-b border-line last:border-b-0">
                      <span className="text-sm flex-1 truncate">{m.motivo}</span>
                      <span className="text-[10px] font-mono text-ink-3">{m.n}×</span>
                      <span className="text-sm font-mono text-ink-2">{formatBRL(m.valor)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
