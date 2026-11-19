import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import Modal from "@/components/ui/Modal";
import { useAcao } from "@/hooks/useAcao";
import { formatBRL } from "@/lib/currency";
import { MARCAS, valida as validaMarca } from "@/lib/marca";
import { rotuloPapel } from "@/lib/papeis";
import SerieDiaria from "@/components/reports/SerieDiaria";
import { haQuanto, plural } from "@/components/painel/Indicadores";
import {
  BarraIA, EmDia, IconeNivel, SENHA_MIN, SeloMarca, compacto, copiar, dataHora,
  CARENCIA_DIAS, apagaEm, descreverAtividade, detalheDaEmpresa, dolar, gerarSenha, nivelDaEmpresa, numero,
  porQue, rotuloDoProblema,
} from "@/components/superadmin/comum";
import {
  ArrowsClockwise, Copy, Eye, EyeSlash, Key, PauseCircle, PlayCircle, SignIn, Trash,
  ArrowCounterClockwise, Warning, WhatsappLogo,
} from "@phosphor-icons/react";

/**
 * A ficha de uma empresa para o super admin, em abas.
 *
 * Tudo o que antes exigia entrar em modo suporte para descobrir ou resolver:
 * como a operação está (Resumo), quem é a equipe e quando entrou pela última
 * vez, com a troca de senha de quem esqueceu (Equipe), o estado de cada
 * número (WhatsApp), nome, marca, teto de IA e retenção de mídia
 * (Configurações) e o que aconteceu na empresa (Histórico). A aba aberta fica
 * na URL (`?aba=`), para um alerta levar direto ao lugar certo.
 */

const ABAS = [
  { id: "resumo", rotulo: "Resumo" },
  { id: "equipe", rotulo: "Equipe" },
  { id: "whatsapp", rotulo: "WhatsApp" },
  { id: "config", rotulo: "Configurações" },
  { id: "historico", rotulo: "Histórico" },
];

const seriesConversas = [
  { chave: "automatico", rotulo: "Só robô ou IA", slot: 1 },
  { chave: "humano", rotulo: "Com atendente", slot: 2 },
];

// Atalhos de teto mensal de IA, em tokens. Uma conversa de atendimento com
// base de conhecimento média gasta na casa dos milhares de tokens.
const TETOS_IA = [1_000_000, 5_000_000, 20_000_000];

const RETENCOES = [
  { valor: "", rotulo: "Padrão do servidor" },
  { valor: "30", rotulo: "30 dias" },
  { valor: "90", rotulo: "90 dias" },
  { valor: "180", rotulo: "180 dias" },
  { valor: "365", rotulo: "1 ano" },
  { valor: "0", rotulo: "Nunca apagar" },
];

function Numero({ rotulo, valor, nota }) {
  return (
    <div className="border border-line rounded-lg px-3 py-2.5">
      <div className="text-[11px] text-ink-3">{rotulo}</div>
      <div className="font-heading text-xl font-black tracking-tight mt-0.5">{valor}</div>
      {nota && <div className="text-[11px] text-ink-3 mt-0.5 truncate">{nota}</div>}
    </div>
  );
}

function Titulo({ children, acao }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <h3 className="text-xs font-bold uppercase tracking-wider text-ink-3">{children}</h3>
      {acao}
    </div>
  );
}

// --- Resumo ---------------------------------------------------------------

function Resumo({ e, irPara }) {
  const s = e.saude || {};
  const r = e.resumo || {};
  const problemas = s.problemas || [];
  return (
    <div className="space-y-5">
      {problemas.length > 0 ? (
        <div className="border border-line rounded-lg divide-y divide-line">
          {problemas.map((p) => {
            const det = detalheDaEmpresa(p.tipo, p);
            return (
              <div key={p.tipo} className="flex items-start gap-3 px-3 py-2.5">
                <span className="mt-0.5"><IconeNivel nivel={p.nivel} /></span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{rotuloDoProblema(p)}{det ? ` · ${det}` : ""}</div>
                  <div className="text-xs text-ink-3">{porQue(p.tipo)}</div>
                </div>
                {(p.tipo === "ia_no_teto" || p.tipo === "ia_perto_teto") && (
                  <button onClick={() => irPara("config")} className="text-xs font-medium text-ink-2 hover:text-ink shrink-0">
                    Ajustar limite
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ) : e.status === "active" ? (
        <div className="border border-line rounded-lg px-3 py-2.5"><EmDia /></div>
      ) : null}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Numero rotulo="Mensagens · 7d" valor={numero(s.mensagens_7d)}
          nota={s.ultima_mensagem ? `última ${haQuanto(s.ultima_mensagem)}` : "nada em 30 dias"} />
        <Numero rotulo="Leads · 7d" valor={numero(s.leads_7d)}
          nota={`${numero(s.leads_7d_anterior)} na semana anterior`} />
        <Numero rotulo="Vendas · 30d" valor={numero(s.vendas_30d)}
          nota={s.vendas_30d_valor > 0 ? formatBRL(s.vendas_30d_valor) : null} />
        <Numero rotulo="Conversas abertas" valor={numero(r.conversas_abertas)} nota="aguardando ou em atendimento" />
        <Numero rotulo="Contatos na base" valor={numero(r.contatos)} />
        <Numero rotulo="Negócios abertos" valor={numero(r.negocios_abertos)} />
        <Numero rotulo="Veículos no estoque" valor={numero(r.veiculos)}
          nota={r.veiculos ? `${numero(r.veiculos_disponiveis)} disponíveis` : null} />
        <Numero rotulo="Disparos no mês" valor={numero(r.disparos_mes)}
          nota={plural(r.campanhas || 0, "campanha", "campanhas")} />
      </div>

      <SerieDiaria titulo="Conversas novas por dia · 14 dias" dados={e.serie || []}
        series={seriesConversas} altura={160} />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="border border-line rounded-lg p-3">
          <Titulo acao={<button onClick={() => irPara("config")} className="text-xs text-ink-3 hover:text-ink">Limite</button>}>
            IA neste mês
          </Titulo>
          <BarraIA ia={s.ia} compactar={false} />
          <div className="text-xs text-ink-3 mt-2">
            {dolar(s.ia?.custo_usd)} pagos pela plataforma
            {s.ia && s.ia.tokens > s.ia.tokens_plataforma
              ? ` · ${compacto(s.ia.tokens - s.ia.tokens_plataforma)} tokens na chave do cliente` : ""}
            {` · ${plural(r.agentes_ativos || 0, "agente ativo", "agentes ativos")}`}
          </div>
        </div>
        <div className="border border-line rounded-lg p-3">
          <Titulo>Automação</Titulo>
          <div className="text-sm">{plural(r.robos || 0, "robô de fluxo", "robôs de fluxo")}</div>
          <div className="text-sm">{plural(r.agentes_ativos || 0, "agente de IA ativo", "agentes de IA ativos")}</div>
          <div className="text-xs text-ink-3 mt-1">
            {plural(s.conversas_7d || 0, "conversa nova", "conversas novas")} na semana
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Equipe ---------------------------------------------------------------

/**
 * Senha nova para alguém da empresa. Mesmo cuidado da criação: a senha só
 * existe agora (o banco guarda o hash), então o passo seguinte é copiar, e as
 * sessões abertas daquela pessoa caem.
 */
function NovaSenha({ empresa, usuario, onFechar }) {
  const [senha, setSenha] = useState(gerarSenha);
  const [ver, setVer] = useState(true);
  const [feita, setFeita] = useState(false);
  const [salvar, salvando] = useAcao(async () => {
    try {
      await api.post(`/admin/tenants/${empresa.id}/users/${usuario.id}/senha`, { password: senha });
      setFeita(true);
    } catch (ex) {
      const d = ex.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Não foi possível trocar a senha");
    }
  });
  const bloco = [`Acesso ao painel ${empresa.name}`, `Endereço: ${window.location.origin}/login`,
    `E-mail: ${usuario.email}`, `Senha: ${senha}`].join("\n");

  if (feita) {
    return (
      <div className="mt-2 border border-warning bg-warning-soft rounded-lg p-3 space-y-2" data-testid="senha-redefinida">
        <div className="text-sm"><b>Senha trocada.</b> Copie agora: ela não aparece de novo. As sessões abertas de {usuario.name} foram encerradas.</div>
        <div className="font-mono text-sm bg-surface border border-line rounded-md px-3 py-2 break-all">{senha}</div>
        <div className="flex gap-2">
          <button className="zz-btn text-xs" onClick={() => copiar(bloco, "Acesso copiado")}>
            <Copy size={13} weight="bold" /> Copiar acesso completo
          </button>
          <button className="zz-btn zz-btn-secondary text-xs" onClick={onFechar}>Concluir</button>
        </div>
      </div>
    );
  }
  return (
    <div className="mt-2 border border-line bg-surface-2 rounded-lg p-3 space-y-2">
      <div className="text-xs text-ink-2">Nova senha para <b>{usuario.email}</b>. Mínimo de {SENHA_MIN} caracteres.</div>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input className="zz-input pr-9 font-mono text-sm" type={ver ? "text" : "password"}
            autoComplete="new-password" minLength={SENHA_MIN} value={senha}
            onChange={(ev) => setSenha(ev.target.value)} data-testid="nova-senha-input" />
          <button type="button" onClick={() => setVer(!ver)} title={ver ? "Esconder" : "Mostrar"}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink p-1">
            {ver ? <EyeSlash size={15} weight="bold" /> : <Eye size={15} weight="bold" />}
          </button>
        </div>
        <button type="button" className="zz-btn zz-btn-secondary text-xs" onClick={() => setSenha(gerarSenha())}>
          <ArrowsClockwise size={13} weight="bold" /> Gerar
        </button>
      </div>
      <div className="flex gap-2 justify-end">
        <button className="zz-btn zz-btn-secondary text-xs" onClick={onFechar}>Cancelar</button>
        <button className="zz-btn text-xs" disabled={salvando || senha.length < SENHA_MIN} onClick={salvar}
          data-testid="nova-senha-salvar">
          {salvando ? "Trocando…" : "Trocar a senha"}
        </button>
      </div>
    </div>
  );
}

function Equipe({ e }) {
  const [trocando, setTrocando] = useState(null);
  const ordenada = [...e.usuarios].sort((a, b) =>
    (a.role === "tenant_admin" ? 0 : 1) - (b.role === "tenant_admin" ? 0 : 1));
  return (
    <div>
      <Titulo>{plural(e.usuarios.length, "pessoa", "pessoas")}</Titulo>
      <ul className="border border-line rounded-lg divide-y divide-line">
        {e.usuarios.length === 0 && (
          <li className="px-3 py-3 text-sm text-danger">Nenhum usuário: ninguém consegue entrar nesta empresa.</li>
        )}
        {ordenada.map((u) => (
          <li key={u.id} className="px-3 py-2.5">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm truncate flex items-center gap-2">
                  <span className="font-medium">{u.name}</span>
                  <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full border ${
                    u.role === "tenant_admin" ? "border-info text-info bg-info-soft" : "border-line text-ink-3"}`}>
                    {rotuloPapel(u.role)}
                  </span>
                  {u.status === "suspended" && <span className="text-xs text-danger">suspenso</span>}
                </div>
                <div className="text-xs text-ink-3 font-mono truncate">{u.email}</div>
              </div>
              <div className="text-right shrink-0 hidden sm:block">
                <div className={`text-xs ${u.ultimo_acesso ? "text-ink-2" : "text-ink-3"}`}>
                  {u.ultimo_acesso ? `entrou ${haQuanto(u.ultimo_acesso)}` : "sem acesso registrado"}
                </div>
                <div className="text-[11px] text-ink-3">
                  desde {new Date(u.created_at).toLocaleDateString("pt-BR")}
                </div>
              </div>
              <button onClick={() => copiar(u.email, "Email copiado")} title="Copiar email"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2">
                <Copy size={14} />
              </button>
              <button onClick={() => setTrocando(trocando === u.id ? null : u.id)} title="Definir nova senha"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2"
                data-testid={`trocar-senha-${u.id}`}>
                <Key size={14} />
              </button>
            </div>
            {trocando === u.id && (
              <NovaSenha empresa={e} usuario={u} onFechar={() => setTrocando(null)} />
            )}
          </li>
        ))}
      </ul>
      <p className="text-xs text-ink-3 mt-2">
        A senha não fica guardada, só o hash. Pela chave ao lado de cada pessoa dá para definir uma nova,
        que aparece uma vez para você copiar. Último acesso é registrado desde 18/11/2026.
      </p>
    </div>
  );
}

// --- WhatsApp -------------------------------------------------------------

function Whatsapp({ e, entrar, entrando }) {
  return (
    <div>
      <Titulo acao={
        <button onClick={() => entrar(e, "/app/whatsapp")} disabled={entrando}
          className="text-xs text-ink-3 hover:text-ink flex items-center gap-1">
          <SignIn size={12} weight="bold" /> Abrir conexões
        </button>
      }>Conexões</Titulo>
      {e.conexoes.length === 0 ? (
        <div className="text-sm text-ink-3 border border-line rounded-lg px-3 py-6 text-center">
          Nenhuma conexão cadastrada. Sem número, a empresa não recebe nem envia nada.
        </div>
      ) : (
        <ul className="border border-line rounded-lg divide-y divide-line">
          {e.conexoes.map((c) => {
            const noAr = c.status === "conectado";
            return (
              <li key={c.id} className="flex items-center gap-3 px-3 py-2.5">
                <WhatsappLogo size={18} weight={noAr ? "fill" : "regular"} className={noAr ? "text-success" : "text-danger"} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate">{c.nome || "Sem nome"}</div>
                  <div className="text-xs text-ink-3 truncate">
                    {[c.numero_exibicao || c.numero, c.ultimo_erro].filter(Boolean).join(" · ") || "sem número"}
                  </div>
                </div>
                <span className={`text-xs font-medium ${noAr ? "text-success" : "text-danger"}`}>
                  {noAr ? "no ar" : "fora do ar"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// --- Configurações --------------------------------------------------------

function Config({ e, mudar, mudando, excluir, excluindo }) {
  const [nome, setNome] = useState(e.name);
  const [teto, setTeto] = useState(e.limite_tokens_ia_mes ? String(e.limite_tokens_ia_mes) : "");
  const [confirma, setConfirma] = useState("");
  useEffect(() => {
    setNome(e.name);
    setTeto(e.limite_tokens_ia_mes ? String(e.limite_tokens_ia_mes) : "");
  }, [e.name, e.limite_tokens_ia_mes]);

  const ativa = e.status === "active";
  const tetoNum = teto.trim() === "" ? null : Number(teto.replace(/\D/g, ""));
  const tetoMudou = (tetoNum || null) !== (e.limite_tokens_ia_mes || null);
  const retencao = e.retencao_midia_dias == null ? "" : String(e.retencao_midia_dias);

  return (
    <div className="space-y-6">
      <section>
        <Titulo>Nome da empresa</Titulo>
        <form className="flex gap-2" onSubmit={(ev) => { ev.preventDefault(); mudar({ name: nome.trim() }, "Nome atualizado"); }}>
          <input className="zz-input text-sm" value={nome} onChange={(ev) => setNome(ev.target.value)}
            minLength={2} maxLength={120} data-testid="empresa-nome-input" />
          <button className="zz-btn zz-btn-secondary text-xs shrink-0" disabled={mudando || nome.trim().length < 2 || nome.trim() === e.name}>
            Salvar
          </button>
        </form>
      </section>

      <section>
        <Titulo>Marca do painel</Titulo>
        <select className="zz-input h-9 text-sm" value={validaMarca(e.marca)} disabled={mudando}
          data-testid="empresa-marca"
          onChange={(ev) => ev.target.value !== validaMarca(e.marca)
            && mudar({ marca: ev.target.value },
              `${e.name} agora vê o painel ${MARCAS[ev.target.value].nome}. Vale no próximo carregamento de quem estiver dentro.`)}>
          {Object.values(MARCAS).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
        </select>
      </section>

      <section>
        <Titulo>Limite mensal de IA (tokens)</Titulo>
        <p className="text-xs text-ink-3 mb-2">
          Vale só para o que roda na chave de IA da plataforma, que é custo nosso. Agente com a chave do
          próprio cliente não tem limite. Ao bater o limite, o agente para e as conversas vão para a fila.
          Vazio = sem limite.
        </p>
        <div className="flex gap-2 flex-wrap">
          <input className="zz-input text-sm font-mono w-48" inputMode="numeric" placeholder="sem limite"
            value={teto ? Number(teto.replace(/\D/g, "") || 0).toLocaleString("pt-BR") : ""}
            onChange={(ev) => setTeto(ev.target.value.replace(/\D/g, ""))} data-testid="empresa-teto-ia" />
          {TETOS_IA.map((v) => (
            <button key={v} type="button" onClick={() => setTeto(String(v))}
              className={`text-xs px-2.5 rounded-md border ${tetoNum === v ? "border-info bg-info-soft ring-1 ring-info" : "border-line hover:border-line-strong"}`}>
              {compacto(v)}
            </button>
          ))}
          <button type="button" onClick={() => setTeto("")}
            className={`text-xs px-2.5 rounded-md border ${tetoNum === null ? "border-info bg-info-soft ring-1 ring-info" : "border-line hover:border-line-strong"}`}>
            Sem limite
          </button>
          <button className="zz-btn text-xs" disabled={mudando || !tetoMudou}
            onClick={() => mudar({ limite_tokens_ia_mes: tetoNum || null },
              tetoNum ? `Limite de IA: ${numero(tetoNum)} tokens por mês` : "Limite de IA removido")}
            data-testid="empresa-teto-salvar">
            Salvar limite
          </button>
        </div>
        {e.saude?.ia && (
          <div className="mt-3 max-w-sm">
            <div className="text-[11px] text-ink-3 mb-1">Uso neste mês</div>
            <BarraIA ia={e.saude.ia} compactar={false} />
          </div>
        )}
      </section>

      <section>
        <Titulo>Retenção de mídia</Titulo>
        <p className="text-xs text-ink-3 mb-2">
          Por quanto tempo fotos, áudios e documentos das conversas ficam guardados. O texto das mensagens não expira.
        </p>
        <select className="zz-input h-9 text-sm w-auto" value={retencao} disabled={mudando}
          data-testid="empresa-retencao"
          onChange={(ev) => mudar({ retencao_midia_dias: ev.target.value === "" ? null : Number(ev.target.value) },
            "Retenção de mídia atualizada")}>
          {!RETENCOES.some((r) => r.valor === retencao) && <option value={retencao}>{retencao} dias</option>}
          {RETENCOES.map((r) => <option key={r.valor} value={r.valor}>{r.rotulo}</option>)}
        </select>
      </section>

      <section className="border border-danger rounded-lg p-4 space-y-4">
        <Titulo>Zona de risco</Titulo>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="text-sm max-w-md">
            <div className="font-medium">{ativa ? "Suspender a empresa" : "Reativar a empresa"}</div>
            <div className="text-xs text-ink-3">
              {ativa
                ? "A equipe perde o acesso na hora. Nada é apagado, e dá para reativar depois."
                : "A equipe volta a entrar com as mesmas senhas."}
            </div>
          </div>
          <button onClick={() => mudar({ status: ativa ? "suspended" : "active" },
            ativa ? "Empresa suspensa: a equipe dela perde o acesso na hora" : "Empresa reativada")}
            disabled={mudando} className="zz-btn zz-btn-secondary text-xs" data-testid="empresa-suspender">
            {ativa ? <><PauseCircle size={14} weight="bold" /> Suspender</> : <><PlayCircle size={14} weight="bold" /> Reativar</>}
          </button>
        </div>
        <div className="border-t border-line pt-4">
          <div className="text-sm font-medium flex items-center gap-1.5 text-danger">
            <Warning size={15} weight="fill" /> Excluir a empresa e todos os dados
          </div>
          <div className="text-xs text-ink-3 mt-0.5 mb-2">
            A equipe perde o acesso na hora e a empresa vai para <b className="text-ink">Excluídas</b>, onde
            pode ser restaurada por {CARENCIA_DIAS} dias. Depois disso, conversas, contatos, funil, estoque,
            agenda, agentes e usuários são apagados de vez.
            Para confirmar, digite o nome exato: <b className="text-ink">{e.name}</b>
          </div>
          <div className="flex gap-2">
            <input className="zz-input text-sm" value={confirma} onChange={(ev) => setConfirma(ev.target.value)}
              placeholder={e.name} data-testid="empresa-excluir-confirma" />
            <button onClick={excluir} disabled={excluindo || confirma.trim() !== e.name}
              className="zz-btn zz-btn-danger text-xs shrink-0" data-testid="empresa-excluir">
              <Trash size={14} weight="bold" /> Excluir
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

// --- Histórico ------------------------------------------------------------

function Historico({ itens }) {
  if (!itens?.length) {
    return <div className="text-sm text-ink-3 border border-line rounded-lg px-3 py-6 text-center">Nenhuma ação registrada nesta empresa.</div>;
  }
  return (
    <ol className="border border-line rounded-lg divide-y divide-line">
      {itens.map((a, i) => (
        <li key={i} className="flex items-start gap-3 px-3 py-2.5">
          <span className="font-mono text-[11px] text-ink-3 w-24 shrink-0 pt-0.5">{dataHora(a.em)}</span>
          <div className="text-sm min-w-0">
            <span className="font-medium">{a.ator || "alguém"}</span>{" "}
            <span className="text-ink-2">{descreverAtividade(a)}</span>
            {a.suporte && a.acao !== "suporte.entrar" && <span className="text-xs text-ink-3"> · em modo suporte</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

// --------------------------------------------------------------------------

export default function EmpresaDetalhe({ id, aba = "resumo", onAba, onFechar, onMudou, entrar, entrando }) {
  const [e, setE] = useState(null);

  const carregar = useCallback(
    () => api.get(`/admin/tenants/${id}`).then((r) => setE(r.data))
      .catch(() => toast.error("Não foi possível carregar a empresa")),
    [id],
  );
  useEffect(() => { carregar(); }, [carregar]);

  const [mudar, mudando] = useAcao(async (campos, aviso) => {
    try {
      await api.patch(`/admin/tenants/${id}`, campos);
      toast.success(aviso);
      await carregar();
      onMudou();
    } catch (ex) {
      const d = ex.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Não foi possível salvar");
    }
  });

  const [excluir, excluindo] = useAcao(async () => {
    try {
      const { data } = await api.delete(`/admin/tenants/${id}`);
      const quando = data?.apagar_em ? new Date(data.apagar_em).toLocaleDateString("pt-BR") : null;
      toast.success(quando
        ? `Empresa excluída. Dá para restaurar em Empresas → Excluídas até ${quando}.`
        : "Empresa excluída");
      onMudou();
      onFechar();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Não foi possível excluir");
    }
  });

  const [restaurar, restaurando] = useAcao(async () => {
    try {
      await api.post(`/admin/tenants/${id}/restaurar`);
      toast.success("Empresa restaurada, com todos os dados");
      await carregar();
      onMudou();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Não foi possível restaurar");
    }
  });

  if (!e) {
    return (
      <Modal titulo="Empresa" onFechar={onFechar} largo>
        <div className="text-sm text-ink-3 py-8 text-center">Carregando…</div>
      </Modal>
    );
  }

  const nivel = nivelDaEmpresa(e);
  const admin = e.usuarios.find((u) => u.role === "tenant_admin");
  const atual = ABAS.some((a) => a.id === aba) ? aba : "resumo";
  const contador = {
    equipe: e.usuarios.length,
    whatsapp: e.conexoes.length,
  };

  return (
    <Modal
      titulo={e.name}
      descricao={[
        e.excluida_em ? "Excluída" : nivel === "suspensa" ? "Suspensa" : "Ativa",
        `cliente desde ${new Date(e.created_at).toLocaleDateString("pt-BR")}`,
        admin?.email,
      ].filter(Boolean).join(" · ")}
      onFechar={onFechar}
      largo
      testId="empresa-detalhe"
      corpoClasse="space-y-4"
      rodape={
        <div className="flex items-center justify-between gap-2 flex-1 flex-wrap">
          <SeloMarca marca={e.marca} />
          <div className="flex gap-2">
            <button onClick={() => entrar(e)} disabled={entrando} className="zz-btn text-xs"
              data-testid="empresa-entrar">
              <SignIn size={14} weight="bold" /> Entrar na empresa
            </button>
          </div>
        </div>
      }
    >
      {e.excluida_em && (
        <div className="border border-danger bg-danger-soft rounded-lg p-3 flex items-center justify-between gap-3 flex-wrap"
          data-testid="empresa-excluida">
          <div className="text-sm">
            <div className="font-medium text-danger flex items-center gap-1.5">
              <Warning size={15} weight="fill" /> Empresa excluída
            </div>
            <div className="text-xs text-ink-2 mt-0.5">
              Excluída em {new Date(e.excluida_em).toLocaleDateString("pt-BR")}
              {e.excluida_por ? ` por ${e.excluida_por}` : ""}. Todos os dados continuam guardados e
              serão apagados de vez em <b>{apagaEm(e).toLocaleDateString("pt-BR")}</b>.
            </div>
          </div>
          <button onClick={restaurar} disabled={restaurando} className="zz-btn text-xs shrink-0"
            data-testid="empresa-restaurar">
            <ArrowCounterClockwise size={14} weight="bold" /> Restaurar empresa
          </button>
        </div>
      )}

      <div className="flex gap-1 border-b border-line -mt-1 overflow-x-auto" role="tablist">
        {ABAS.map((a) => (
          <button key={a.id} role="tab" aria-selected={atual === a.id} onClick={() => onAba?.(a.id)}
            data-testid={`aba-${a.id}`}
            className={`text-sm px-3 py-2 -mb-px border-b-2 whitespace-nowrap ${atual === a.id
              ? "border-brand text-ink font-semibold" : "border-transparent text-ink-3 hover:text-ink"}`}>
            {a.rotulo}
            {contador[a.id] != null && <span className="ml-1 font-mono text-[11px] text-ink-3">{contador[a.id]}</span>}
            {a.id === "resumo" && (e.saude?.problemas?.length || 0) > 0 && (
              <span className={`ml-1.5 inline-block w-1.5 h-1.5 rounded-full align-middle ${nivel === "alto" ? "bg-danger" : "bg-warning"}`} />
            )}
          </button>
        ))}
      </div>

      {atual === "resumo" && <Resumo e={e} irPara={onAba} />}
      {atual === "equipe" && <Equipe e={e} />}
      {atual === "whatsapp" && <Whatsapp e={e} entrar={entrar} entrando={entrando} />}
      {atual === "config" && (e.excluida_em
        ? <div className="text-sm text-ink-3 border border-line rounded-lg px-3 py-6 text-center">
            Restaure a empresa para mudar as configurações.
          </div>
        : <Config e={e} mudar={mudar} mudando={mudando} excluir={excluir} excluindo={excluindo} />)}
      {atual === "historico" && <Historico itens={e.historico} />}
    </Modal>
  );
}
