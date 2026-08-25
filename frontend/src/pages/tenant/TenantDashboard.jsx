import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatBRL } from "@/lib/currency";
import {
  Headset, Funnel, CheckSquareOffset, Megaphone, UsersThree, WhatsappLogo,
  Warning, ArrowRight,
} from "@phosphor-icons/react";

// Mesmos cortes de fuso da agenda: quem sabe em que fuso está é o navegador.
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

function Bloco({ titulo, icone: Icone, para, children }) {
  return (
    <div className="border border-slate-200 bg-white">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <Icone size={15} weight="bold" className="text-slate-500" />
          <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
            {titulo}
          </span>
        </div>
        {para && (
          <Link to={para} className="text-slate-400 hover:text-slate-900">
            <ArrowRight size={13} weight="bold" />
          </Link>
        )}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function Numero({ rotulo, valor, destaque, alerta }) {
  return (
    <div>
      <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">{rotulo}</div>
      <div className={`font-heading font-black tracking-tighter ${
        destaque ? "text-3xl" : "text-2xl"
      } ${alerta ? "text-red-600" : ""}`}>
        {valor}
      </div>
    </div>
  );
}

export default function TenantDashboard() {
  const { user } = useAuth();
  const [m, setMetrics] = useState(null);
  const isAdmin = user?.role === "tenant_admin";

  useEffect(() => {
    api.get("/dashboard/metrics", {
      params: { hoje_ate: fimDoDia(), semana_ate: fimDaSemana() },
    }).then((r) => setMetrics(r.data)).catch(() => {});
  }, []);

  if (!isAdmin) {
    return (
      <div className="p-8" data-testid="tenant-dashboard">
        <div className="mb-8">
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Painel</div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Olá, {user?.name}.</h1>
          <p className="text-slate-600 mt-2">Suas conversas estão na Central de Atendimento.</p>
        </div>
        {m && (
          <div className="grid grid-cols-3 gap-2 max-w-2xl">
            <div className="border border-slate-200 bg-white p-4">
              <Numero rotulo="Aguardando na fila" valor={m.atendimento.aguardando}
                alerta={m.atendimento.aguardando > 0} destaque />
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <Numero rotulo="Suas atividades atrasadas" valor={m.agenda.atrasadas}
                alerta={m.agenda.atrasadas > 0} destaque />
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <Numero rotulo="Para hoje" valor={m.agenda.hoje} destaque />
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="p-8 max-w-6xl" data-testid="tenant-dashboard">
      <div className="mb-6">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Painel</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Olá, {user?.name}.</h1>
        <p className="text-slate-600 mt-2 text-sm">Como está a operação agora.</p>
      </div>

      {!m ? (
        <div className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500 py-8">
          Carregando…
        </div>
      ) : (
        <>
          {(m.atendimento.aguardando > 0 || m.agenda.atrasadas > 0) && (
            <div className="border-2 border-amber-400 bg-amber-50 p-3 mb-4 flex items-center gap-3 flex-wrap">
              <Warning size={16} weight="bold" className="text-amber-700 shrink-0" />
              {m.atendimento.aguardando > 0 && (
                <Link to="/app/inbox" className="text-sm text-slate-800 hover:underline">
                  <strong>{m.atendimento.aguardando}</strong> conversa(s) esperando atendimento
                </Link>
              )}
              {m.agenda.atrasadas > 0 && (
                <Link to="/app/atividades" className="text-sm text-slate-800 hover:underline">
                  <strong>{m.agenda.atrasadas}</strong> atividade(s) atrasada(s)
                </Link>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 mb-3">
            <Bloco titulo="Atendimento" icone={Headset} para="/app/inbox">
              <div className="grid grid-cols-4 gap-3">
                <Numero rotulo="Com o robô" valor={m.atendimento.bot} />
                <Numero rotulo="Na fila" valor={m.atendimento.aguardando}
                  alerta={m.atendimento.aguardando > 0} />
                <Numero rotulo="Em atendimento" valor={m.atendimento.em_atendimento} />
                <Numero rotulo="Finalizadas" valor={m.atendimento.finalizado} />
              </div>
              <div className="text-[11px] text-slate-500 mt-3">
                {m.atendimento.mensagens_30d.toLocaleString("pt-BR")} mensagens nos últimos 30 dias
              </div>
            </Bloco>

            <Bloco titulo="Funil" icone={Funnel} para="/app/funil">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">
                    Em aberto
                  </div>
                  <div className="font-heading text-2xl font-black tracking-tighter">
                    {formatBRL(m.funil.aberto.valor)}
                  </div>
                  <div className="text-[10px] text-slate-500">{m.funil.aberto.n} negócio(s)</div>
                </div>
                <div>
                  <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">
                    Ganho no mês
                  </div>
                  <div className="font-heading text-2xl font-black tracking-tighter text-green-700">
                    {formatBRL(m.funil.ganho_mes.valor)}
                  </div>
                  <div className="text-[10px] text-slate-500">{m.funil.ganho_mes.n} fechado(s)</div>
                </div>
              </div>
            </Bloco>

            <Bloco titulo="Agenda" icone={CheckSquareOffset} para="/app/atividades">
              <div className="grid grid-cols-4 gap-3">
                <Numero rotulo="Atrasadas" valor={m.agenda.atrasadas}
                  alerta={m.agenda.atrasadas > 0} />
                <Numero rotulo="Hoje" valor={m.agenda.hoje} />
                <Numero rotulo="7 dias" valor={m.agenda.semana} />
                <Numero rotulo="Pendentes" valor={m.agenda.pendentes} />
              </div>
            </Bloco>

            <Bloco titulo="Campanhas" icone={Megaphone} para="/app/campanhas">
              <div className="grid grid-cols-2 gap-3">
                <Numero rotulo="Em andamento" valor={m.campanhas.em_andamento} />
                <Numero rotulo="Disparos no mês"
                  valor={m.campanhas.disparos_mes.toLocaleString("pt-BR")} />
              </div>
            </Bloco>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Bloco titulo="Base" icone={UsersThree} para="/app/contacts">
              <Numero rotulo="Contatos" valor={m.base.contatos.toLocaleString("pt-BR")} destaque />
            </Bloco>
            <Bloco titulo="WhatsApp" icone={WhatsappLogo} para="/app/whatsapp">
              <Numero rotulo="Conexões conectadas" valor={m.base.conexoes_conectadas} destaque
                alerta={m.base.conexoes_conectadas === 0} />
            </Bloco>
            <Bloco titulo="Robôs" icone={Headset} para="/app/bots">
              <Numero rotulo="Ativos" valor={m.base.bots_ativos} destaque />
            </Bloco>
          </div>
        </>
      )}
    </div>
  );
}
