import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Plus, PencilSimple, Trash, Code, ListBullets, Copy, ArrowsClockwise, WarningCircle,
} from "@phosphor-icons/react";
import api, { API, formatApiErrorDetail } from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import Modal from "@/components/ui/Modal";
import EscolhaDeModelo from "@/components/whatsapp/EscolhaDeModelo";
import { confirmToast } from "@/lib/confirm-toast";
import { t } from "@/lib/textos";

// Formulário de site: quem preenche a landing page vira contato aqui, com a
// origem do anúncio, e pode já cair no funil, na agenda do vendedor e no
// WhatsApp. Cada formulário tem um endereço com chave própria; a chave fica
// no código da página e só serve para criar lead naquele formulário.

// Funcao, nao constante: o texto depende da marca (lib/textos.js).
const modos = () => [
  ["agente", t("Agente de IA"), `O ${t("agente")} da conexão responde. Sem ${t("agente")} ligado, a conversa vai para a fila.`],
  ["bot", t("Robô"), `Um ${t("robô")} do editor começa do nó Início.`],
  ["fila", "Fila de atendimento", "Direto para a Central, para uma pessoa responder."],
];

const PRAZOS = [[5, "5 minutos"], [15, "15 minutos"], [30, "30 minutos"], [60, "1 hora"],
  [120, "2 horas"], [240, "4 horas"], [1440, "1 dia"]];

const STATUS = {
  recebida: { label: "Recebida", classe: "bg-success-soft text-success border-success" },
  repetida: { label: "Repetida", classe: "bg-surface-2 text-ink-2 border-line" },
  recusada: { label: "Recusada", classe: "bg-danger-soft text-danger border-danger" },
};

const WPP = {
  pendente: "Enviando…",
  enviando: "Enviando…",
  enviada: "Enviado",
  repetida: "Já tinha recebido",
  sem_modelo: "Sem modelo",
  falha: "Falhou",
};

const VAZIO = {
  nome: "",
  ativo: true,
  tags: [],
  responsavel_id: "",
  dominios: [],
  redirecionar_para: "",
  negocio: { ativo: false, pipeline_id: "", etapa_id: "", valor: 0, titulo: "" },
  tarefa: { ativo: false, prazo_min: 30, titulo: "" },
  whatsapp: {
    ativo: false, connection_id: "", mensagem: "", resposta_modo: "agente", bot_id: "",
    template: { nome: "", idioma: "pt_BR", variaveis: [] },
  },
};

function periodoDoMes() {
  const hoje = new Date();
  const de = new Date(hoje.getFullYear(), hoje.getMonth(), 1);
  const ate = new Date(hoje.getFullYear(), hoje.getMonth() + 1, 1);
  return { de: de.toISOString(), ate: ate.toISOString() };
}

function quando(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function reais(valor) {
  return Number(valor || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 0,
  });
}

function telefone(digitos) {
  if (!digitos) return "";
  const d = String(digitos);
  if (d.startsWith("55") && (d.length === 12 || d.length === 13)) {
    const resto = d.slice(4);
    return `(${d.slice(2, 4)}) ${resto.slice(0, resto.length - 4)}-${resto.slice(-4)}`;
  }
  return `+${d}`;
}

function lista(texto) {
  return String(texto || "").split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
}

async function copiar(texto, aviso) {
  try {
    await navigator.clipboard.writeText(texto);
    toast.success(aviso);
  } catch {
    // Fora de HTTPS o navegador não deixa copiar, e sem aviso parece que copiou.
    toast.error("Não foi possível copiar. Selecione o texto e copie à mão.");
  }
}

export default function FormulariosPage() {
  const [formularios, setFormularios] = useState(null);
  const [resumo, setResumo] = useState(null);
  const [editando, setEditando] = useState(null); // null | {} novo | formulário
  const [instalando, setInstalando] = useState(null);
  const [vendoRespostas, setVendoRespostas] = useState(null);

  const carregar = useCallback(() => {
    api.get("/formularios").then((r) => setFormularios(r.data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
    api.get("/formularios/resumo", { params: periodoDoMes() })
      .then((r) => setResumo(r.data)).catch(() => {});
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  const [excluir, excluindo] = useAcao(async (f) => {
    const ok = await confirmToast(
      `Excluir "${f.nome}"? O site para de enviar leads para cá. As respostas já recebidas continuam nos relatórios.`,
      { confirmLabel: "Excluir" });
    if (!ok) return;
    try {
      await api.delete(`/formularios/${f.id}`);
      toast.success("Formulário excluído");
      carregar();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  const aoSalvar = (f, novo) => {
    setEditando(null);
    carregar();
    // O passo seguinte de um formulário novo é instalar no site.
    if (novo) setInstalando(f);
  };

  return (
    <div className="zz-page" data-testid="formularios-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Formulários</h1>
          <p className="text-ink-2 mt-2 text-sm max-w-3xl">
            Quem preenche o formulário do seu site vira {t("contato")} aqui, com a origem do
            anúncio. Daqui ele pode ir direto para o {t("funil")}, para a agenda de um vendedor
            e receber uma mensagem no WhatsApp.
          </p>
        </div>
        <button className="zz-btn" onClick={() => setEditando({})} data-testid="form-novo">
          <Plus size={14} weight="bold" /> Novo formulário
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 items-start">
        <div className="xl:col-span-2 space-y-3">
          {formularios === null && <div className="text-sm text-ink-3">Carregando…</div>}
          {formularios?.length === 0 && (
            <div className="border border-dashed border-line rounded-xl p-8 text-center bg-surface">
              <div className="font-semibold">Nenhum formulário ainda</div>
              <p className="text-sm text-ink-2 mt-1 max-w-md mx-auto">
                Crie um para cada página ou campanha que capta lead. Depois de criado,
                você recebe o código para colar no site.
              </p>
            </div>
          )}
          {(formularios || []).map((f) => (
            <CartaoFormulario key={f.id} f={f}
              onEditar={() => setEditando(f)}
              onInstalar={() => setInstalando(f)}
              onRespostas={() => setVendoRespostas(f)}
              onExcluir={() => excluir(f)} excluindo={excluindo} />
          ))}
        </div>

        <section className="border border-line rounded-xl p-5 bg-surface">
          <h3 className="font-heading text-lg font-black tracking-tight mb-4">Este mês</h3>
          {resumo ? (
            <div className="grid grid-cols-2 gap-3">
              <Numero rotulo="Leads" valor={resumo.total.respostas} />
              <Numero rotulo={`${t("Contatos")} novos`} valor={resumo.total.contatos_novos} />
              <Numero rotulo={t("Negócios")} valor={resumo.total.negocios} />
              <Numero rotulo={t("Vendas")} valor={resumo.total.ganhos} />
              <div className="col-span-2 border border-line rounded-lg p-3">
                <div className="font-heading text-2xl font-black">{reais(resumo.total.valor_ganho)}</div>
                <div className="text-[11px] uppercase tracking-wider font-bold text-ink-3 mt-0.5">{t("Vendido")}</div>
              </div>
              {resumo.total.recusadas > 0 && (
                <div className="col-span-2 text-xs text-warning flex items-start gap-1.5">
                  <WarningCircle size={14} weight="fill" className="shrink-0 mt-0.5" />
                  {resumo.total.recusadas} envio(s) recusado(s) por telefone faltando ou inválido.
                  Confira em Respostas.
                </div>
              )}
            </div>
          ) : <div className="text-sm text-ink-3">Carregando…</div>}
        </section>
      </div>

      {resumo?.por_origem?.length > 0 && (
        <section className="border border-line rounded-xl bg-surface mt-6" data-testid="form-origens">
          <div className="px-5 py-4 border-b border-line">
            <h3 className="font-heading text-lg font-black tracking-tight">De onde vieram os leads</h3>
            <p className="text-xs text-ink-2 mt-1">
              Pelo utm_source e utm_campaign do link do anúncio.{" "}
              {t("A venda conta para a campanha que trouxe o lead, mesmo que tenha fechado depois.")}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-3">
                  <th className="px-5 py-2 font-bold">Origem</th>
                  <th className="px-5 py-2 font-bold">Campanha</th>
                  <th className="px-5 py-2 font-bold text-right">Leads</th>
                  <th className="px-5 py-2 font-bold text-right">{t("Negócios")}</th>
                  <th className="px-5 py-2 font-bold text-right">{t("Vendas")}</th>
                  <th className="px-5 py-2 font-bold text-right">{t("Vendido")}</th>
                </tr>
              </thead>
              <tbody>
                {resumo.por_origem.map((l) => (
                  <tr key={`${l.utm_source}|${l.utm_campaign}`} className="border-t border-line">
                    <td className="px-5 py-2.5">{l.utm_source || <span className="text-ink-3">Sem origem</span>}</td>
                    <td className="px-5 py-2.5 text-ink-2">{l.utm_campaign || "—"}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{l.respostas}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{l.negocios}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{l.ganhos}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{reais(l.valor_ganho)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {editando && (
        <EditarFormulario inicial={editando} onFechar={() => setEditando(null)} onSalvo={aoSalvar} />
      )}
      {instalando && (
        <Instalar f={instalando} onFechar={() => setInstalando(null)}
          onChaveNova={(f) => { setInstalando(f); carregar(); }} />
      )}
      {vendoRespostas && (
        <Respostas f={vendoRespostas} onFechar={() => setVendoRespostas(null)} />
      )}
    </div>
  );
}

function CartaoFormulario({ f, onEditar, onInstalar, onRespostas, onExcluir, excluindo }) {
  const acoes = [
    f.negocio?.ativo && `Abre ${t("negócio")}`,
    f.tarefa?.ativo && "Cria tarefa",
    f.whatsapp?.ativo && "Manda WhatsApp",
    f.dominios?.length > 0 && `Só ${f.dominios.join(", ")}`,
  ].filter(Boolean);
  return (
    <div className="border border-line rounded-xl p-5 bg-surface" data-testid={`form-${f.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-heading text-lg font-black tracking-tight truncate">{f.nome}</span>
            {!f.ativo && (
              <span className="text-[11px] font-semibold border rounded-full px-2 py-0.5 bg-surface-2 text-ink-2 border-line">
                Desativado
              </span>
            )}
          </div>
          <div className="text-sm text-ink-2 mt-1">
            {f.respostas} lead{f.respostas === 1 ? "" : "s"}
            {f.ultima_resposta ? ` · último em ${quando(f.ultima_resposta)}` : " · nenhum recebido ainda"}
          </div>
          {acoes.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {acoes.map((a) => (
                <span key={a} className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-surface-2 text-ink-2">{a}</span>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="zz-btn zz-btn-secondary text-xs" onClick={onInstalar} data-testid={`form-instalar-${f.id}`}>
            <Code size={12} weight="bold" /> Instalar no site
          </button>
          <button className="zz-btn zz-btn-secondary text-xs" onClick={onRespostas}>
            <ListBullets size={12} weight="bold" /> Respostas
          </button>
          <button className="zz-btn-icon" onClick={onEditar} aria-label="Editar" data-testid={`form-editar-${f.id}`}>
            <PencilSimple size={16} weight="bold" />
          </button>
          <button className="zz-btn-icon text-danger" onClick={onExcluir} disabled={excluindo} aria-label="Excluir">
            <Trash size={16} weight="bold" />
          </button>
        </div>
      </div>
    </div>
  );
}

function EditarFormulario({ inicial, onFechar, onSalvo }) {
  const novo = !inicial.id;
  const [form, setForm] = useState(() => {
    const base = { ...VAZIO, ...inicial };
    return {
      ...base,
      responsavel_id: base.responsavel_id || "",
      redirecionar_para: base.redirecionar_para || "",
      tagsTexto: (base.tags || []).join(", "),
      dominiosTexto: (base.dominios || []).join("\n"),
      negocio: { ...VAZIO.negocio, ...base.negocio, pipeline_id: base.negocio?.pipeline_id || "", etapa_id: base.negocio?.etapa_id || "" },
      tarefa: { ...VAZIO.tarefa, ...base.tarefa },
      whatsapp: {
        ...VAZIO.whatsapp, ...base.whatsapp,
        connection_id: base.whatsapp?.connection_id || "", bot_id: base.whatsapp?.bot_id || "",
        template: base.whatsapp?.template || VAZIO.whatsapp.template,
      },
    };
  });
  const [usuarios, setUsuarios] = useState([]);
  const [funis, setFunis] = useState([]);
  const [conexoes, setConexoes] = useState([]);
  const [bots, setBots] = useState([]);

  useEffect(() => {
    api.get("/users").then((r) => setUsuarios(r.data)).catch(() => {});
    api.get("/pipelines").then((r) => setFunis(r.data)).catch(() => {});
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/bots").then((r) => setBots(r.data)).catch(() => {});
  }, []);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setParte = (parte, patch) => setForm((f) => ({ ...f, [parte]: { ...f[parte], ...patch } }));

  const funil = funis.find((p) => p.id === form.negocio.pipeline_id);
  const etapas = [...(funil?.etapas || [])].filter((e) => e.tipo === "aberta")
    .sort((a, b) => (a.ordem || 0) - (b.ordem || 0));
  const conexao = conexoes.find((c) => c.id === form.whatsapp.connection_id)
    || conexoes.find((c) => c.status === "conectado") || conexoes[0];
  const naoOficial = conexao && (conexao.canal || "cloud_api") !== "cloud_api";

  const salvar = async () => {
    const corpo = {
      nome: form.nome,
      ativo: form.ativo,
      tags: lista(form.tagsTexto),
      responsavel_id: form.responsavel_id || null,
      dominios: lista(form.dominiosTexto),
      redirecionar_para: form.redirecionar_para.trim() || null,
      negocio: {
        ...form.negocio,
        pipeline_id: form.negocio.pipeline_id || null,
        etapa_id: form.negocio.etapa_id || null,
        valor: Number(String(form.negocio.valor || 0).replace(",", ".")) || 0,
      },
      tarefa: { ...form.tarefa, prazo_min: Number(form.tarefa.prazo_min) },
      whatsapp: {
        ...form.whatsapp,
        connection_id: form.whatsapp.connection_id || null,
        bot_id: form.whatsapp.resposta_modo === "bot" ? form.whatsapp.bot_id || null : null,
      },
    };
    try {
      const r = novo ? await api.post("/formularios", corpo) : await api.put(`/formularios/${inicial.id}`, corpo);
      toast.success(novo ? "Formulário criado" : "Formulário salvo");
      onSalvo(r.data, novo);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  return (
    <Modal largo titulo={novo ? "Novo formulário" : "Editar formulário"}
      descricao="O que acontece com cada pessoa que preencher."
      onFechar={onFechar} onSalvar={salvar} salvarLabel={novo ? "Criar formulário" : "Salvar"}
      testId="form-editar" corpoClasse="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Campo label="Nome" nota={`Para você reconhecer. Ex.: LP Lançamento, Site — ${t("Contato")}.`}>
          <input required autoFocus maxLength={80} className="zz-input" value={form.nome}
            data-testid="form-nome" onChange={(e) => set({ nome: e.target.value })} />
        </Campo>
        <div className="flex items-end pb-6">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={form.ativo} onChange={(e) => set({ ativo: e.target.checked })} />
            <span className="font-semibold">Recebendo leads</span>
          </label>
        </div>
      </div>

      <Secao titulo={`O ${t("contato")}`}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label="Etiquetas" nota={`Separadas por vírgula. Somadas às que o ${t("contato")} já tem.`}>
            <input className="zz-input" value={form.tagsTexto} placeholder="site, lançamento"
              onChange={(e) => set({ tagsTexto: e.target.value })} />
          </Campo>
          <Campo label="Responsável" nota={`Dono do ${t("contato")} e do ${t("negócio")}. Quem já tem dono continua com ele.`}>
            <select className="zz-input" value={form.responsavel_id} data-testid="form-responsavel"
              onChange={(e) => set({ responsavel_id: e.target.value })}>
              <option value="">Ninguém</option>
              {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
            </select>
          </Campo>
        </div>
      </Secao>

      <Secao titulo={t("Funil")} ligado={form.negocio.ativo}
        onLigar={(v) => setParte("negocio", { ativo: v })} rotulo={`Abrir um ${t("negócio")} para cada lead`}
        nota={`Quem já tem ${t("negócio")} aberto neste ${t("funil")} não ganha outro.`}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label={t("Funil")}>
            <select className="zz-input" value={form.negocio.pipeline_id}
              onChange={(e) => setParte("negocio", { pipeline_id: e.target.value, etapa_id: "" })}>
              <option value="">Selecione…</option>
              {funis.map((p) => <option key={p.id} value={p.id}>{p.nome}</option>)}
            </select>
          </Campo>
          <Campo label="Etapa">
            <select className="zz-input" value={form.negocio.etapa_id}
              onChange={(e) => setParte("negocio", { etapa_id: e.target.value })}>
              <option value="">A primeira do {t("funil")}</option>
              {etapas.map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
            </select>
          </Campo>
          <Campo label="Valor estimado (R$)">
            <input className="zz-input" inputMode="decimal" value={form.negocio.valor}
              onChange={(e) => setParte("negocio", { valor: e.target.value })} />
          </Campo>
          <Campo label={`Título do ${t("negócio")}`} nota="Use {nome} e {formulario}. Em branco: nome do formulário e do lead.">
            <input className="zz-input" maxLength={200} value={form.negocio.titulo}
              onChange={(e) => setParte("negocio", { titulo: e.target.value })} />
          </Campo>
        </div>
      </Secao>

      <Secao titulo="Retorno" ligado={form.tarefa.ativo}
        onLigar={(v) => setParte("tarefa", { ativo: v })} rotulo="Criar tarefa de retorno para o responsável"
        nota={`Aparece na agenda de ${t("Atividades")} e fica atrasada se ninguém ligar.`}>
        {!form.responsavel_id && (
          <p className="text-xs text-warning mb-3">Escolha um responsável acima: a tarefa precisa de um dono.</p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label="Prazo">
            <select className="zz-input" value={form.tarefa.prazo_min}
              onChange={(e) => setParte("tarefa", { prazo_min: e.target.value })}>
              {PRAZOS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
            </select>
          </Campo>
          <Campo label="Título da tarefa" nota="Em branco: Retornar lead do formulário {formulario}.">
            <input className="zz-input" maxLength={200} value={form.tarefa.titulo}
              onChange={(e) => setParte("tarefa", { titulo: e.target.value })} />
          </Campo>
        </div>
      </Secao>

      <Secao titulo="WhatsApp" ligado={form.whatsapp.ativo}
        onLigar={(v) => setParte("whatsapp", { ativo: v })} rotulo="Mandar mensagem para quem preencheu"
        nota="Uma mensagem por pessoa a cada 30 minutos, mesmo que ela preencha de novo.">
        {naoOficial && (
          <div className="text-xs text-warning bg-warning-soft border border-warning rounded-lg p-3 mb-4">
            Nesta conexão (API não oficial) escrever primeiro para quem nunca falou com o número
            é o que mais leva a bloqueio. Use com volume baixo.
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label="Sai pela conexão">
            <select className="zz-input" value={form.whatsapp.connection_id}
              onChange={(e) => setParte("whatsapp", {
                connection_id: e.target.value,
                template: { nome: "", idioma: "pt_BR", variaveis: [] },
              })}>
              <option value="">Automática (a primeira conectada)</option>
              {conexoes.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select>
          </Campo>
          <EscolhaDeModelo conexao={conexao} template={form.whatsapp.template}
            onChange={(t) => setParte("whatsapp", { template: t })} primeiraVariavel="{primeiro_nome}"
            dica="Aceita {nome}, {primeiro_nome}, {empresa} e {formulario}." />
          <Campo label="Texto da mensagem" className="sm:col-span-2"
            nota="Sai como texto quando a conversa está aberta (e sempre na conexão não oficial), e é o que aparece no histórico. Use {primeiro_nome}, {nome}, {empresa} e {formulario}. Com modelo, escreva aqui o mesmo texto dele.">
            <textarea rows={3} className="zz-input" value={form.whatsapp.mensagem}
              placeholder="Olá, {primeiro_nome}! Recebemos seu cadastro na {empresa}. Como podemos te ajudar?"
              onChange={(e) => setParte("whatsapp", { mensagem: e.target.value })} />
          </Campo>
        </div>
        <div className="mt-4">
          <div className="text-xs font-bold uppercase tracking-wider text-ink-2 mb-1.5">Quem atende a resposta</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {modos().map(([valor, rotulo, nota]) => {
              const marcado = form.whatsapp.resposta_modo === valor;
              return (
                <button key={valor} type="button" onClick={() => setParte("whatsapp", { resposta_modo: valor })}
                  className={`text-left border rounded-lg p-3 transition-colors ${
                    marcado ? "border-info bg-info-soft ring-1 ring-info" : "border-line hover:bg-surface-2"}`}>
                  <div className="font-semibold text-sm">{rotulo}</div>
                  <div className="text-xs text-ink-2 mt-1">{nota}</div>
                </button>
              );
            })}
          </div>
          {form.whatsapp.resposta_modo === "bot" && (
            <div className="mt-3 max-w-sm">
              <Campo label={t("Robô")}>
                <select className="zz-input" value={form.whatsapp.bot_id}
                  onChange={(e) => setParte("whatsapp", { bot_id: e.target.value })}>
                  <option value="">Selecione…</option>
                  {bots.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </Campo>
            </div>
          )}
        </div>
      </Secao>

      <Secao titulo="Segurança e página de obrigado">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label="Aceitar envios só destes sites"
            nota="Um por linha, ex.: r3.com.br (vale para os subdomínios). Em branco aceita de qualquer lugar, que é o necessário para n8n e Zapier.">
            <textarea rows={3} className="zz-input font-mono text-xs" value={form.dominiosTexto}
              onChange={(e) => set({ dominiosTexto: e.target.value })} />
          </Campo>
          <Campo label="Página de obrigado"
            nota="Só para formulário HTML sem JavaScript: depois de enviar, a pessoa vai para este endereço.">
            <input className="zz-input" type="url" placeholder="https://…" value={form.redirecionar_para}
              onChange={(e) => set({ redirecionar_para: e.target.value })} />
          </Campo>
        </div>
      </Secao>
    </Modal>
  );
}

function Instalar({ f, onFechar, onChaveNova }) {
  const endereco = `${API}/f/${f.chave}`;
  const script = `<script src="${endereco}/script.js" async></script>`;
  const marcacao = `<form data-zappzen>
  <input name="nome" placeholder="Nome">
  <input name="telefone" placeholder="WhatsApp" required>
  <input name="email" type="email" placeholder="E-mail">
  <!-- campo-isca contra robô: fica escondido -->
  <input name="_hp" style="display:none" tabindex="-1" autocomplete="off">
  <button>Enviar</button>
</form>`;
  const porCodigo = `// Depois do script acima, onde o seu formulário já envia:
ZappZen.enviar({ nome: "Ana", telefone: "85999998888", email: "ana@x.com" })
  .then((r) => { if (!r.ok) alert(r.erro); });`;
  const curl = `curl -X POST ${endereco} \\
  -H "Content-Type: application/json" \\
  -d '{"nome":"Ana","telefone":"85999998888","utm_source":"instagram"}'`;

  const [trocar, trocando] = useAcao(async () => {
    const ok = await confirmToast(
      "Gerar uma chave nova? A atual para de funcionar na hora, e o site precisa ser atualizado com o código novo.",
      { confirmLabel: "Gerar nova" });
    if (!ok) return;
    try {
      const r = await api.post(`/formularios/${f.id}/chave`);
      toast.success("Chave nova gerada. Atualize o código no site.");
      onChaveNova(r.data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  return (
    <Modal largo titulo={`Instalar "${f.nome}"`}
      descricao="Escolha o jeito que serve para o seu site. Os três mandam para o mesmo lugar."
      onFechar={onFechar} testId="form-instalar" corpoClasse="space-y-6"
      rodape={(
        <button type="button" className="zz-btn zz-btn-secondary mr-auto" onClick={trocar} disabled={trocando}>
          <ArrowsClockwise size={14} weight="bold" /> {trocando ? "Gerando…" : "Gerar chave nova"}
        </button>
      )}>
      <Trecho titulo="1. Página com formulário próprio (o mais comum)"
        nota="Cole o script uma vez, no fim da página, e acrescente data-zappzen à tag <form>. Ele guarda o utm_source, utm_campaign e o clique do anúncio por 30 dias, mesmo que a pessoa navegue antes de preencher, e envia junto. O envio original do formulário continua funcionando."
        codigo={`${script}\n\n${marcacao}`} />
      <Trecho titulo="2. Formulário que já envia por JavaScript"
        nota="Se o seu código já trata o envio (por exemplo, gravando em outro banco), chame ZappZen.enviar com os campos. A origem do anúncio vai junto sozinha."
        codigo={`${script}\n\n${porCodigo}`} />
      <Trecho titulo="3. n8n, Zapier, Elementor, RD ou do seu servidor"
        nota="Um POST com os campos em JSON. Nessa forma a origem só vai se você mandar utm_source e utm_campaign no corpo."
        codigo={curl} />
      <div className="text-xs text-ink-2 bg-surface-2 rounded-lg p-4 space-y-1.5">
        <div className="font-semibold text-ink">Os nomes dos campos</div>
        <div>O telefone é obrigatório. São reconhecidos sozinhos: <span className="font-mono">nome</span>,{" "}
          <span className="font-mono">sobrenome</span>, <span className="font-mono">telefone</span> /{" "}
          <span className="font-mono">celular</span> / <span className="font-mono">whatsapp</span>,{" "}
          <span className="font-mono">email</span>, <span className="font-mono">empresa</span>,{" "}
          <span className="font-mono">cargo</span>.</div>
        <div>Campo com o mesmo nome de um campo personalizado dos {t("Contatos")} vai para ele. Os outros
          ficam guardados na resposta e numa anotação na ficha do {t("contato")}.</div>
      </div>
      <div className="text-[11px] text-ink-3 break-all">
        Endereço: <span className="font-mono">{endereco}</span>
      </div>
    </Modal>
  );
}

function Trecho({ titulo, nota, codigo }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-1">
        <div className="font-semibold text-sm">{titulo}</div>
        <button type="button" className="zz-btn zz-btn-secondary text-xs shrink-0"
          onClick={() => copiar(codigo, "Código copiado")}>
          <Copy size={12} weight="bold" /> Copiar
        </button>
      </div>
      <p className="text-xs text-ink-2 mb-2">{nota}</p>
      <pre className="text-xs font-mono bg-surface-2 border border-line rounded-lg p-3 overflow-x-auto whitespace-pre">{codigo}</pre>
    </div>
  );
}

function Respostas({ f, onFechar }) {
  const [linhas, setLinhas] = useState(null);

  const carregar = useCallback(() => {
    api.get(`/formularios/${f.id}/respostas`, { params: { limite: 100 } })
      .then((r) => setLinhas(r.data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [f.id]);
  useEffect(() => { carregar(); }, [carregar]);

  return (
    <Modal largo titulo={`Respostas de "${f.nome}"`} descricao="As 100 mais recentes."
      onFechar={onFechar} testId="form-respostas" corpoClasse=""
      rodape={(
        <button type="button" className="zz-btn zz-btn-secondary mr-auto" onClick={carregar}>
          <ArrowsClockwise size={14} weight="bold" /> Atualizar
        </button>
      )}>
      {linhas === null && <div className="text-sm text-ink-3">Carregando…</div>}
      {linhas?.length === 0 && (
        <div className="text-sm text-ink-3 text-center py-6">
          Nenhuma resposta ainda. Faça um envio de teste pelo seu site.
        </div>
      )}
      {linhas?.length > 0 && (
        <div className="overflow-x-auto -mx-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-ink-3">
                <th className="px-6 py-2 font-bold">Quando</th>
                <th className="px-6 py-2 font-bold">Quem</th>
                <th className="px-6 py-2 font-bold">Origem</th>
                <th className="px-6 py-2 font-bold">Situação</th>
                <th className="px-6 py-2 font-bold">WhatsApp</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((l) => {
                const st = STATUS[l.status] || STATUS.recebida;
                const origem = [l.utm?.utm_source, l.utm?.utm_campaign].filter(Boolean).join(" / ");
                const detalhe = [l.erro, ...(l.avisos || [])].filter(Boolean).join(" · ");
                return (
                  <tr key={l.id} className="border-t border-line align-top">
                    <td className="px-6 py-2.5 font-mono text-xs text-ink-2 whitespace-nowrap">{quando(l.created_at)}</td>
                    <td className="px-6 py-2.5">
                      <div>{l.contato_nome || l.nome || <span className="text-ink-3">Sem nome</span>}</div>
                      <div className="text-xs text-ink-3">{telefone(l.numero) || l.dados?.telefone || l.dados?.celular || ""}</div>
                    </td>
                    <td className="px-6 py-2.5 text-ink-2">{origem || "—"}</td>
                    <td className="px-6 py-2.5">
                      <span className={`inline-block text-[11px] font-semibold border rounded-full px-2 py-0.5 ${st.classe}`}>
                        {st.label}
                      </span>
                      {detalhe && <div className="text-xs text-ink-3 mt-1 max-w-xs">{detalhe}</div>}
                    </td>
                    <td className="px-6 py-2.5 text-ink-2" title={l.whatsapp_erro || ""}>
                      {l.whatsapp_status ? WPP[l.whatsapp_status] || l.whatsapp_status : "—"}
                      {l.respondeu_em && <div className="text-xs text-success">Respondeu</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

// Bloco do formulário de edição. Com `onLigar`, o bloco tem uma chave e o
// conteúdo só aparece ligado: quem não usa funil não precisa ler os campos dele.
function Secao({ titulo, ligado, onLigar, rotulo, nota, children }) {
  const comChave = typeof onLigar === "function";
  return (
    <section className="border border-line rounded-xl p-4">
      <div className="font-heading font-black tracking-tight mb-2">{titulo}</div>
      {comChave && (
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={!!ligado} onChange={(e) => onLigar(e.target.checked)} />
          <span className="font-semibold">{rotulo}</span>
        </label>
      )}
      {nota && <p className="text-[11px] text-ink-3 mt-1">{nota}</p>}
      {(!comChave || ligado) && <div className="mt-4">{children}</div>}
    </section>
  );
}

function Numero({ rotulo, valor }) {
  return (
    <div className="border border-line rounded-lg p-3">
      <div className="font-heading text-2xl font-black">{valor ?? 0}</div>
      <div className="text-[11px] uppercase tracking-wider font-bold text-ink-3 mt-0.5">{rotulo}</div>
    </div>
  );
}

function Campo({ label, nota, className = "", children }) {
  return (
    <div className={className}>
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
      {nota && <p className="text-[11px] text-ink-3 mt-1">{nota}</p>}
    </div>
  );
}
