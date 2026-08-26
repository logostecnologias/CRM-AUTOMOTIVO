import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  CaretLeft, CaretRight, Plus, Robot, Sparkle, User, XCircle, CheckCircle,
  Prohibit, CalendarBlank,
} from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { confirmToast } from "@/lib/confirm-toast";
import { useAuth } from "@/context/AuthContext";
import { useAcao } from "@/hooks/useAcao";
import NovoAgendamento from "@/components/agenda/NovoAgendamento";
import { Servicos, Profissionais } from "@/components/agenda/Catalogo";
import Configuracao from "@/components/agenda/Configuracao";
import {
  ORIGEM, STATUS, diaDe, hojeNaEmpresa, hora, instanteDoDia, moeda, rotuloDia, somaDias,
} from "@/components/agenda/comum";

// A agenda da empresa.
//
// **Todo mundo da equipe vê a agenda inteira**: não só a própria. Quem atende o
// telefone precisa poder dizer "a Ana tem às 15h", e um recorte por profissional
// transformaria a tela em algo que só o dono usa. O recorte existe como filtro,
// e é ele que faz "minha agenda" caber num clique para quem está ligado a um
// profissional. Configurar (serviços, grade, feriados) continua sendo do admin,
// pela mesma regra do resto do CRM: operar é de quem atende, configurar é de
// quem responde pela operação.

const ABAS_BASE = [["agenda", "Agenda"]];
const ABAS_ADMIN = [["servicos", "Serviços"], ["profissionais", "Profissionais"],
                    ["config", "Configuração"]];

const ICONE_ORIGEM = { manual: User, bot: Robot, ia: Sparkle };

export default function AgendaPage() {
  const { user } = useAuth();
  const admin = user?.role === "tenant_admin";
  const [aba, setAba] = useState("agenda");
  const [config, setConfig] = useState(null);
  const [servicos, setServicos] = useState([]);
  const [recursos, setRecursos] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [criando, setCriando] = useState(false);

  const carregarCatalogo = useCallback(() => {
    api.get("/agenda/config").then((r) => setConfig(r.data)).catch(() => {});
    api.get("/agenda/services").then((r) => setServicos(r.data)).catch(() => {});
    api.get("/agenda/resources").then((r) => setRecursos(r.data)).catch(() => {});
  }, []);

  useEffect(() => { carregarCatalogo(); }, [carregarCatalogo]);
  useEffect(() => {
    if (admin) api.get("/users").then((r) => setUsuarios(r.data)).catch(() => {});
  }, [admin]);

  const abas = admin ? [...ABAS_BASE, ...ABAS_ADMIN] : ABAS_BASE;
  const ativos = {
    servicos: servicos.filter((s) => s.ativo !== false),
    recursos: recursos.filter((r) => r.ativo !== false),
  };
  const pronto = ativos.servicos.length > 0 && ativos.recursos.length > 0;

  if (!config) {
    return <div className="zz-page text-sm text-ink-3">Carregando agenda…</div>;
  }

  return (
    <div className="zz-page" data-testid="agenda-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Agenda</h1>
          <p className="text-ink-2 mt-2 text-sm">
            Os horários marcados, seja pela recepção, pelo robô do WhatsApp ou pelo agente de IA.
            Horário marcado por qualquer um deles some da lista dos outros na hora.
          </p>
        </div>
        {aba === "agenda" && (
          <button className="zz-btn" data-testid="novo-agendamento-btn" disabled={!pronto}
            title={pronto ? "" : "Cadastre ao menos um serviço e um profissional"}
            onClick={() => setCriando(true)}>
            <Plus size={14} weight="bold" /> Novo agendamento
          </button>
        )}
      </div>

      <div className="flex gap-1 border-b border-line mb-6 overflow-x-auto">
        {abas.map(([id, label]) => (
          <button key={id} onClick={() => setAba(id)} data-testid={`aba-${id}`}
            className={`px-4 py-2.5 text-sm font-semibold whitespace-nowrap border-b-2 -mb-px transition-colors ${
              aba === id
                ? "border-info text-info"
                : "border-transparent text-ink-3 hover:text-ink"}`}>
            {label}
          </button>
        ))}
      </div>

      {aba === "agenda" && (
        <Quadro config={config} recursos={recursos} pronto={pronto}
          faltaCadastro={{ servicos: ativos.servicos.length, recursos: ativos.recursos.length }} />
      )}
      {aba === "servicos" && (
        <Servicos servicos={servicos} recursos={recursos} onMudou={carregarCatalogo} />
      )}
      {aba === "profissionais" && (
        <Profissionais recursos={recursos} usuarios={usuarios} config={config}
          onMudou={carregarCatalogo} />
      )}
      {aba === "config" && (
        <Configuracao config={config} onSalvo={carregarCatalogo} />
      )}

      {criando && (
        <NovoAgendamento servicos={ativos.servicos} recursos={ativos.recursos} fuso={config.fuso}
          onFechar={() => setCriando(false)}
          onSalvo={() => { setCriando(false); window.dispatchEvent(new Event("agenda:recarregar")); }} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quadro de horários
// ---------------------------------------------------------------------------

function Quadro({ config, recursos, pronto, faltaCadastro }) {
  const fuso = config.fuso;
  const [dia, setDia] = useState(() => hojeNaEmpresa(fuso));
  const [periodo, setPeriodo] = useState("dia");
  const [recursoId, setRecursoId] = useState("");
  const [itens, setItens] = useState([]);
  const [carregando, setCarregando] = useState(true);

  const dias = periodo === "dia" ? 1 : 7;

  const carregar = useCallback(() => {
    setCarregando(true);
    api.get("/agenda/appointments", {
      params: {
        de: instanteDoDia(dia, fuso),
        ate: instanteDoDia(somaDias(dia, dias - 1), fuso, true),
        resource_id: recursoId || undefined,
      },
    })
      .then((r) => setItens(r.data.items || []))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)))
      .finally(() => setCarregando(false));
  }, [dia, dias, fuso, recursoId]);

  useEffect(() => { carregar(); }, [carregar]);
  useEffect(() => {
    // O modal de marcação vive na página, acima deste componente; o evento é o
    // que o faz recarregar sem subir o estado da lista inteira para lá.
    const h = () => carregar();
    window.addEventListener("agenda:recarregar", h);
    return () => window.removeEventListener("agenda:recarregar", h);
  }, [carregar]);

  const [cancelar, cancelando] = useAcao(async (a) => {
    if (!(await confirmToast(
      `Cancelar o horário de ${a.contact_nome} em ${hora(a.inicio, fuso)}?`,
      { confirmLabel: "Cancelar horário" }))) return;
    try {
      await api.post(`/agenda/appointments/${a.id}/cancel`, null, { params: { avisar: true } });
      toast.success("Horário cancelado e contato avisado");
      carregar();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  const [mudarStatus, mudando] = useAcao(async (a, status) => {
    try {
      await api.patch(`/agenda/appointments/${a.id}/status`, { status });
      carregar();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  if (!pronto) {
    return (
      <div className="border border-dashed border-line rounded-xl p-10 text-center">
        <CalendarBlank size={28} weight="bold" className="mx-auto text-ink-3 mb-3" />
        <div className="font-semibold mb-1">A agenda ainda não está pronta</div>
        <p className="text-sm text-ink-2 max-w-lg mx-auto">
          Falta cadastrar {faltaCadastro.servicos === 0 && "ao menos um serviço"}
          {faltaCadastro.servicos === 0 && faltaCadastro.recursos === 0 && " e "}
          {faltaCadastro.recursos === 0 && "ao menos um profissional"}. Sem os dois não há
          horário livre para oferecer, nem na recepção, nem no WhatsApp.
        </p>
      </div>
    );
  }

  // Agrupado por dia e, dentro do dia, por profissional: é como quem olha a
  // agenda pensa ("o que a Ana tem hoje"), e é o recorte em que um buraco de
  // horário fica visível.
  const porDia = {};
  for (let i = 0; i < dias; i++) porDia[somaDias(dia, i)] = [];
  itens.forEach((a) => {
    const d = diaDe(a.inicio, fuso);
    (porDia[d] = porDia[d] || []).push(a);
  });

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-5">
        <div className="flex items-center gap-1">
          <button className="zz-btn-icon" data-testid="agenda-anterior"
            onClick={() => setDia(somaDias(dia, -dias))}>
            <CaretLeft size={16} weight="bold" />
          </button>
          <button className="zz-btn zz-btn-secondary text-xs"
            onClick={() => setDia(hojeNaEmpresa(fuso))}>Hoje</button>
          <button className="zz-btn-icon" data-testid="agenda-proximo"
            onClick={() => setDia(somaDias(dia, dias))}>
            <CaretRight size={16} weight="bold" />
          </button>
        </div>
        <div className="font-heading text-lg font-black tracking-tight">
          {periodo === "dia" ? rotuloDia(dia)
            : `${rotuloDia(dia)}, ${rotuloDia(somaDias(dia, 6))}`}
        </div>
        <div className="flex-1" />
        <select className="zz-input max-w-[150px]" value={periodo}
          onChange={(e) => setPeriodo(e.target.value)} data-testid="agenda-periodo">
          <option value="dia">Dia</option>
          <option value="semana">7 dias</option>
        </select>
        <select className="zz-input max-w-[220px]" value={recursoId}
          onChange={(e) => setRecursoId(e.target.value)} data-testid="agenda-filtro-recurso">
          <option value="">Todos os profissionais</option>
          {recursos.map((r) => <option key={r.id} value={r.id}>{r.nome}</option>)}
        </select>
      </div>

      {carregando ? (
        <div className="text-sm text-ink-3 py-10 text-center">Carregando…</div>
      ) : (
        <div className="space-y-5">
          {Object.keys(porDia).sort().map((d) => (
            <div key={d}>
              {periodo === "semana" && (
                <div className="text-xs font-bold uppercase tracking-wider text-ink-3 mb-2">
                  {rotuloDia(d)} · {porDia[d].length} horário(s)
                </div>
              )}
              {porDia[d].length === 0 ? (
                <div className="text-sm text-ink-3 border border-dashed border-line rounded-lg p-6 text-center">
                  Nenhum horário marcado.
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
                  {porDia[d].map((a) => (
                    <Cartao key={a.id} a={a} fuso={fuso} ocupado={cancelando || mudando}
                      onCancelar={() => cancelar(a)}
                      onStatus={(s) => mudarStatus(a, s)} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Cartao({ a, fuso, onCancelar, onStatus, ocupado }) {
  const st = STATUS[a.status] || STATUS.agendado;
  const IconeOrigem = ICONE_ORIGEM[a.origem] || User;
  const encerrado = ["cancelado", "concluido", "faltou"].includes(a.status);

  return (
    <div className={`border border-line rounded-xl p-4 bg-surface ${
      a.status === "cancelado" ? "opacity-60" : ""}`} data-testid="cartao-agendamento">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono font-black text-lg leading-none">
            {hora(a.inicio, fuso)}
            <span className="text-ink-3 font-normal text-xs ml-1.5">
{hora(a.fim, fuso)}
            </span>
          </div>
          <div className="font-semibold text-sm mt-1.5 truncate">{a.contact_nome}</div>
          <div className="text-[11px] font-mono text-ink-3">{a.contact_numero}</div>
        </div>
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full border shrink-0 ${st.classe}`}>
          {st.label}
        </span>
      </div>

      <div className="text-xs text-ink-2 mt-3">
        {a.service_nome}
        {a.preco ? ` · ${moeda(a.preco)}` : ""} · com <strong>{a.resource_nome}</strong>
      </div>
      {a.observacoes && <p className="text-[11px] text-ink-3 mt-1.5">{a.observacoes}</p>}

      <div className="flex items-center justify-between gap-2 mt-3 pt-3 border-t border-line">
        <span className="text-[10px] text-ink-3 flex items-center gap-1"
          title={ORIGEM[a.origem] || a.origem}>
          <IconeOrigem size={12} weight="bold" /> {ORIGEM[a.origem] || a.origem}
        </span>
        {!encerrado && (
          <div className="flex gap-1">
            <button className="zz-btn-icon" title="Marcar como atendido"
              data-testid="agendamento-concluir" disabled={ocupado} onClick={() => onStatus("concluido")}>
              <CheckCircle size={15} weight="bold" />
            </button>
            <button className="zz-btn-icon" title="Marcar falta"
              data-testid="agendamento-faltou" disabled={ocupado} onClick={() => onStatus("faltou")}>
              <Prohibit size={15} weight="bold" />
            </button>
            <button className="zz-btn-icon" title="Cancelar e avisar o contato"
              data-testid="agendamento-cancelar" disabled={ocupado} onClick={onCancelar}>
              <XCircle size={15} weight="bold" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
