import { useCallback, useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { formatBRL } from "@/lib/currency";
import { Warning, Megaphone, Headset, Funnel, CalendarBlank } from "@phosphor-icons/react";
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
    <div className={`border rounded-lg px-4 py-3 ${destaque ? "border-info bg-surface" : "border-line bg-surface"}`}>
      <div className="text-[9px] font-bold uppercase tracking-wider text-ink-3">{rotulo}</div>
      <div className="font-heading text-2xl font-black tracking-tighter">{valor}</div>
      {hint && <div className="text-[10px] text-ink-3 mt-0.5">{hint}</div>}
    </div>
  );
}

/** Barra proporcional dentro da linha de uma tabela — magnitude sem virar gráfico. */
function BarraLinha({ valor, maximo, cor = "#2563EB" }) {
  const pct = maximo ? Math.max(2, (valor / maximo) * 100) : 0;
  return (
    <div className="h-1.5 bg-surface-2">
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
      <div className="border border-warning bg-warning-soft p-4 flex gap-3 rounded-lg">
        <Warning size={18} weight="bold" className="text-warning shrink-0 mt-0.5" />
        <div className="text-sm text-ink">{erro}</div>
      </div>
    );
  }
  if (!dados) return <div className="text-xs text-ink-3 py-6">Carregando…</div>;

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

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
        <Tile rotulo="Conversas" valor={resumo.conversas.toLocaleString("pt-BR")} destaque />
        <Tile rotulo="Finalizadas" valor={resumo.finalizadas.toLocaleString("pt-BR")} />
        <Tile rotulo="Em aberto" valor={resumo.em_aberto.toLocaleString("pt-BR")} />
        <Tile rotulo="De campanha" valor={resumo.de_campanha.toLocaleString("pt-BR")} />
        <Tile rotulo="Recebidas" valor={resumo.mensagens_recebidas.toLocaleString("pt-BR")}
          hint="mensagens" />
        <Tile rotulo="Enviadas" valor={resumo.mensagens_enviadas.toLocaleString("pt-BR")}
          hint="mensagens" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
        <Tile rotulo="Espera na fila" valor={duracao(tempos.espera_media_s)}
          hint={`média · 90% abaixo de ${duracao(tempos.espera_p90_s)} · ${tempos.espera_amostra} conversa(s)`} />
        <Tile rotulo="Duração do atendimento" valor={duracao(tempos.atendimento_medio_s)}
          hint={`média · 90% abaixo de ${duracao(tempos.atendimento_p90_s)} · ${tempos.atendimento_amostra} conversa(s)`} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
        <SerieDiaria titulo="Conversas por dia" dados={dados.por_dia}
          series={[{ chave: "conversas", rotulo: "Conversas", slot: 1 }]} />
        <SerieDiaria titulo="Mensagens por dia" dados={dados.por_dia}
          series={[
            { chave: "recebidas", rotulo: "Recebidas", slot: 1 },
            { chave: "enviadas", rotulo: "Enviadas", slot: 2 },
          ]} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="border border-line bg-surface p-5 rounded-lg">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-3">
            Por atendente
          </div>
          {dados.por_atendente.length === 0 ? (
            <div className="text-xs text-ink-4">Nenhuma conversa assumida no período.</div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line">
                  <th className="text-left pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Atendente</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Assumidas</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Finalizadas</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Tempo médio</th>
                </tr>
              </thead>
              <tbody>
                {dados.por_atendente.map((a) => (
                  <tr key={a.atendente_id} className="border-b border-line last:border-b-0">
                    <td className="py-2.5.5 pr-2">
                      <div className="font-semibold truncate">{a.nome}</div>
                      <BarraLinha valor={a.assumidas} maximo={maxAtendente} />
                    </td>
                    <td className="py-2.5.5 text-right font-mono">{a.assumidas}</td>
                    <td className="py-2.5.5 text-right font-mono">{a.finalizadas}</td>
                    <td className="py-2.5.5 text-right font-mono">{duracao(a.atendimento_medio_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="space-y-3">
          <div className="border border-line bg-surface p-5 rounded-lg">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-3">
              Por departamento
            </div>
            {dados.por_departamento.length === 0 ? (
              <div className="text-xs text-ink-4">Nenhuma conversa com departamento.</div>
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

          <div className="border border-line bg-surface p-5 rounded-lg">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-3">
              Por conexão
            </div>
            {dados.por_conexao.length === 0 ? (
              <div className="text-xs text-ink-4">Nenhuma conversa no período.</div>
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

  if (!dados) return <div className="text-xs text-ink-3 py-6">Carregando…</div>;
  const { resumo } = dados;
  const maxValor = Math.max(1, ...dados.itens.map((i) => i.valor));

  return (
    <div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2 mb-4">
        <Tile rotulo="Disparos entregues" valor={resumo.enviados.toLocaleString("pt-BR")} />
        <Tile rotulo="Falhas" valor={resumo.falhas.toLocaleString("pt-BR")} />
        <Tile rotulo="Respostas" valor={resumo.respostas.toLocaleString("pt-BR")}
          hint={resumo.enviados ? `${Math.round(resumo.respostas / resumo.enviados * 100)}% de quem recebeu` : null} />
        <Tile rotulo="Negócios ganhos" valor={resumo.negocios.toLocaleString("pt-BR")} />
        <Tile rotulo="Receita atribuída" valor={formatBRL(resumo.valor)} destaque
          hint="negócios fechados vindos de campanha" />
      </div>

      <div className="border border-line bg-surface rounded-lg">
        <div className="grid grid-cols-12 px-4 py-2 border-b border-line text-[9px] font-bold uppercase tracking-wider text-ink-3">
          <div className="col-span-4">Campanha</div>
          <div className="col-span-1 text-right">Entregues</div>
          <div className="col-span-1 text-right">Falhas</div>
          <div className="col-span-1 text-right">Respostas</div>
          <div className="col-span-1 text-right">Taxa</div>
          <div className="col-span-1 text-right">Negócios</div>
          <div className="col-span-3 text-right">Receita</div>
        </div>
        {dados.itens.length === 0 && (
          <div className="p-8 text-center text-sm text-ink-3">
            Nenhuma campanha com disparo ou negócio fechado no período.
          </div>
        )}
        {dados.itens.map((i) => (
          <div key={i.campanha_id} className="grid grid-cols-12 px-4 py-2.5 border-b border-line last:border-b-0 items-center"
            data-testid={`rel-campanha-${i.campanha_id}`}>
            <div className="col-span-4 pr-3">
              <div className="text-sm font-semibold truncate">{i.nome}</div>
              <BarraLinha valor={i.valor} maximo={maxValor} />
            </div>
            <div className="col-span-1 text-right font-mono text-xs">{i.enviados}</div>
            <div className="col-span-1 text-right font-mono text-xs text-ink-3">{i.falhas || "—"}</div>
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

/** Percentual que já vem calculado do servidor. Nulo é "não há base", não zero. */
function pct(v) {
  return v == null ? "-" : `${v}%`;
}

function horas(min) {
  if (!min) return "-";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (!h) return `${m}min`;
  return m ? `${h}h ${m}min` : `${h}h`;
}

/**
 * Agenda: o que estava marcado no período e o que aconteceu com ele.
 *
 * A janela filtra o **início** do horário, não a data em que ele foi marcado.
 * Então tudo aqui é sobre o calendário do período, inclusive a quebra por quem
 * marcou, e os rótulos dizem isso. Sem esse cuidado, "20 marcados pelo robô"
 * seria lido como "o robô marcou 20 vezes neste mês", que é outra conta.
 */
function Agenda({ janela }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);

  useEffect(() => {
    setDados(null);
    setErro(null);
    api.get("/reports/agenda", { params: { de: desde(janela), ate: ate() } })
      .then((r) => setDados(r.data))
      .catch((ex) => setErro(formatApiErrorDetail(ex.response?.data?.detail)));
  }, [janela]);

  if (erro) {
    return (
      <div className="border border-warning bg-warning-soft p-4 flex gap-3 rounded-lg">
        <Warning size={18} weight="bold" className="text-warning shrink-0 mt-0.5" />
        <div className="text-sm text-ink">{erro}</div>
      </div>
    );
  }
  if (!dados) return <div className="text-xs text-ink-3 py-6">Carregando…</div>;

  const { resumo, lembrete, por_origem: origem } = dados;
  if (resumo.marcados === 0) {
    return (
      <div className="border border-line bg-surface rounded-lg p-10 text-center">
        <div className="text-sm text-ink-2">Nenhum horário marcado no período.</div>
        <div className="text-xs text-ink-3 mt-1">
          O relatório conta pelo dia do atendimento, não pelo dia em que foi marcado.
        </div>
      </div>
    );
  }

  const maxOcupacao = Math.max(100, ...dados.por_profissional.map((p) => p.ocupacao || 0));
  const maxServico = Math.max(1, ...dados.por_servico.map((s) => s.marcados));
  const automaticos = (origem.bot || 0) + (origem.ia || 0);

  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
        <Tile rotulo="Horários no período" valor={resumo.marcados.toLocaleString("pt-BR")} destaque />
        <Tile rotulo="Atendidos" valor={resumo.realizados.toLocaleString("pt-BR")}
          hint={horas(resumo.horas_realizadas * 60)} />
        <Tile rotulo="Faltas" valor={resumo.faltas.toLocaleString("pt-BR")}
          hint={`${pct(resumo.taxa_falta)} dos decididos`} />
        <Tile rotulo="Cancelados" valor={resumo.cancelados.toLocaleString("pt-BR")}
          hint={`${pct(resumo.taxa_cancelamento)} do total`} />
        <Tile rotulo="Por acontecer" valor={resumo.por_acontecer.toLocaleString("pt-BR")}
          hint={`${resumo.confirmados} confirmado(s)`} />
        <Tile rotulo="Receita realizada" valor={formatBRL(resumo.receita_realizada)} destaque
          hint="atendimentos concluídos" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-4">
        <Tile rotulo="Receita prevista" valor={formatBRL(resumo.receita_prevista)}
          hint="do que ainda vai acontecer" />
        <Tile rotulo="Receita perdida" valor={formatBRL(resumo.receita_perdida)}
          hint="faltas e cancelamentos" />
        <Tile rotulo="Marcados pelo WhatsApp" valor={automaticos.toLocaleString("pt-BR")}
          hint={`${origem.manual || 0} pela equipe${origem.ia ? ` · ${origem.ia} pelo agente de IA` : ""}`} />
      </div>

      {resumo.sem_preco > 0 && (
        <div className="text-[11px] text-ink-3 mb-4">
          {resumo.sem_preco} horário(s) sem preço no cadastro do serviço não entram em receita nenhuma.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
        <SerieDiaria titulo="Atendidos e faltas por dia" dados={dados.por_dia}
          series={[
            { chave: "realizados", rotulo: "Atendidos", slot: 1 },
            { chave: "faltas", rotulo: "Faltas", slot: 2 },
          ]} />
        <SerieDiaria titulo="Quem marcou, por dia" dados={dados.por_dia}
          series={[
            { chave: "equipe", rotulo: "Equipe", slot: 1 },
            { chave: "whatsapp", rotulo: "WhatsApp", slot: 2 },
          ]} />
      </div>

      {/* O lembrete é o que faz o módulo se pagar, e esta é a única leitura
          honesta que os dados permitem: uma comparação, não uma causa. */}
      <div className="border border-line bg-surface p-5 rounded-lg mb-4">
        <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-3">
          Efeito do lembrete
        </div>
        {lembrete.com.decididos + lembrete.sem.decididos === 0 ? (
          <div className="text-xs text-ink-4">
            Nenhum horário do período foi atendido ou marcado como falta ainda.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <Tile rotulo="Com lembrete enviado" valor={pct(lembrete.com.taxa_falta)}
                hint={`de falta · ${lembrete.com.faltas} de ${lembrete.com.decididos}`} />
              <Tile rotulo="Sem lembrete" valor={pct(lembrete.sem.taxa_falta)}
                hint={`de falta · ${lembrete.sem.faltas} de ${lembrete.sem.decididos}`} />
            </div>
            <div className="text-[11px] text-ink-3 mt-2">
              Não é comparação controlada: quem marcou para hoje não chega a receber lembrete,
              então a coluna sem lembrete carrega os de última hora.
            </div>
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="border border-line bg-surface p-5 rounded-lg">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-3">
            Por profissional
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line">
                <th className="text-left pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Profissional</th>
                <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Horários</th>
                <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Faltas</th>
                <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Ocupação</th>
                <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Receita</th>
              </tr>
            </thead>
            <tbody>
              {dados.por_profissional.map((p) => (
                <tr key={p.id} className="border-b border-line last:border-b-0"
                  data-testid={`rel-agenda-prof-${p.id}`}>
                  <td className="py-2.5 pr-2">
                    <div className="font-semibold truncate">
                      {p.nome}
                      {p.ativo === false && (
                        <span className="ml-1.5 text-[9px] font-bold uppercase tracking-wider text-ink-4">
                          inativo
                        </span>
                      )}
                    </div>
                    <BarraLinha valor={p.ocupacao || 0} maximo={maxOcupacao} cor="var(--serie-1)" />
                  </td>
                  <td className="py-2.5 text-right font-mono">{p.marcados}</td>
                  <td className="py-2.5 text-right font-mono">
                    {p.faltas || 0}
                    <span className="text-ink-3"> · {pct(p.taxa_falta)}</span>
                  </td>
                  <td className="py-2.5 text-right font-mono">{pct(p.ocupacao)}</td>
                  <td className="py-2.5 text-right font-mono">
                    {p.receita ? formatBRL(p.receita) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[11px] text-ink-3 mt-3">
            Ocupação é o tempo marcado dividido pelo tempo de grade do período, no fuso da
            empresa ({dados.fuso}). Passa de 100% quando alguém foi encaixado fora do horário
            de atendimento.
          </div>
        </div>

        <div className="border border-line bg-surface p-5 rounded-lg">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-3">
            Por serviço
          </div>
          {dados.por_servico.length === 0 ? (
            <div className="text-xs text-ink-4">Nenhum serviço no período.</div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line">
                  <th className="text-left pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Serviço</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Horários</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Atendidos</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Duração</th>
                  <th className="text-right pb-1 text-[9px] font-bold uppercase tracking-wider text-ink-3">Receita</th>
                </tr>
              </thead>
              <tbody>
                {dados.por_servico.map((s) => (
                  <tr key={s.id} className="border-b border-line last:border-b-0"
                    data-testid={`rel-agenda-servico-${s.id}`}>
                    <td className="py-2.5 pr-2">
                      <div className="font-semibold truncate">{s.nome}</div>
                      <BarraLinha valor={s.marcados} maximo={maxServico} cor="var(--serie-2)" />
                    </td>
                    <td className="py-2.5 text-right font-mono">{s.marcados}</td>
                    <td className="py-2.5 text-right font-mono">{s.realizados}</td>
                    <td className="py-2.5 text-right font-mono">{horas(s.duracao_media_min)}</td>
                    <td className="py-2.5 text-right font-mono">
                      {s.receita ? formatBRL(s.receita) : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
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

  if (!funilId) return <div className="text-xs text-ink-3 py-6">Carregando…</div>;
  return (
    <div>
      {funis.length > 1 && (
        <select className="zz-input max-w-[220px] mb-3" value={funilId}
          onChange={(e) => setFunilId(e.target.value)} data-testid="rel-funil">
          {funis.map((f) => <option key={f.id} value={f.id}>{f.nome}</option>)}
        </select>
      )}
      <FunilMetricas pipelineId={funilId} />
    </div>
  );
}

const ABAS = [
  ["atendimento", "Atendimento", Headset],
  ["agenda", "Agenda", CalendarBlank],
  ["campanhas", "Campanhas", Megaphone],
  ["funil", "Funil", Funnel],
];

export default function RelatoriosPage() {
  const [aba, setAba] = useState("atendimento");
  const [janela, setJanela] = useState("30");

  return (
    <div className="zz-page" data-testid="relatorios-page">
      <div className="flex items-end justify-between mb-6">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Relatórios</h1>
          <p className="text-ink-2 mt-2 text-sm">
            O que a operação produziu no período: atendimento, agenda, campanhas e funil.
          </p>
        </div>
        {aba !== "funil" && (
          <div className="flex gap-1">
            {JANELAS.map(([v, r]) => (
              <button key={v} onClick={() => setJanela(v)} data-testid={`janela-${v}`}
                className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border rounded-full ${
                  janela === v ? "bg-brand text-brand-fg border-brand" : "bg-surface border-line text-ink-2"
                }`}>
                {r}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-1 mb-4 border-b border-line">
        {ABAS.map(([v, r, Icone]) => (
          <button key={v} onClick={() => setAba(v)} data-testid={`aba-${v}`}
            className={`px-3 py-2 text-xs font-bold uppercase tracking-wider border-b-2 -mb-px flex items-center gap-1.5 ${
              aba === v ? "border-info text-ink" : "border-transparent text-ink-3 hover:text-ink"
            }`}>
            <Icone size={13} weight="bold" /> {r}
          </button>
        ))}
      </div>

      {aba === "atendimento" && <Atendimento janela={janela} />}
      {aba === "agenda" && <Agenda janela={janela} />}
      {aba === "campanhas" && <Campanhas janela={janela} />}
      {aba === "funil" && <FunilAba />}
    </div>
  );
}
