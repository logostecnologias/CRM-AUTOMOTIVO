import { useMemo, useState } from "react";
import { Table } from "@phosphor-icons/react";
import { layout, LARGURA_VB, MARGEM } from "./geometria";

/**
 * Colunas por dia, uma ou duas séries empilhadas.
 *
 * As cores passaram pelo validador de paleta: separação para daltonismo muito
 * acima do piso e contraste ≥ 3:1 contra a superfície branca. O azul é o mesmo
 * `#2563EB` já usado no resto do produto; o laranja é a variação escura, porque
 * o `#F97316` do sistema **reprova** no contraste contra fundo claro. Ficam em
 * constante para serem trocadas num lugar só.
 *
 * Duas medidas de escalas diferentes (conversas e mensagens) nunca compartilham
 * o mesmo gráfico com dois eixos — são dois gráficos lado a lado. Eixo duplo
 * inventa uma correlação que não está no dado.
 */
const SERIES = {
  1: "#2563EB",
  2: "#EA580C",
};
const GRADE = "#E2E8F0";
const EIXO = "#94A3B8";

function rotuloDia(dia) {
  const [, m, d] = dia.split("-");
  return `${d}/${m}`;
}

export default function SerieDiaria({ titulo, dados, series, altura = 180 }) {
  const [sobre, setSobre] = useState(null);
  const [tabela, setTabela] = useState(false);
  const g = useMemo(() => layout(dados, series, altura), [dados, series, altura]);

  if (dados.length === 0) {
    return (
      <div className="border border-slate-200 bg-white p-4" data-testid={`serie-${titulo}`}>
        <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-2">{titulo}</div>
        <div className="text-xs text-slate-400 py-8 text-center">Sem dados no período.</div>
      </div>
    );
  }

  return (
    <div className="border border-slate-200 bg-white p-4" data-testid={`serie-${titulo}`}>
      <div className="flex items-center justify-between mb-3 gap-3">
        <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">{titulo}</div>
        <div className="flex items-center gap-3">
          {/* Legenda sempre presente com duas séries ou mais: identidade nunca
              pode depender só da cor. */}
          {series.length > 1 && (
            <div className="flex items-center gap-2.5">
              {series.map((s) => (
                <span key={s.chave} className="flex items-center gap-1.5 text-[11px] text-slate-600">
                  <span className="w-2.5 h-2.5 shrink-0" style={{ background: SERIES[s.slot] }} />
                  {s.rotulo}
                </span>
              ))}
            </div>
          )}
          <button onClick={() => setTabela((v) => !v)}
            title={tabela ? "Ver gráfico" : "Ver tabela"}
            className={`p-1 hover:bg-slate-200 ${tabela ? "text-slate-900 bg-slate-100" : "text-slate-500"}`}
            data-testid={`tabela-${titulo}`}>
            <Table size={13} weight="bold" />
          </button>
        </div>
      </div>

      {tabela ? (
        <div className="max-h-[164px] overflow-y-auto border border-slate-200">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50">
              <tr className="border-b border-slate-200">
                <th className="text-left px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-slate-500">Dia</th>
                {series.map((s) => (
                  <th key={s.chave} className="text-right px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-slate-500">
                    {s.rotulo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dados.map((d) => (
                <tr key={d.dia} className="border-b border-slate-100 last:border-b-0">
                  <td className="px-2 py-1 font-mono">{rotuloDia(d.dia)}</td>
                  {series.map((s) => (
                    <td key={s.chave} className="px-2 py-1 text-right font-mono">{d[s.chave] || 0}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${LARGURA_VB} ${altura}`} className="w-full" style={{ height: altura }}
            role="img" aria-label={titulo}>
            {g.ticks.map((t) => (
              <g key={t.valor}>
                {/* Grade fina, sólida e discreta — tracejado só acrescenta ruído. */}
                <line x1={MARGEM.esq} x2={LARGURA_VB} y1={t.y} y2={t.y} stroke={GRADE} strokeWidth="1" />
                <text x={MARGEM.esq - 8} y={t.y + 3.5} textAnchor="end"
                  className="fill-slate-400" style={{ fontSize: 10 }}>
                  {Math.round(t.valor).toLocaleString("pt-BR")}
                </text>
              </g>
            ))}

            {g.colunas.map((c) => (
              <g key={c.dia}
                onMouseEnter={() => setSobre(c)}
                onMouseLeave={() => setSobre(null)}>
                {/* Alvo de mouse do tamanho da faixa, não da barra: coluna fina
                    não pode exigir precisão de mira. */}
                <rect x={c.alvo.x} y={MARGEM.topo} width={c.alvo.largura} height={g.areaA}
                  fill="#0F172A" fillOpacity={sobre?.indice === c.indice ? 0.04 : 0} />
                {c.partes.map((p) => (
                  p.d ? <path key={p.chave} d={p.d} fill={SERIES[p.slot]} /> : null
                ))}
              </g>
            ))}

            <line x1={MARGEM.esq} x2={LARGURA_VB} y1={g.y0} y2={g.y0} stroke={EIXO} strokeWidth="1" />

            {g.colunas.map((c) => (c.indice % g.cadaN === 0 ? (
              <text key={c.dia} x={c.centro} y={altura - 6} textAnchor="middle"
                className="fill-slate-400" style={{ fontSize: 10 }}>
                {rotuloDia(c.dia)}
              </text>
            ) : null))}
          </svg>

          {sobre && (
            <div className="absolute pointer-events-none border border-slate-900 bg-white px-2 py-1 z-10"
              style={{
                left: `${(sobre.centro / LARGURA_VB) * 100}%`,
                top: 0,
                transform: "translate(-50%, -100%)",
              }}
              data-testid="serie-tooltip">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                {rotuloDia(sobre.dia)}
              </div>
              {sobre.partes.map((p) => (
                <div key={p.chave} className="flex items-center gap-1.5 text-xs whitespace-nowrap">
                  <span className="w-2 h-2 shrink-0" style={{ background: SERIES[p.slot] }} />
                  <span className="text-slate-600">{p.rotulo}</span>
                  <span className="font-mono font-bold ml-auto">{p.valor}</span>
                </div>
              ))}
              {sobre.partes.length > 1 && (
                <div className="text-[10px] font-mono text-slate-500 border-t border-slate-200 mt-0.5 pt-0.5">
                  total {sobre.total}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export { SERIES };
