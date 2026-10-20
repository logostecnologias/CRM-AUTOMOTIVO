import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatBRL } from "@/lib/currency";
import SerieDiaria from "@/components/reports/SerieDiaria";
import {
  ArrowClockwise, ArrowDown, ArrowRight, ArrowUp, ChatsCircle, CheckCircle,
  CheckSquareOffset, Headset, Megaphone, Robot, UsersThree, Warning,
  WarningCircle, WhatsappLogo,
} from "@phosphor-icons/react";

/**
 * O painel responde a duas perguntas, nesta ordem: "o que precisa de mim
 * agora?" e "a operação está indo melhor ou pior?". A versão anterior eram
 * sete caixas de contagem sem comparação nem destino, e o cliente a achou
 * inútil (20/10/2026). Por isso:
 *
 *  - Os alertas vêm primeiro, e cada um leva à tela onde se resolve.
 *  - Todo número de tendência vem com a semana anterior ao lado. "128
 *    conversas" não diz nada; "128, 12% a mais" diz.
 *  - O gráfico separa o que um atendente pegou do que o robô ou o agente
 *    resolveu sozinho, que é o trabalho que o sistema faz pela empresa.
 */

// Mesmos cortes de fuso das atividades: quem sabe em que fuso está é o navegador.
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

// O painel fica aberto numa aba o dia inteiro: sem recarregar, a fila que ele
// mostra envelhece. Um minuto, como o selo de atividades, e não os 3s da
// Central: aqui ninguém responde conversa.
const RECARGA_MS = 60_000;

function plural(n, um, varios) {
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? um : varios}`;
}

function haQuanto(iso) {
  if (!iso) return null;
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 1) return "agora há pouco";
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  return `há ${plural(Math.floor(h / 24), "dia", "dias")}`;
}

function duracao(seg) {
  if (seg == null) return "—";
  const min = Math.round(seg / 60);
  if (min < 1) return "< 1 min";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const resto = min % 60;
  return resto ? `${h} h ${resto} min` : `${h} h`;
}

function hoje() {
  const t = new Intl.DateTimeFormat("pt-BR", {
    weekday: "long", day: "numeric", month: "long",
  }).format(new Date());
  return t.charAt(0).toUpperCase() + t.slice(1);
}

// ---------------------------------------------------------------------------
// Alertas
// ---------------------------------------------------------------------------

function textoDoAlerta(a) {
  switch (a.tipo) {
    case "fila": {
      const espera = haQuanto(a.desde);
      return {
        titulo: `${plural(a.n, "conversa esperando", "conversas esperando")} atendimento`,
        detalhe: espera ? `A mais antiga chegou na fila ${espera}.` : null,
        acao: "Abrir fila",
      };
    }
    case "atividades":
      return {
        titulo: plural(a.n, "atividade atrasada", "atividades atrasadas"),
        detalhe: "Venceram e ainda não foram concluídas.",
        acao: "Ver atividades",
      };
    case "conexoes":
      return {
        titulo: a.n === 1 ? "Conexão de WhatsApp fora do ar" : `${a.n} conexões de WhatsApp fora do ar`,
        detalhe: `${a.nomes.join(", ")}. Lembretes, campanhas e respostas por esse número não saem.`,
        acao: "Ver conexões",
      };
    case "agentes":
      return {
        titulo: a.n === 1 ? "Agente de IA com a chave recusada" : `${a.n} agentes de IA com a chave recusada`,
        detalhe: `${a.nomes.join(", ")}. As conversas estão indo para a fila.`,
        acao: "Ver agentes",
      };
    case "campanhas":
      return {
        titulo: plural(a.n, "campanha pausada", "campanhas pausadas"),
        detalhe: [a.nomes.join(", "), a.motivo].filter(Boolean).join(". ") + ".",
        acao: "Ver campanhas",
      };
    default:
      return { titulo: a.tipo, detalhe: null, acao: "Abrir" };
  }
}

function Alertas({ alertas, admin }) {
  if (!alertas.length) {
    return (
      <div className="border border-line bg-surface rounded-xl px-4 py-3.5 flex items-center gap-3"
        data-testid="painel-tudo-em-dia">
        <CheckCircle size={20} weight="fill" className="text-success shrink-0" />
        <div className="text-sm">
          <span className="font-semibold">Tudo em dia.</span>{" "}
          <span className="text-ink-2">
            {admin
              ? "Fila vazia, nenhuma atividade atrasada e todas as conexões no ar."
              : "Nenhuma conversa esperando e nenhuma atividade sua atrasada."}
          </span>
        </div>
      </div>
    );
  }
  return (
    <div className="border border-line bg-surface rounded-xl overflow-hidden" data-testid="painel-alertas">
      <div className="px-4 pt-3.5 pb-2 text-sm font-semibold">Precisa de atenção</div>
      <ul>
        {alertas.map((a) => {
          const t = textoDoAlerta(a);
          const alto = a.nivel === "alto";
          // Ícone + texto, nunca só a cor: o nível também é dito pelo ícone.
          const Icone = alto ? WarningCircle : Warning;
          const corpo = (
            <>
              <Icone size={18} weight="fill"
                className={`shrink-0 mt-0.5 ${alto ? "text-danger" : "text-warning"}`} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-ink">{t.titulo}</div>
                {t.detalhe && <div className="text-xs text-ink-3 mt-0.5">{t.detalhe}</div>}
              </div>
              {a.para && (
                <span className="text-xs font-medium text-ink-2 group-hover:text-ink whitespace-nowrap flex items-center gap-1 mt-0.5">
                  {t.acao} <ArrowRight size={12} weight="bold" />
                </span>
              )}
            </>
          );
          const classe = "flex items-start gap-3 px-4 py-3 border-t border-line";
          return (
            <li key={a.tipo} data-testid={`alerta-${a.tipo}`}>
              {a.para ? (
                <Link to={a.para} className={`${classe} group hover:bg-surface-2`}>{corpo}</Link>
              ) : (
                <div className={classe}>{corpo}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Números
// ---------------------------------------------------------------------------

/**
 * A variação contra a semana anterior. `menorMelhor` inverte a leitura (espera
 * na fila que cai é boa notícia). Seta + palavra, para não depender só da cor.
 */
function Variacao({ atual, anterior, menorMelhor = false, formato }) {
  if (atual == null || anterior == null) {
    return <span className="text-ink-3">sem semana anterior para comparar</span>;
  }
  if (anterior === 0 && atual === 0) return <span className="text-ink-3">igual à semana anterior</span>;
  const diff = atual - anterior;
  if (diff === 0) return <span className="text-ink-3">igual à semana anterior</span>;
  const subiu = diff > 0;
  const bom = menorMelhor ? !subiu : subiu;
  const Seta = subiu ? ArrowUp : ArrowDown;
  const quanto = formato
    ? formato(Math.abs(diff))
    : anterior > 0
      ? `${Math.round((Math.abs(diff) / anterior) * 100)}%`
      : plural(Math.abs(diff), "", "").trim();
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`inline-flex items-center gap-0.5 font-semibold ${bom ? "text-success" : "text-danger"}`}>
        <Seta size={11} weight="bold" />
        {quanto}
      </span>
      <span className="text-ink-3">{subiu ? "a mais" : "a menos"} que a semana anterior</span>
    </span>
  );
}

function Indicador({ rotulo, valor, rodape, para, testid }) {
  const corpo = (
    <>
      <div className="text-xs text-ink-3">{rotulo}</div>
      <div className="font-heading text-3xl font-black tracking-tight mt-1 truncate">{valor}</div>
      <div className="text-xs mt-1.5 min-h-[1rem]">{rodape}</div>
    </>
  );
  const classe = "block border border-line bg-surface rounded-xl p-4";
  return para ? (
    <Link to={para} className={`${classe} hover:border-line-strong`} data-testid={testid}>{corpo}</Link>
  ) : (
    <div className={classe} data-testid={testid}>{corpo}</div>
  );
}

// ---------------------------------------------------------------------------
// Conversas agora e agenda de hoje
// ---------------------------------------------------------------------------

function ConversasAgora({ a, admin }) {
  const linhas = [
    { rotulo: "Com o robô ou agente de IA", n: a.bot, icone: Robot },
    { rotulo: "Na fila", n: a.aguardando, icone: Headset, alerta: a.aguardando > 0 },
    { rotulo: "Em atendimento", n: a.em_atendimento, icone: UsersThree },
  ];
  if (!admin) linhas.push({ rotulo: "Com você", n: a.minhas, icone: CheckCircle });
  return (
    <div className="border border-line bg-surface rounded-xl" data-testid="painel-conversas-agora">
      <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
        <div className="text-sm font-semibold">Conversas agora</div>
        <Link to="/app/atendimento" className="text-xs text-ink-3 hover:text-ink flex items-center gap-1">
          Abrir <ArrowRight size={11} weight="bold" />
        </Link>
      </div>
      <ul>
        {linhas.map(({ rotulo, n, icone: Icone, alerta }) => (
          <li key={rotulo} className="flex items-center gap-3 px-4 py-2.5 border-t border-line">
            <Icone size={15} className="text-ink-3 shrink-0" />
            <span className="text-sm text-ink-2 flex-1">{rotulo}</span>
            <span className={`font-mono text-sm font-semibold ${alerta ? "text-danger" : "text-ink"}`}>
              {n.toLocaleString("pt-BR")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AgendaDeHoje({ agenda }) {
  // A hora é a da empresa, não a do computador: mesma regra da tela de Agenda.
  const hora = new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit", minute: "2-digit", timeZone: agenda.fuso,
  });
  const agora = new Date().toISOString();
  return (
    <div className="border border-line bg-surface rounded-xl" data-testid="painel-agenda-hoje">
      <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
        <div className="text-sm font-semibold">
          Agenda de hoje{" "}
          <span className="font-normal text-ink-3">· {plural(agenda.total, "horário", "horários")}</span>
        </div>
        <Link to="/app/agenda" className="text-xs text-ink-3 hover:text-ink flex items-center gap-1">
          Abrir <ArrowRight size={11} weight="bold" />
        </Link>
      </div>
      {agenda.itens.length === 0 ? (
        <div className="px-4 py-6 border-t border-line text-sm text-ink-3 text-center">
          Nenhum horário marcado para hoje.
        </div>
      ) : (
        <ul>
          {agenda.itens.map((i) => {
            const passou = i.inicio < agora;
            return (
              <li key={i.id} className={`flex items-baseline gap-3 px-4 py-2.5 border-t border-line ${passou ? "opacity-60" : ""}`}>
                <span className="font-mono text-sm font-semibold w-12 shrink-0">
                  {hora.format(new Date(i.inicio))}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate">{i.contact_nome || "Sem nome"}</div>
                  <div className="text-xs text-ink-3 truncate">
                    {[i.service_nome, i.resource_nome].filter(Boolean).join(" · ")}
                  </div>
                </div>
                {i.status === "confirmado" && (
                  <span className="text-[11px] text-success flex items-center gap-1 shrink-0">
                    <CheckCircle size={12} weight="fill" /> confirmado
                  </span>
                )}
              </li>
            );
          })}
          {agenda.total > agenda.itens.length && (
            <li className="px-4 py-2 border-t border-line text-xs text-ink-3">
              e mais {plural(agenda.total - agenda.itens.length, "horário", "horários")}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Faixa da operação
// ---------------------------------------------------------------------------

function Operacao({ m }) {
  const itens = [
    {
      para: "/app/whatsapp", icone: WhatsappLogo, rotulo: "WhatsApp",
      valor: `${m.base.conexoes_conectadas} de ${m.base.conexoes_total} no ar`,
      alerta: m.base.conexoes_total > 0 && m.base.conexoes_conectadas < m.base.conexoes_total,
    },
    { para: "/app/bots", icone: Robot, rotulo: "Robôs ativos", valor: m.base.bots_ativos },
    {
      para: "/app/campanhas", icone: Megaphone, rotulo: "Campanhas",
      valor: `${m.campanhas.em_andamento} em andamento · ${m.campanhas.disparos_mes.toLocaleString("pt-BR")} enviadas no mês`,
    },
    { para: "/app/contacts", icone: UsersThree, rotulo: "Contatos", valor: m.base.contatos.toLocaleString("pt-BR") },
    {
      para: "/app/relatorios", icone: ChatsCircle, rotulo: "Mensagens em 30 dias",
      valor: m.atendimento.mensagens_30d.toLocaleString("pt-BR"),
    },
  ];
  return (
    <div className="border border-line bg-surface rounded-xl grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 overflow-hidden"
      data-testid="painel-operacao">
      {itens.map(({ para, icone: Icone, rotulo, valor, alerta }) => (
        <Link key={rotulo} to={para}
          className="flex items-start gap-3 px-4 py-3 hover:bg-surface-2 border-b border-line xl:border-b-0 xl:border-r last:border-r-0 last:border-b-0">
          <Icone size={16} className="text-ink-3 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <div className="text-xs text-ink-3">{rotulo}</div>
            <div className={`text-sm font-medium ${alerta ? "text-danger" : "text-ink"}`}>{valor}</div>
          </div>
        </Link>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tela
// ---------------------------------------------------------------------------

const SERIES = [
  { chave: "automatico", rotulo: "Só robô ou IA", slot: 1 },
  { chave: "humano", rotulo: "Com atendente", slot: 2 },
];

export default function TenantDashboard() {
  const { user } = useAuth();
  const [m, setMetrics] = useState(null);
  const [erro, setErro] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const admin = user?.role === "tenant_admin";

  const carregar = useCallback(() => {
    setCarregando(true);
    api.get("/dashboard/metrics", {
      params: { hoje_ate: fimDoDia(), semana_ate: fimDaSemana() },
    })
      .then((r) => { setMetrics(r.data); setErro(false); })
      .catch(() => setErro(true))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar();
    const t = setInterval(carregar, RECARGA_MS);
    return () => clearInterval(t);
  }, [carregar]);

  const atualizado = m
    ? new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(new Date(m.gerado_em))
    : null;

  const totais = m
    ? m.serie.reduce((acc, d) => ({ a: acc.a + d.automatico, h: acc.h + d.humano }), { a: 0, h: 0 })
    : null;
  const pctAuto = totais && totais.a + totais.h > 0
    ? Math.round((totais.a / (totais.a + totais.h)) * 100)
    : null;

  return (
    <div className="zz-page" data-testid="tenant-dashboard">
      <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Painel</h1>
          <p className="text-ink-2 mt-2 text-sm">
            Olá, {user?.name?.split(" ")[0]}. {hoje()}.
          </p>
        </div>
        {m && (
          <button onClick={carregar} disabled={carregando}
            className="text-xs text-ink-3 hover:text-ink flex items-center gap-1.5"
            title="Atualizar agora" data-testid="painel-atualizar">
            <ArrowClockwise size={13} weight="bold" className={carregando ? "animate-spin" : ""} />
            Atualizado às {atualizado}
          </button>
        )}
      </div>

      {!m ? (
        <div className="text-sm text-ink-3 py-8">
          {erro ? (
            <span className="flex items-center gap-2">
              Não foi possível carregar o painel.
              <button onClick={carregar} className="underline hover:text-ink">Tentar de novo</button>
            </span>
          ) : "Carregando…"}
        </div>
      ) : (
        <div className="space-y-4">
          <Alertas alertas={m.alertas} admin={admin} />

          <div className={`grid grid-cols-1 sm:grid-cols-2 ${admin ? "xl:grid-cols-4" : "xl:grid-cols-3"} gap-3`}>
            <Indicador testid="kpi-conversas" para={admin ? "/app/relatorios" : undefined}
              rotulo="Conversas novas · 7 dias"
              valor={m.semana.conversas.toLocaleString("pt-BR")}
              rodape={<Variacao atual={m.semana.conversas} anterior={m.semana.conversas_anterior} />} />
            <Indicador testid="kpi-espera" para={admin ? "/app/relatorios" : undefined}
              rotulo="Espera média na fila · 7 dias"
              valor={duracao(m.semana.espera_media_s)}
              rodape={m.semana.espera_media_s == null
                ? <span className="text-ink-3">ninguém foi atendido por pessoa na semana</span>
                : <Variacao atual={m.semana.espera_media_s} anterior={m.semana.espera_media_anterior_s}
                    menorMelhor formato={duracao} />} />
            {admin ? (
              <>
                <Indicador testid="kpi-vendido" para="/app/funil"
                  rotulo="Vendido no mês"
                  valor={formatBRL(m.funil.ganho_mes.valor)}
                  rodape={
                    <span className="text-ink-3">
                      {plural(m.funil.ganho_mes.n, "negócio", "negócios")}
                      {m.funil.conversao_mes != null &&
                        ` · ${Math.round(m.funil.conversao_mes * 100)}% de conversão`}
                    </span>
                  } />
                <Indicador testid="kpi-aberto" para="/app/funil"
                  rotulo="Em negociação no funil"
                  valor={formatBRL(m.funil.aberto.valor)}
                  rodape={<span className="text-ink-3">{plural(m.funil.aberto.n, "negócio aberto", "negócios abertos")}</span>} />
              </>
            ) : (
              <Indicador testid="kpi-atividades"
                rotulo="Suas atividades"
                valor={m.agenda.hoje.toLocaleString("pt-BR")}
                rodape={<span className="text-ink-3">
                  para hoje · {plural(m.agenda.pendentes, "pendente", "pendentes")} no total
                </span>} />
            )}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
            <div className="xl:col-span-2 space-y-2">
              <SerieDiaria titulo="Conversas novas por dia · 14 dias" dados={m.serie}
                series={SERIES} altura={200} />
              {pctAuto != null && (
                <p className="text-xs text-ink-3 px-1">
                  {pctAuto}% das conversas dos últimos 14 dias terminaram sem precisar de um atendente.
                  {m.serie_parcial && " Período cortado por volume; o detalhe está em Relatórios."}
                </p>
              )}
            </div>
            <div className="space-y-3">
              <ConversasAgora a={m.atendimento} admin={admin} />
              {m.agenda_hoje && <AgendaDeHoje agenda={m.agenda_hoje} />}
            </div>
          </div>

          {admin && <Operacao m={m} />}

          {admin && m.agenda.pendentes > 0 && !m.alertas.some((a) => a.tipo === "atividades") && (
            <Link to="/app/atividades"
              className="flex items-center gap-2 text-xs text-ink-3 hover:text-ink px-1">
              <CheckSquareOffset size={13} />
              {plural(m.agenda.hoje, "atividade", "atividades")} para hoje,{" "}
              {plural(m.agenda.pendentes, "pendente", "pendentes")} no total
              <ArrowRight size={11} weight="bold" />
            </Link>
          )}

          {!admin && (
            <p className="text-xs text-ink-3 px-1">
              Os números do painel contam só as conexões de WhatsApp liberadas para você.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
