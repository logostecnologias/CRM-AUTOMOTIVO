import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatBRL } from "@/lib/currency";
import { MARCAS } from "@/lib/marca";
import SerieDiaria from "@/components/reports/SerieDiaria";
import { Indicador, Variacao, plural } from "@/components/painel/Indicadores";
import {
  SeloMarca, detalheDaEmpresa, porQue, tituloDoAlerta, useEntrar,
} from "@/components/superadmin/comum";
import {
  ArrowClockwise, ArrowRight, CheckCircle, SignIn, Warning, WarningCircle, Info,
} from "@phosphor-icons/react";

/**
 * Visão geral da plataforma, para quem opera o sistema.
 *
 * A versão anterior eram seis contagens do banco inteiro ("mensagens totais",
 * "robôs no sistema") sem comparação nem destino. Esta responde, nesta ordem:
 * "qual cliente está com problema agora?", "a plataforma está crescendo?" e
 * "quem mais usa?". Cada alerta lista as empresas, cada uma com o botão de
 * entrar já na tela onde aquilo se resolve. As contas estão em
 * `backend/plataforma.py`.
 */

const RECARGA_MS = 60_000;
// Acima disso o grupo de alerta mostra "e mais N": uma lista de 40 empresas
// paradas empurraria o resto da tela para fora da vista.
const MAX_POR_ALERTA = 6;

const series = [
  { chave: "automatico", rotulo: "Só robô ou IA", slot: 1 },
  { chave: "humano", rotulo: "Com atendente", slot: 2 },
];

function Alertas({ alertas, entrar, entrando }) {
  if (!alertas.length) {
    return (
      <div className="border border-line bg-surface rounded-xl px-4 py-3.5 flex items-center gap-3"
        data-testid="admin-tudo-em-dia">
        <CheckCircle size={20} weight="fill" className="text-success shrink-0" />
        <div className="text-sm">
          <span className="font-semibold">Tudo em dia.</span>{" "}
          <span className="text-ink-2">Todas as empresas ativas com WhatsApp no ar, movimento na semana e dentro do plano.</span>
        </div>
      </div>
    );
  }
  return (
    <div className="border border-line bg-surface rounded-xl overflow-hidden" data-testid="admin-alertas">
      <div className="px-4 pt-3.5 pb-2 text-sm font-semibold">Precisa de atenção</div>
      {alertas.map((a) => {
        // Ícone + texto, nunca só a cor: o nível também é dito pelo ícone.
        const Icone = a.nivel === "alto" ? WarningCircle : a.nivel === "medio" ? Warning : Info;
        const cor = a.nivel === "alto" ? "text-danger" : a.nivel === "medio" ? "text-warning" : "text-ink-3";
        const mostradas = a.empresas.slice(0, MAX_POR_ALERTA);
        return (
          <section key={a.tipo} className="border-t border-line px-4 py-3" data-testid={`admin-alerta-${a.tipo}`}>
            <div className="flex items-start gap-3">
              <Icone size={18} weight="fill" className={`shrink-0 mt-0.5 ${cor}`} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{tituloDoAlerta(a.tipo, a.empresas.length)}</div>
                {porQue(a.tipo) && <div className="text-xs text-ink-3 mt-0.5">{porQue(a.tipo)}</div>}
                <ul className="mt-2 divide-y divide-line border border-line rounded-lg">
                  {mostradas.map((e) => {
                    const detalhe = detalheDaEmpresa(a.tipo, e);
                    return (
                      <li key={e.id} className="flex items-center gap-3 px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm truncate">{e.name}</div>
                          {detalhe && <div className="text-xs text-ink-3 truncate">{detalhe}</div>}
                        </div>
                        {e.para ? (
                          <button onClick={() => entrar(e, e.para)} disabled={entrando}
                            className="text-xs font-medium text-ink-2 hover:text-ink flex items-center gap-1 shrink-0"
                            data-testid={`admin-alerta-entrar-${a.tipo}-${e.id}`}>
                            Entrar e resolver <ArrowRight size={11} weight="bold" />
                          </button>
                        ) : (
                          <Link to={`/admin/tenants?empresa=${e.id}`}
                            className="text-xs font-medium text-ink-2 hover:text-ink flex items-center gap-1 shrink-0">
                            Ver empresa <ArrowRight size={11} weight="bold" />
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
    </div>
  );
}

function MaisMovimento({ top, entrar, entrando }) {
  return (
    <div className="border border-line bg-surface rounded-xl" data-testid="admin-top">
      <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
        <div className="text-sm font-semibold">Mais movimento na semana</div>
        <Link to="/admin/tenants" className="text-xs text-ink-3 hover:text-ink flex items-center gap-1">
          Todas <ArrowRight size={11} weight="bold" />
        </Link>
      </div>
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
                <div className="text-sm truncate">{e.name}</div>
                <SeloMarca marca={e.marca} />
              </div>
              <div className="text-right shrink-0">
                <div className="font-mono text-sm font-semibold">{e.mensagens_7d.toLocaleString("pt-BR")}</div>
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
    </div>
  );
}

function PorMarca({ receita, empresas }) {
  return (
    <div className="border border-line bg-surface rounded-xl" data-testid="admin-por-marca">
      <div className="px-4 pt-3.5 pb-2 text-sm font-semibold">Por marca</div>
      {receita.por_marca.length === 0 ? (
        <div className="px-4 py-6 border-t border-line text-sm text-ink-3 text-center">Nenhuma empresa ativa.</div>
      ) : (
        <ul>
          {receita.por_marca.map((m) => {
            const pct = receita.mensal > 0 ? Math.round((m.receita / receita.mensal) * 100) : 0;
            return (
              <li key={m.marca} className="px-4 py-2.5 border-t border-line">
                <div className="flex items-baseline justify-between gap-3">
                  <SeloMarca marca={m.marca} />
                  <span className="font-mono text-sm font-semibold">{formatBRL(m.receita)}</span>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <div className="h-1.5 flex-1 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-[11px] text-ink-3 w-28 text-right">
                    {plural(m.empresas, "empresa", "empresas")} · {pct}%
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {empresas.suspensas > 0 && (
        <div className="px-4 py-2 border-t border-line text-xs text-ink-3">
          {plural(empresas.suspensas, "empresa suspensa", "empresas suspensas")} fora da conta.
        </div>
      )}
    </div>
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
        {v && (
          <button onClick={carregar} disabled={carregando}
            className="text-xs text-ink-3 hover:text-ink flex items-center gap-1.5" title="Atualizar agora">
            <ArrowClockwise size={13} weight="bold" className={carregando ? "animate-spin" : ""} />
            Atualizado às {atualizado}
          </button>
        )}
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
          <Alertas alertas={v.alertas} entrar={entrar} entrando={entrando} />

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            <Indicador testid="admin-kpi-receita" para="/admin/plans"
              rotulo="Receita mensal recorrente"
              valor={formatBRL(v.receita.mensal)}
              rodape={<span className="text-ink-3">soma dos planos das empresas ativas</span>} />
            <Indicador testid="admin-kpi-empresas" para="/admin/tenants"
              rotulo="Empresas ativas"
              valor={v.empresas.ativas.toLocaleString("pt-BR")}
              rodape={<span className="text-ink-3">
                {v.empresas.novas_mes > 0
                  ? `${plural(v.empresas.novas_mes, "nova", "novas")} este mês`
                  : "nenhuma nova este mês"}
              </span>} />
            <Indicador testid="admin-kpi-mensagens"
              rotulo="Mensagens · 7 dias"
              valor={v.semana.mensagens.toLocaleString("pt-BR")}
              rodape={<Variacao atual={v.semana.mensagens} anterior={v.semana.mensagens_anterior} />} />
            <Indicador testid="admin-kpi-uso"
              rotulo="Empresas com movimento · 7 dias"
              valor={`${v.empresas.com_movimento_7d} de ${v.empresas.ativas}`}
              rodape={<Variacao atual={v.empresas.com_movimento_7d}
                anterior={v.empresas.com_movimento_7d_anterior}
                formato={(n) => plural(n, "empresa", "empresas")} />} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
            <div className="xl:col-span-2 space-y-2">
              <SerieDiaria titulo="Conversas novas por dia · 14 dias · todas as empresas"
                dados={v.serie} series={series} altura={200} />
              <p className="text-xs text-ink-3 px-1">
                {v.semana.conversas.toLocaleString("pt-BR")} conversas novas nesta semana.
                {pctAuto != null && ` ${pctAuto}% das dos últimos 14 dias terminaram sem precisar de um atendente.`}
              </p>
            </div>
            <div className="space-y-3">
              <MaisMovimento top={v.top} entrar={entrar} entrando={entrando} />
              {Object.keys(MARCAS).length > 1 && <PorMarca receita={v.receita} empresas={v.empresas} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
