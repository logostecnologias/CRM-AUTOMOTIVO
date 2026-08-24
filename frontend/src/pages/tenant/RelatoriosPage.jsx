import { useCallback, useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { formatBRL } from "@/lib/currency";
import { Warning, Megaphone, Headset, Funnel } from "@phosphor-icons/react";
import SerieDiaria from "@/components/reports/SerieDiaria";
import FunilMetricas from "@/components/deals/FunilMetricas";

const JANELAS = [["7", "7 dias"], ["30", "30 dias"], ["90", "90 dias"], ["365", "12 meses"]];

// Os limites saem daqui, no fuso de quem está olhando — o servidor não sabe em
// que fuso o navegador está.
function desde(dias) {
  const d = new Date();
  d.setDate(d.getDate() - Number(dias));
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function ate() {
  const d = new Date();
  d.setHours(23, 59, 59, 999);
  return d.toISOString();
}

/** Segundos em algo que se lê: "45s", "12 min", "2h 20min". */
function duracao(s) {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return m ? `${h}h ${m}min` : `${h}h`;
}

function Tile({ rotulo, valor, hint, destaque }) {
  return (
    <div className={`border px-4 py-3 ${destaque ? "border-slate-900 bg-white" : "border-slate-300 bg-white"}`}>
      <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">{rotulo}</div>
      <div className="font-heading text-2xl font-black tracking-tighter">{valor}</div>
      {hint && <div className="text-[10px] text-slate-500 mt-0.5">{hint}</div>}
    </div>
  );
}

/** Barra proporcional dentro da linha de uma tabela — magnitude sem virar gráfico. */
function BarraLinha({ valor, maximo, cor = "#2563EB" }) {
  const pct = maximo ? Math.max(2, (valor / maximo) * 100) : 0;
  return (
    <div className="h-1.5 bg-slate-100">
      <div className="h-full" style={{ width: `${pct}%`, background: cor }} />
    </div>
  );
}

function Atendimento({ janela }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [conexoes, setConexoes] = useState([]);
  const [departamentos, setDepartamentos] = useState([]);
  const [conexao, setConexao] = useState("");
  const [departamento, setDepartamento] = useState("");

  useEffect(() => {
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/departments").then((r) => setDepartamentos(r.data)).catch(() => {});
  }, []);

  const carregar = useCallback(() => {
    setDados(null);
    setErro(null);
    api.get("/reports/atendimento", {
      params: {
        de: desde(janela), ate: ate(),
        connection_id: conexao || undefined,
        departamento_id: departamento || undefined,
      },
    }).then((r) => setDados(r.data))
      .catch((ex) => setErro(formatApiErrorDetail(ex.response?.data?.detail)));
  }, [janela, conexao, departamento]);

  useEffect(() => { carregar(); }, [carregar]);

  if (erro) {
    return (
      <div className="border-2 border-amber-400 bg-amber-50 p-4 flex gap-3">
        <Warning size={18} weight="bold" className="text-amber-700 shrink-0 mt-0.5" />
        <div className="text-sm text-slate-800">{erro}</div>
      </div>
    );
  }
  if (!dados) return <div className="text-xs text-slate-500 py-6">Carregando…</div>;

  const { resumo, tempos } = dados;
  const maxAtendente = Math.max(1, ...dados.por_atendente.map((a) => a.assumidas));

  return (
    <div>
      <div className="flex gap-2 mb-4">
        <select className="zz-input max-w-[200px]" data-testid="rel-conexao"
          value={conexao} onChange={(e) => setConexao(e.target.value)}>
          <option value="">Todas as conexões</option>
          {conexoes.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
        </select>
        <select className="zz-input max-w-[200px]" data-testid="rel-departamento"
          value={departamento} onChange={(e) => setDepartamento(e.target.value)}>
          <option value="">Todos os departamentos</option>
          {departamentos.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
        </select>
      </div>

      <div className="grid grid-cols-6 gap-2 mb-4">
        <Tile rotulo="Conversas" valor={resumo.conversas.toLocaleString("pt-BR")} destaque />
        <Tile rotulo="Finalizadas" valor={resumo.finalizadas.toLocaleString("pt-BR")} />
        <Tile rotulo="Em aberto" valor={resumo.em_aberto.toLocaleString("pt-BR")} />
        <Tile rotulo="De campanha" valor={resumo.de_campanha.toLocaleString("pt-BR")} />
        <Tile rotulo="Recebidas" valor={resumo.mensagens_recebidas.toLocaleString("pt-BR")}
          hint="mensagens" />
        <Tile rotulo="Enviadas" valor={resumo.mensagens_enviadas.toLocaleString("pt-BR")}
          hint="mensagens" />
      </div>

      <div className="grid grid-cols-2 gap-2 mb-4">
        <Tile rotulo="Espera na fila" valor={duracao(tempos.espera_media_s)}
          hint={`média · 90% abaixo de ${duracao(tempos.espera_p90_s)} · ${tempos.espera_amostra} conversa(s)`} />
        <Tile rotulo="Duração do atendimento" valor={duracao(tempos.atendimento_medio_s)}
          hint={`média · 90% abaixo de ${duracao(tempos.atendimento_p90_s)} · ${tempos.atendimento_amostra} conversa(s)`} />
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <SerieDiaria titulo="Conversas por dia" dados={dados.por_dia}
          series={[{ chave: "conversas", rotulo: "Conversas", slot: 1 }]} />
        <SerieDiaria titulo="Mensagens por dia" dados={dados.por_dia}
          series={[
            { chave: "recebidas", rotulo: "Recebidas", slot: 1 },
            { chave: "enviadas", rotulo: "Enviadas", slot: 2 },
          ]} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="border border-slate-200 bg-white p-4">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-3">
            Por atendente
          </div>
          {dados.por_atendente.length === 0 ? (
            <div className="text-xs text-slate-400">Nenhuma conversa assumida no período.</div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-500">Atendente</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-500">Assumidas</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-500">Finalizadas</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-500">Tempo médio</th>
                </tr>
              </thead>
              <tbody>
                {dados.por_atendente.map((a) => (
                  <tr key={a.atendente_id} className="border-b border-slate-100 last:border-b-0">
                    <td className="py-1.5 pr-2">
                      <div className="font-semibold truncate">{a.nome}</div>
                      <BarraLinha valor={a.assumidas} maximo={maxAtendente} />
                    </td>
                    <td className="py-1.5 text-right font-mono">{a.assumidas}</td>
                    <td className="py-1.5 text-right font-mono">{a.finalizadas}</td>
                    <td className="py-1.5 text-right font-mono">{duracao(a.atendimento_medio_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="space-y-3">
          <div className="border border-slate-200 bg-white p-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-3">
              Por departamento
            </div>
            {dados.por_departamento.length === 0 ? (
              <div className="text-xs text-slate-400">Nenhuma conversa com departamento.</div>
            ) : dados.por_departamento.map((d) => (
              <div key={d.id} className="mb-2 last:mb-0">
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="truncate">{d.nome}</span>
                  <span className="font-mono">{d.conversas}</span>
                </div>
                <BarraLinha valor={d.conversas}
                  maximo={dados.por_departamento[0].conversas} cor={d.cor || "#2563EB"} />
              </div>
            ))}
          </div>

          <div className="border border-slate-200 bg-white p-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-3">
              Por conexão
            </div>
            {dados.por_conexao.length === 0 ? (
              <div className="text-xs text-slate-400">Nenhuma conversa no período.</div>
            ) : dados.por_conexao.map((c) => (
              <div key={c.id} className="mb-2 last:mb-0">
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="truncate">{c.nome}</span>
                  <span className="font-mono">{c.conversas}</span>
                </div>
                <BarraLinha valor={c.conversas} maximo={dados.por_conexao[0].conversas} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Campanhas({ janela }) {
  const [dados, setDados] = useState(null);

  useEffect(() => {
    setDados(null);
    api.get("/reports/campanhas", { params: { de: desde(janela), ate: ate() } })
      .then((r) => setDados(r.data)).catch(() => setDados(null));
  }, [janela]);

  if (!dados) return <div className="text-xs text-slate-500 py-6">Carregando…</div>;
  const { resumo } = dados;
  const maxValor = Math.max(1, ...dados.itens.map((i) => i.valor));

  return (
    <div>
      <div className="grid grid-cols-5 gap-2 mb-4">
        <Tile rotulo="Disparos entregues" valor={resumo.enviados.toLocaleString("pt-BR")} />
        <Tile rotulo="Falhas" valor={resumo.falhas.toLocaleString("pt-BR")} />
        <Tile rotulo="Respostas" valor={resumo.respostas.toLocaleString("pt-BR")}
          hint={resumo.enviados ? `${Math.round(resumo.respostas / resumo.enviados * 100)}% de quem recebeu` : null} />
        <Tile rotulo="Negócios ganhos" valor={resumo.negocios.toLocaleString("pt-BR")} />
        <Tile rotulo="Receita atribuída" valor={formatBRL(resumo.valor)} destaque
          hint="negócios fechados vindos de campanha" />
      </div>

      <div className="border border-slate-200 bg-white">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-200 text-[9px] font-bold uppercase tracking-wider text-slate-500">
          <div className="col-span-4">Campanha</div>
          <div className="col-span-1 text-right">Entregues</div>
          <div className="col-span-1 text-right">Falhas</div>
          <div className="col-span-1 text-right">Respostas</div>
          <div className="col-span-1 text-right">Taxa</div>
          <div className="col-span-1 text-right">Negócios</div>
          <div className="col-span-3 text-right">Receita</div>
        </div>
        {dados.itens.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-500">
            Nenhuma campanha com disparo ou negócio fechado no período.
          </div>
        )}
        {dados.itens.map((i) => (
          <div key={i.campanha_id} className="grid grid-cols-12 px-4 py-2.5 border-b border-slate-100 last:border-b-0 items-center"
            data-testid={`rel-campanha-${i.campanha_id}`}>
            <div className="col-span-4 pr-3">
              <div className="text-sm font-semibold truncate">{i.nome}</div>
              <BarraLinha valor={i.valor} maximo={maxValor} />
            </div>
            <div className="col-span-1 text-right font-mono text-xs">{i.enviados}</div>
            <div className="col-span-1 text-right font-mono text-xs text-slate-500">{i.falhas || "—"}</div>
            <div className="col-span-1 text-right font-mono text-xs">{i.respostas}</div>
            <div className="col-span-1 text-right font-mono text-xs">
              {i.taxa_resposta != null ? `${i.taxa_resposta}%` : "—"}
            </div>
            <div className="col-span-1 text-right font-mono text-xs">{i.negocios || "—"}</div>
            <div className="col-span-3 text-right font-mono text-sm font-bold">
              {i.valor ? formatBRL(i.valor) : "—"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FunilAba() {
  const [funis, setFunis] = useState([]);
  const [funilId, setFunilId] = useState("");

  useEffect(() => {
    api.get("/pipelines").then((r) => {
      setFunis(r.data);
      setFunilId((a) => a || r.data[0]?.id || "");
    }).catch(() => {});
  }, []);

  if (!funilId) return <div className="text-xs text-slate-500 py-6">Carregando…</div>;
  return (
    <div>
      {funis.length > 1 && (
        <select className="zz-input max-w-[220px] mb-3" value={funilId}
          onChange={(e) => setFunilId(e.target.value)} data-testid="rel-funil">
          {funis.map((f) => <option key={f.id} value={f.id}>{f.nome}</option>)}
        </select>
      )}
      <FunilMetricas pipelineId={funilId} onClose={() => {}} />
    </div>
  );
}

const ABAS = [
  ["atendimento", "Atendimento", Headset],
  ["campanhas", "Campanhas", Megaphone],
  ["funil", "Funil", Funnel],
];

export default function RelatoriosPage() {
  const [aba, setAba] = useState("atendimento");
  const [janela, setJanela] = useState("30");

  return (
    <div className="p-8 max-w-7xl" data-testid="relatorios-page">
      <div className="flex items-end justify-between mb-6">
        <div>
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Números</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Relatórios</h1>
          <p className="text-slate-600 mt-2 text-sm">
            O que a operação produziu no período — atendimento, campanhas e funil.
          </p>
        </div>
        {aba !== "funil" && (
          <div className="flex gap-1">
            {JANELAS.map(([v, r]) => (
              <button key={v} onClick={() => setJanela(v)} data-testid={`janela-${v}`}
                className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border ${
                  janela === v ? "bg-slate-900 text-white border-slate-900" : "bg-white border-slate-300 text-slate-600"
                }`}>
                {r}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-1 mb-4 border-b border-slate-200">
        {ABAS.map(([v, r, Icone]) => (
          <button key={v} onClick={() => setAba(v)} data-testid={`aba-${v}`}
            className={`px-3 py-2 text-xs font-bold uppercase tracking-wider border-b-2 -mb-px flex items-center gap-1.5 ${
              aba === v ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}>
            <Icone size={13} weight="bold" /> {r}
          </button>
        ))}
      </div>

      {aba === "atendimento" && <Atendimento janela={janela} />}
      {aba === "campanhas" && <Campanhas janela={janela} />}
      {aba === "funil" && <FunilAba />}
    </div>
  );
}
