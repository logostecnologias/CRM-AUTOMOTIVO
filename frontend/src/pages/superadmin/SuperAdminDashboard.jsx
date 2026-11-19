import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatBRL } from "@/lib/currency";
import { MARCAS } from "@/lib/marca";
import SerieDiaria from "@/components/reports/SerieDiaria";
import { Indicador, Variacao, haQuanto, plural } from "@/components/painel/Indicadores";
import {
  BarraIA, Cartao, IconeNivel, SeloMarca, abaDoProblema, compacto, descreverAtividade,
  detalheDaEmpresa, dolar, numero, porQue, tituloDoAlerta, useEntrar,
} from "@/components/superadmin/comum";
import {
  ArrowClockwise, ArrowRight, CheckCircle, ClockCounterClockwise, Plus, SignIn,
} from "@phosphor-icons/react";

/**
 * Visão geral da plataforma, para quem opera o sistema.
 *
 * Lida de cima para baixo, responde: "como está a base de clientes agora?"
 * (o semáforo), "a plataforma está gerando resultado?" (mensagens, leads,
 * vendas), "o que precisa de mim?" (alertas, cada um com o botão de entrar já
 * na tela do problema), "o que mudou?" (atividade recente) e "quanto a IA está
 * custando?" (consumo pago pela chave da plataforma contra o teto de cada
 * empresa). As contas estão em `backend/plataforma.py`.
 *
 * Os planos saíram em 18/11/2026: não há receita nem limite de cadastro aqui.
 */

const RECARGA_MS = 60_000;
// Acima disso o grupo de alerta mostra "e mais N": uma lista de 40 empresas
// paradas empurraria o resto da tela para fora da vista.
const MAX_POR_ALERTA = 5;

const series = [
  { chave: "automatico", rotulo: "Só robô ou IA", slot: 1 },
  { chave: "humano", rotulo: "Com atendente", slot: 2 },
];

/**
 * O semáforo da base: cada empresa ativa numa faixa só, a do pior problema
 * dela. A barra mostra a proporção; cada faixa leva à lista já filtrada.
 */
function Semaforo({ faixas, empresas }) {
  const total = faixas.alto + faixas.medio + faixas.em_dia;
  const itens = [
    { chave: "alto", rotulo: "Problema grave", cor: "bg-danger", texto: "text-danger", filtro: "graves" },
    { chave: "medio", rotulo: "Precisam de atenção", cor: "bg-warning", texto: "text-warning", filtro: "atencao" },
    { chave: "em_dia", rotulo: "Em dia", cor: "bg-success", texto: "text-success", filtro: "em_dia" },
  ];
  return (
    <div className="border border-line bg-surface rounded-xl p-4" data-testid="admin-semaforo">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="text-sm font-semibold">Saúde da base</div>
        <div className="text-xs text-ink-3">
          {plural(empresas.ativas, "empresa ativa", "empresas ativas")}
          {empresas.suspensas > 0 && (
            <> · <Link to="/admin/tenants?filtro=suspensas" className="hover:text-ink underline-offset-2 hover:underline">
              {plural(empresas.suspensas, "suspensa", "suspensas")}
            </Link></>
          )}
        </div>
      </div>
      {total > 0 && (
        <div className="flex h-2.5 mt-3 rounded-full overflow-hidden bg-surface-3" aria-hidden>
          {itens.map((i) => faixas[i.chave] > 0 && (
            <div key={i.chave} className={i.cor} style={{ width: `${(faixas[i.chave] / total) * 100}%` }} />
          ))}
        </div>
      )}
      <div className="grid grid-cols-3 gap-2 mt-3">
        {itens.map((i) => (
          <Link key={i.chave} to={`/admin/tenants?filtro=${i.filtro}`}
            className="rounded-lg border border-line px-3 py-2 hover:border-line-strong hover:bg-surface-2"
            data-testid={`semaforo-${i.chave}`}>
            <div className={`font-heading text-2xl font-black tracking-tight ${faixas[i.chave] ? i.texto : "text-ink-3"}`}>
              {faixas[i.chave]}
            </div>
            <div className="text-[11px] text-ink-3 leading-tight">{i.rotulo}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Alertas({ alertas, entrar, entrando }) {
  if (!alertas.length) {
    return (
      <Cartao testid="admin-tudo-em-dia">
        <div className="px-4 py-6 flex flex-col items-center text-center gap-2">
          <CheckCircle size={28} weight="fill" className="text-success" />
          <div className="text-sm font-semibold">Tudo em dia</div>
          <div className="text-xs text-ink-3 max-w-sm">
            Todas as empresas ativas com WhatsApp no ar, movimento na semana e IA dentro do limite.
          </div>
        </div>
      </Cartao>
    );
  }
  const n = new Set(alertas.flatMap((a) => a.empresas.map((e) => e.id))).size;
  return (
    <Cartao titulo={`Precisa de atenção · ${plural(n, "empresa", "empresas")}`} testid="admin-alertas"
      acao={<Link to="/admin/tenants?filtro=atencao" className="text-xs text-ink-3 hover:text-ink flex items-center gap-1">
        Ver na lista <ArrowRight size={11} weight="bold" />
      </Link>}>
      {alertas.map((a) => {
        const mostradas = a.empresas.slice(0, MAX_POR_ALERTA);
        return (
          <section key={a.tipo} className="border-t border-line px-4 py-3" data-testid={`admin-alerta-${a.tipo}`}>
            <div className="flex items-start gap-3">
              <span className="mt-0.5"><IconeNivel nivel={a.nivel} size={18} /></span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{tituloDoAlerta(a.tipo, a.empresas.length)}</div>
                {porQue(a.tipo) && <div className="text-xs text-ink-3 mt-0.5">{porQue(a.tipo)}</div>}
                <ul className="mt-2 divide-y divide-line border border-line rounded-lg">
                  {mostradas.map((e) => {
                    const detalhe = detalheDaEmpresa(a.tipo, e);
                    return (
                      <li key={e.id} className="flex items-center gap-3 px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <Link to={`/admin/tenants?empresa=${e.id}`} className="text-sm truncate block hover:underline underline-offset-2">
                            {e.name}
                          </Link>
                          {detalhe && <div className="text-xs text-ink-3 truncate">{detalhe}</div>}
                        </div>
                        {e.para ? (
                          <button onClick={() => entrar(e, e.para)} disabled={entrando}
                            className="text-xs font-medium text-ink-2 hover:text-ink flex items-center gap-1 shrink-0"
                            data-testid={`admin-alerta-entrar-${a.tipo}-${e.id}`}>
                            Entrar e resolver <ArrowRight size={11} weight="bold" />
                          </button>
                        ) : (
                          <Link to={`/admin/tenants?empresa=${e.id}&aba=${abaDoProblema(a.tipo)}`}
                            className="text-xs font-medium text-ink-2 hover:text-ink flex items-center gap-1 shrink-0">
                            Resolver na ficha <ArrowRight size={11} weight="bold" />
                          </Link>
                        )}
                      </li>
                    );
                  })}
                  {a.empresas.length > mostradas.length && (
                    <li className="px-3 py-2 text-xs text-ink-3">
                      <Link to="/admin/tenants?filtro=atencao" className="hover:text-ink">
                        e mais {plural(a.empresas.length - mostradas.length, "empresa", "empresas")}
                      </Link>
                    </li>
                  )}
                </ul>
              </div>
            </div>
          </section>
        );
      })}
    </Cartao>
  );
}

function Atividade({ itens }) {
  return (
    <Cartao titulo="Atividade recente" testid="admin-atividade"
      acao={<ClockCounterClockwise size={15} className="text-ink-3" />}>
      {itens.length === 0 ? (
        <div className="px-4 py-6 border-t border-line text-sm text-ink-3 text-center">
          Nenhuma ação registrada ainda.
        </div>
      ) : (
        <ol className="border-t border-line max-h-[420px] overflow-y-auto">
          {itens.map((a, i) => (
            <li key={i} className="px-4 py-2.5 border-b border-line last:border-b-0">
              <div className="text-sm leading-snug">
                <span className="font-medium">{a.ator || "alguém"}</span>{" "}
                <span className="text-ink-2">{descreverAtividade(a)}</span>
                {a.empresa && (
                  a.tenant_id && a.acao !== "tenant.delete" ? (
                    <> em <Link to={`/admin/tenants?empresa=${a.tenant_id}&aba=historico`}
                      className="font-medium hover:underline underline-offset-2">{a.empresa}</Link></>
                  ) : <> · <span className="font-medium">{a.empresa}</span></>
                )}
              </div>
              <div className="text-[11px] text-ink-3 mt-0.5 flex items-center gap-1.5">
                {haQuanto(a.em)}
                {a.suporte && a.acao !== "suporte.entrar" && <span>· em modo suporte</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Cartao>
  );
}

function MaisMovimento({ top, entrar, entrando }) {
  return (
    <Cartao titulo="Mais movimento na semana" testid="admin-top"
      acao={<Link to="/admin/tenants?ordem=movimento" className="text-xs text-ink-3 hover:text-ink flex items-center gap-1">
        Todas <ArrowRight size={11} weight="bold" />
      </Link>}>
      {top.length === 0 ? (
        <div className="px-4 py-6 border-t border-line text-sm text-ink-3 text-center">
          Nenhuma mensagem na plataforma nos últimos 7 dias.
        </div>
      ) : (
        <ul>
          {top.map((e, i) => (
            <li key={e.id} className="flex items-center gap-3 px-4 py-2.5 border-t border-line">
              <span className="font-mono text-xs text-ink-3 w-4">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <Link to={`/admin/tenants?empresa=${e.id}`} className="text-sm truncate block hover:underline underline-offset-2">
                  {e.name}
                </Link>
                <div className="text-[11px] text-ink-3">{plural(e.leads_7d || 0, "lead", "leads")} na semana</div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-mono text-sm font-semibold">{numero(e.mensagens_7d)}</div>
                <div className="text-[11px] text-ink-3">mensagens</div>
              </div>
              <button onClick={() => entrar(e)} disabled={entrando} title="Entrar na empresa"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2">
                <SignIn size={15} weight="bold" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Cartao>
  );
}

function ConsumoIA({ ia }) {
  return (
    <Cartao titulo="IA paga pela plataforma · este mês" testid="admin-consumo-ia"
      acao={<span className="text-xs text-ink-3">{plural(ia.empresas, "empresa usando", "empresas usando")}</span>}>
      {ia.ranking.length === 0 ? (
        <div className="px-4 py-6 border-t border-line text-sm text-ink-3 text-center">
          Nenhum consumo de IA neste mês.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[480px]">
            <thead>
              <tr className="text-[11px] text-ink-3 border-t border-b border-line">
                <th className="font-medium px-4 py-2">Empresa</th>
                <th className="font-medium px-3 py-2">Tokens · limite</th>
                <th className="font-medium px-3 py-2 text-right">Custo</th>
                <th className="font-medium px-4 py-2 text-right">Conta própria</th>
              </tr>
            </thead>
            <tbody>
              {ia.ranking.map((e) => (
                <tr key={e.id} className="border-b border-line last:border-b-0">
                  <td className="px-4 py-2.5">
                    <Link to={`/admin/tenants?empresa=${e.id}&aba=config`} className="text-sm hover:underline underline-offset-2">
                      {e.name}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5 w-48"><BarraIA ia={e} /></td>
                  <td className="px-3 py-2.5 text-right font-mono text-sm">{dolar(e.custo_usd)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-3">
                    {e.tokens - e.tokens_plataforma > 0 ? compacto(e.tokens - e.tokens_plataforma) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="px-4 py-2 border-t border-line text-[11px] text-ink-3">
        Custo estimado em dólar pela tabela do provedor. O que roda na chave do próprio cliente não entra no limite nem no custo.
      </div>
    </Cartao>
  );
}

function PorMarca({ marcas }) {
  const total = marcas.reduce((s, m) => s + m.empresas, 0);
  return (
    <Cartao titulo="Por marca" testid="admin-por-marca">
      {marcas.length === 0 ? (
        <div className="px-4 py-6 border-t border-line text-sm text-ink-3 text-center">Nenhuma empresa ativa.</div>
      ) : (
        <ul>
          {marcas.map((m) => {
            const pct = total > 0 ? Math.round((m.empresas / total) * 100) : 0;
            return (
              <li key={m.marca} className="px-4 py-2.5 border-t border-line">
                <div className="flex items-baseline justify-between gap-3">
                  <SeloMarca marca={m.marca} />
                  <span className="text-xs text-ink-3">{numero(m.mensagens_7d)} mensagens na semana</span>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <div className="h-1.5 flex-1 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-[11px] text-ink-3 w-24 text-right">
                    {plural(m.empresas, "empresa", "empresas")}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Cartao>
  );
}

export default function SuperAdminDashboard() {
  const { user } = useAuth();
  const [v, setV] = useState(null);
  const [erro, setErro] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [entrar, entrando] = useEntrar();

  const carregar = useCallback(() => {
    setCarregando(true);
    api.get("/admin/visao")
      .then((r) => { setV(r.data); setErro(false); })
      .catch(() => setErro(true))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar();
    const t = setInterval(carregar, RECARGA_MS);
    return () => clearInterval(t);
  }, [carregar]);

  const atualizado = v
    ? new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(new Date(v.gerado_em))
    : null;
  const totais = v
    ? v.serie.reduce((acc, d) => ({ a: acc.a + d.automatico, h: acc.h + d.humano }), { a: 0, h: 0 })
    : null;
  const pctAuto = totais && totais.a + totais.h > 0
    ? Math.round((totais.a / (totais.a + totais.h)) * 100)
    : null;

  return (
    <div className="zz-page" data-testid="admin-dashboard">
      <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Visão geral</h1>
          <p className="text-ink-2 mt-2 text-sm">
            Olá, {user?.name?.split(" ")[0]}. A plataforma inteira, todas as marcas.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {v && (
            <button onClick={carregar} disabled={carregando}
              className="text-xs text-ink-3 hover:text-ink flex items-center gap-1.5" title="Atualizar agora">
              <ArrowClockwise size={13} weight="bold" className={carregando ? "animate-spin" : ""} />
              Atualizado às {atualizado}
            </button>
          )}
          <Link to="/admin/tenants?nova=1" className="zz-btn" data-testid="admin-nova-empresa">
            <Plus size={16} weight="bold" /> Nova empresa
          </Link>
        </div>
      </div>

      {!v ? (
        <div className="text-sm text-ink-3 py-8">
          {erro ? (
            <span className="flex items-center gap-2">
              Não foi possível carregar a visão geral.
              <button onClick={carregar} className="underline hover:text-ink">Tentar de novo</button>
            </span>
          ) : "Carregando…"}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
            <Semaforo faixas={v.faixas} empresas={v.empresas} />
            <div className="xl:col-span-2 grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Indicador testid="admin-kpi-mensagens"
                rotulo="Mensagens · 7 dias"
                valor={numero(v.semana.mensagens)}
                rodape={<Variacao atual={v.semana.mensagens} anterior={v.semana.mensagens_anterior} />} />
              <Indicador testid="admin-kpi-leads"
                rotulo="Leads novos · 7 dias"
                valor={numero(v.semana.leads)}
                rodape={<Variacao atual={v.semana.leads} anterior={v.semana.leads_anterior} />} />
              <Indicador testid="admin-kpi-vendas"
                rotulo="Vendas no funil · 30 dias"
                valor={numero(v.vendas_30d.n)}
                rodape={<span className="text-ink-3">
                  {v.vendas_30d.valor > 0 ? `${formatBRL(v.vendas_30d.valor)} em negócios ganhos` : "nenhum valor informado"}
                </span>} />
              <Indicador testid="admin-kpi-conversas"
                rotulo="Conversas novas · 7 dias"
                valor={numero(v.semana.conversas)}
                rodape={<Variacao atual={v.semana.conversas} anterior={v.semana.conversas_anterior} />} />
              <Indicador testid="admin-kpi-uso" para="/admin/tenants?ordem=movimento"
                rotulo="Empresas com movimento · 7 dias"
                valor={`${v.empresas.com_movimento_7d} de ${v.empresas.ativas}`}
                rodape={<span className="text-ink-3">
                  {v.empresas.novas_mes > 0
                    ? `${plural(v.empresas.novas_mes, "nova", "novas")} este mês`
                    : "nenhuma nova este mês"}
                </span>} />
              <Indicador testid="admin-kpi-ia"
                rotulo="Custo de IA · este mês"
                valor={dolar(v.ia.custo_usd)}
                rodape={<span className="text-ink-3">{compacto(v.ia.tokens_plataforma)} tokens pela plataforma</span>} />
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 items-start">
            <div className="xl:col-span-2">
              <Alertas alertas={v.alertas} entrar={entrar} entrando={entrando} />
            </div>
            <Atividade itens={v.atividade} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 items-start">
            <div className="xl:col-span-2 space-y-2">
              <SerieDiaria titulo="Conversas novas por dia · 14 dias · todas as empresas"
                dados={v.serie} series={series} altura={210} />
              <p className="text-xs text-ink-3 px-1">
                {pctAuto != null
                  ? `${pctAuto}% das conversas dos últimos 14 dias terminaram sem precisar de um atendente.`
                  : "Nenhuma conversa nos últimos 14 dias."}
              </p>
            </div>
            <MaisMovimento top={v.top} entrar={entrar} entrando={entrando} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 items-start">
            <div className="xl:col-span-2"><ConsumoIA ia={v.ia} /></div>
            {Object.keys(MARCAS).length > 1 && <PorMarca marcas={v.por_marca} />}
          </div>
        </div>
      )}
    </div>
  );
}
