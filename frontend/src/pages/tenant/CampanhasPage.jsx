import { useCallback, useEffect, useRef, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import Modal from "@/components/ui/Modal";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import {
  Plus, Play, Pause, X, Trash, PencilSimple, Paperclip, CaretDown, CaretRight,
  Megaphone, Warning,
} from "@phosphor-icons/react";

const STATUS_META = {
  rascunho: { label: "rascunho", classe: "bg-surface-2 border-line-strong text-ink" },
  agendada: { label: "agendada", classe: "bg-info-soft border-info text-info" },
  enviando: { label: "enviando", classe: "bg-warning-soft border-warning text-warning" },
  pausada: { label: "pausada", classe: "bg-warning-soft border-warning text-warning" },
  concluida: { label: "concluída", classe: "bg-success-soft border-success text-success" },
  cancelada: { label: "cancelada", classe: "bg-danger-soft border-danger text-danger" },
};

const EMPTY = {
  nome: "",
  whatsapp_connection_id: "",
  // Modelo aprovado e o padrao, e nao uma opcao entre outras: fora da janela de
  // 24h o WhatsApp so entrega template, e num publico de campanha quase todo
  // mundo esta fora dela (a pessoa nao escreveu para a empresa hoje).
  conteudo: {
    tipo: "template", texto: "", media_id: null,
    template: { nome: "", idioma: "pt_BR", corpo: "", variaveis: [], media_id: null },
  },
  publico: { tipo: "todos", tags: [], contact_ids: [] },
  cadencia: { por_minuto: 12 },
  agendada_para: "",
  resposta_modo: "aguardando",
  bot_id: null,
  departamento_id: null,
};

// O <input type="datetime-local"> fala no fuso do navegador e o backend guarda
// tudo em UTC. As duas conversões ficam juntas aqui para não divergirem.
function paraInputLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function paraIso(local) {
  return local ? new Date(local).toISOString() : null;
}

function Campo({ label, hint, children, className = "" }) {
  return (
    <div className={className}>
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
      {hint && <div className="text-[10px] text-ink-3 mt-1">{hint}</div>}
    </div>
  );
}

function BotaoTipo({ atual, valor, onClick, children }) {
  // Seleção é `border-info` + anel, nunca a troca de um cinza por outro: os
  // dois cinzas são quase iguais e o sinal desaparece.
  const ativo = atual === valor || (valor === "text" && atual === "media");
  return (
    <button type="button" onClick={onClick} data-testid={`campaign-tipo-${valor}`}
      className={`px-4 py-2 rounded-lg border text-sm font-bold ${
        ativo ? "border-info ring-1 ring-info text-info bg-info-soft"
              : "border-line text-ink-2 hover:bg-surface-2"}`}>
      {children}
    </button>
  );
}

// A lista vem da conta da Meta do cliente, e só com os modelos APROVADOS:
// oferecer um em análise produziria uma campanha que falha em todos os
// destinatários, uma mensagem por vez.
function EscolhaDeModelo({ conexaoId, template, onChange }) {
  const [modelos, setModelos] = useState(null);
  const [erro, setErro] = useState(null);

  useEffect(() => {
    if (!conexaoId) { setModelos(null); return; }
    setModelos(null);
    setErro(null);
    api.get(`/whatsapp/connections/${conexaoId}/templates`)
      .then((r) => setModelos(r.data))
      .catch((e) => setErro(formatApiErrorDetail(e.response?.data?.detail) || "Não foi possível listar os modelos"));
  }, [conexaoId]);

  const escolhido = (modelos || []).find(
    (m) => m.nome === template.nome && m.idioma === template.idioma);

  const escolher = (chave) => {
    const m = (modelos || []).find((x) => `${x.nome}|${x.idioma}` === chave);
    if (!m) return onChange({ nome: "", idioma: "pt_BR", corpo: "", variaveis: [], media_id: null });
    onChange({
      nome: m.nome, idioma: m.idioma, corpo: m.corpo,
      // Um valor por variável do corpo. Nasce com {primeiro_nome} na primeira,
      // que é o uso mais comum e o que a pessoa ia digitar de qualquer forma.
      variaveis: Array.from({ length: m.variaveis }, (_, i) => (i === 0 ? "{primeiro_nome}" : "")),
      media_id: null,
    });
  };

  if (!conexaoId) {
    return (
      <div className="sm:col-span-2 lg:col-span-3 text-sm text-ink-2 border border-dashed border-line rounded-lg p-4">
        Escolha a conexão primeiro: os modelos vêm da conta da Meta daquele número.
      </div>
    );
  }

  return (
    <>
      <Campo label="Modelo aprovado" className="sm:col-span-2 lg:col-span-3"
        hint={erro || "Cadastrados no painel da Meta, em WhatsApp > Modelos de mensagem."}>
        <select required className="zz-input" data-testid="campaign-template"
          value={template.nome ? `${template.nome}|${template.idioma}` : ""}
          onChange={(e) => escolher(e.target.value)}>
          <option value="">{modelos === null ? "Carregando…" : "Selecione…"}</option>
          {(modelos || []).map((m) => (
            <option key={`${m.nome}|${m.idioma}`} value={`${m.nome}|${m.idioma}`}>
              {m.nome} ({m.idioma}) · {String(m.categoria || "").toLowerCase()}
            </option>
          ))}
        </select>
        {modelos !== null && modelos.length === 0 && !erro && (
          <div className="text-[11px] text-warning mt-1">
            Nenhum modelo aprovado nesta conta ainda. Crie um no painel da Meta e espere a aprovação.
          </div>
        )}
      </Campo>

      {escolhido && (
        <div className="sm:col-span-2 lg:col-span-3 border border-line rounded-lg p-4 bg-surface-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-ink-3 mb-2">
            Texto do modelo
          </div>
          <div className="text-sm text-ink whitespace-pre-wrap font-sans">{escolhido.corpo}</div>
          {template.variaveis.length > 0 && (
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
              {template.variaveis.map((v, i) => (
                <div key={i}>
                  <label className="text-[10px] font-bold uppercase tracking-wider text-ink-3 block mb-1.5">
                    Variável {`{{${i + 1}}}`}
                  </label>
                  <input className="zz-input" value={v} data-testid={`campaign-var-${i}`}
                    placeholder="{primeiro_nome} ou um texto fixo"
                    onChange={(e) => {
                      const novas = [...template.variaveis];
                      novas[i] = e.target.value;
                      onChange({ ...template, variaveis: novas });
                    }} />
                </div>
              ))}
              <div className="sm:col-span-2 text-[10px] text-ink-3">
                Aceita as mesmas variáveis do texto livre: {"{nome_contato}"}, {"{primeiro_nome}"}, {"{numero}"}.
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function Progresso({ campanha }) {
  const t = campanha.totais || {};
  const total = t.total || 0;
  const feitos = (t.enviados || 0) + (t.falhas || 0) + (t.ignorados || 0);
  const pct = total ? Math.round((feitos / total) * 100) : 0;
  return (
    <div>
      <div className="h-2 bg-surface-3 border border-line rounded-full">
        <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-[10px] font-mono text-ink-2 mt-1">
        {feitos}/{total} · {t.enviados || 0} enviados
        {t.falhas ? ` · ${t.falhas} falhas` : ""}
        {t.ignorados ? ` · ${t.ignorados} ignorados` : ""}
      </div>
    </div>
  );
}

function SeletorContatos({ selecionados, onChange }) {
  const [busca, setBusca] = useState("");
  const [achados, setAchados] = useState([]);

  useEffect(() => {
    const t = setTimeout(() => {
      api.get("/contacts", { params: { q: busca || undefined, limit: 30 } })
        .then((r) => setAchados(r.data.items || []))
        .catch(() => setAchados([]));
    }, 300);
    return () => clearTimeout(t);
  }, [busca]);

  const alterna = (id) =>
    onChange(selecionados.includes(id) ? selecionados.filter((x) => x !== id) : [...selecionados, id]);

  return (
    <div className="border border-line bg-surface rounded-lg">
      <input className="zz-input border-0 border-b border-line" placeholder="Buscar por nome ou número…"
        value={busca} onChange={(e) => setBusca(e.target.value)} data-testid="campaign-contact-search" />
      <div className="max-h-44 overflow-y-auto">
        {achados.length === 0 && <div className="p-3 text-xs text-ink-3">Nenhum contato encontrado.</div>}
        {achados.map((c) => (
          <label key={c.id} className="flex items-center gap-2 px-3 py-1.5 border-b border-line hover:bg-surface-2 cursor-pointer">
            <input type="checkbox" checked={selecionados.includes(c.id)} onChange={() => alterna(c.id)} />
            <span className="text-sm font-semibold flex-1 truncate">{c.nome}</span>
            <span className="text-xs font-mono text-ink-3">{c.numero_whatsapp}</span>
            {c.opt_out && <span className="text-[9px] font-bold uppercase text-danger">optout</span>}
          </label>
        ))}
      </div>
      <div className="px-3 py-1.5 bg-surface-2 text-[10px] font-bold uppercase tracking-wider text-ink-2">
        {selecionados.length} selecionado(s)
      </div>
    </div>
  );
}

function Detalhe({ campanha }) {
  const [dados, setDados] = useState(null);
  const [falhas, setFalhas] = useState([]);

  useEffect(() => {
    api.get(`/campaigns/${campanha.id}`).then((r) => setDados(r.data.metricas)).catch(() => {});
    api.get(`/campaigns/${campanha.id}/recipients`, { params: { status: "falha", limit: 20 } })
      .then((r) => setFalhas(r.data.items || [])).catch(() => {});
  }, [campanha.id, campanha.updated_at]);

  if (!dados) return <div className="px-4 py-3 text-xs text-ink-3">Carregando…</div>;

  const caixas = [
    ["Público", (dados.pendente || 0) + (dados.enviando || 0) + (dados.enviado || 0) + (dados.falha || 0) + (dados.ignorado || 0)],
    ["Enviados", dados.enviado || 0],
    ["Respostas", dados.respostas || 0],
    ["Falhas", dados.falha || 0],
    ["Ignorados", dados.ignorado || 0],
    ["Na fila", dados.pendente || 0],
  ];
  const taxa = dados.enviado ? Math.round(((dados.respostas || 0) / dados.enviado) * 100) : 0;

  return (
    <div className="px-4 py-4 bg-surface-2 border-b border-line">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
        {caixas.map(([rotulo, valor]) => (
          <div key={rotulo} className="border border-line bg-surface px-3 py-2 rounded-lg">
            <div className="text-[9px] font-bold uppercase tracking-wider text-ink-3">{rotulo}</div>
            <div className="font-heading text-xl font-black tracking-tighter">{valor}</div>
          </div>
        ))}
      </div>
      <div className="text-xs text-ink-2 mb-3">
        Taxa de resposta: <strong className="font-mono">{taxa}%</strong>
        {campanha.motivo_pausa && (
          <span className="ml-3 text-warning"><Warning size={12} weight="bold" className="inline" /> {campanha.motivo_pausa}</span>
        )}
      </div>
      {falhas.length > 0 && (
        <div className="border border-line bg-surface rounded-lg">
          <div className="px-3 py-1.5 border-b border-line text-[10px] font-bold uppercase tracking-wider text-ink-3">
            Falhas recentes
          </div>
          {falhas.map((f) => (
            <div key={f.id} className="flex items-center gap-3 px-3 py-1.5 border-b border-line text-xs">
              <span className="font-mono text-ink w-32 shrink-0">{f.numero_whatsapp}</span>
              <span className="truncate text-ink-3">{f.erro}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CampanhasPage() {
  const [campanhas, setCampanhas] = useState([]);
  const [conexoes, setConexoes] = useState([]);
  const [bots, setBots] = useState([]);
  const [departamentos, setDepartamentos] = useState([]);
  const [tagsDisponiveis, setTagsDisponiveis] = useState([]);
  const [editando, setEditando] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [anexo, setAnexo] = useState(null);
  const [previa, setPrevia] = useState(null);
  const [aberta, setAberta] = useState(null);
  const arquivoRef = useRef(null);

  const carregar = useCallback(
    () => api.get("/campaigns").then((r) => setCampanhas(r.data)).catch(() => {}),
    []
  );

  useEffect(() => {
    carregar();
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/bots").then((r) => setBots(r.data)).catch(() => {});
    api.get("/departments").then((r) => setDepartamentos(r.data)).catch(() => {});
    api.get("/contacts/tags").then((r) => setTagsDisponiveis(r.data)).catch(() => {});
  }, [carregar]);

  // Só pesquisa enquanto há campanha andando. Uma tela de campanhas todas
  // concluídas não muda sozinha, e o polling de 4s existe para acompanhar o
  // progresso de um disparo — não para ficar batendo no banco à toa.
  const temAtiva = campanhas.some((c) => ["enviando", "agendada"].includes(c.status));
  useEffect(() => {
    if (!temAtiva) return;
    const t = setInterval(carregar, 4000);
    return () => clearInterval(t);
  }, [temAtiva, carregar]);

  // Prévia do público. É o número que a pessoa confere antes de disparar para
  // milhares de contatos, então é recalculado a cada mudança do filtro.
  useEffect(() => {
    if (!editando) return;
    const t = setTimeout(() => {
      api.post("/campaigns/audience/preview", { publico: form.publico })
        .then((r) => setPrevia(r.data)).catch(() => setPrevia(null));
    }, 300);
    return () => clearTimeout(t);
  }, [editando, form.publico]);

  const abrirNova = () => {
    setForm({ ...EMPTY, whatsapp_connection_id: conexoes[0]?.id || "" });
    setAnexo(null);
    setEditando({});
  };

  const abrirEdicao = (c) => {
    setForm({
      nome: c.nome,
      whatsapp_connection_id: c.whatsapp_connection_id || "",
      conteudo: {
        tipo: c.conteudo?.tipo || "template",
        texto: c.conteudo?.texto || "",
        media_id: c.conteudo?.media_id || null,
        template: c.conteudo?.template || { nome: "", idioma: "pt_BR", corpo: "", variaveis: [], media_id: null },
      },
      publico: { tipo: c.publico?.tipo || "todos", tags: c.publico?.tags || [], contact_ids: c.publico?.contact_ids || [] },
      cadencia: { por_minuto: c.cadencia?.por_minuto || 12 },
      agendada_para: paraInputLocal(c.agendada_para),
      resposta_modo: c.resposta_modo || "aguardando",
      bot_id: c.bot_id || null,
      departamento_id: c.departamento_id || null,
    });
    setAnexo(c.conteudo?.media_id ? { id: c.conteudo.media_id, filename: "arquivo anexado" } : null);
    setEditando(c);
  };

  const enviarArquivo = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post("/campaigns/media", fd);
      setAnexo(r.data);
      setForm((f) => ({ ...f, conteudo: { ...f.conteudo, tipo: "media", media_id: r.data.id } }));
      toast.success("Arquivo anexado");
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const removerAnexo = () => {
    setAnexo(null);
    setForm((f) => ({ ...f, conteudo: { ...f.conteudo, tipo: "text", media_id: null } }));
    if (arquivoRef.current) arquivoRef.current.value = "";
  };

  // A trava de clique repetido vem do Modal.
  const salvar = async () => {
    const payload = { ...form, agendada_para: paraIso(form.agendada_para) };
    try {
      if (editando?.id) await api.patch(`/campaigns/${editando.id}`, payload);
      else await api.post("/campaigns", payload);
      setEditando(null);
      toast.success("Campanha salva");
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const acao = async (c, rota, mensagem, confirmar) => {
    if (confirmar && !(await confirmToast(confirmar, { confirmLabel: "Confirmar" }))) return;
    try {
      const r = await api.post(`/campaigns/${c.id}/${rota}`);
      toast.success(mensagem(r.data));
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const excluir = async (c) => {
    if (!(await confirmToast(`Excluir a campanha "${c.nome}"?`, { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/campaigns/${c.id}`);
      toast.success("Campanha excluída");
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const alternaTag = (tag) =>
    setForm((f) => ({
      ...f,
      publico: {
        ...f.publico,
        tags: f.publico.tags.includes(tag) ? f.publico.tags.filter((t) => t !== tag) : [...f.publico.tags, tag],
      },
    }));

  const semConexao = conexoes.length === 0;

  return (
    <div className="zz-page" data-testid="campaigns-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Campanhas</h1>
          <p className="text-ink-2 mt-2 text-sm">
            Dispare uma mensagem para uma lista de contatos e acompanhe quem recebeu e quem respondeu.
          </p>
        </div>
        <button data-testid="new-campaign-btn" onClick={abrirNova} disabled={semConexao} className="zz-btn disabled:opacity-40">
          <Plus size={14} weight="bold" /> Nova campanha
        </button>
      </div>

      <div className="border border-warning bg-warning-soft p-4 mb-6 flex gap-3 rounded-lg" data-testid="campaign-warning">
        <Warning size={18} weight="bold" className="text-warning shrink-0 mt-0.5" />
        <div className="text-sm text-ink">
          <strong className="font-bold">Cada modelo entregue é cobrado pela Meta.</strong> Fora da janela de 24
          horas o WhatsApp só entrega modelo aprovado, e é isso que o disparo usa. Marketing custa mais que
          utilidade, e conteúdo que o contato denuncia derruba a nota de qualidade do número, o que reduz o
          limite diário de conversas e chega a suspender o número da empresa. Mande para quem espera receber
          e sempre ofereça a saída (o contato que responder <span className="font-mono">SAIR</span> é removido
          dos próximos disparos automaticamente).
        </div>
      </div>

      {semConexao && (
        <div className="border border-dashed border-line rounded-xl bg-surface p-8 text-center text-sm text-ink-2 mb-6">
          Conecte um número de WhatsApp antes de criar campanhas.
        </div>
      )}

      {editando && (
        <Modal titulo={editando?.id ? "Editar campanha" : "Nova campanha"} largo
          descricao="Fora da janela de 24 horas só sai modelo aprovado — é por isso que ele é o padrão do conteúdo."
          onFechar={() => setEditando(null)} onSalvar={salvar} testId="campaign-form"
          corpoClasse="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Campo label="Nome da campanha" className="sm:col-span-2">
            <input required autoFocus className="zz-input" data-testid="campaign-name" value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })} />
          </Campo>
          <Campo label="Enviar pela conexão">
            <select required className="zz-input" data-testid="campaign-connection" value={form.whatsapp_connection_id}
              onChange={(e) => setForm({ ...form, whatsapp_connection_id: e.target.value })}>
              <option value="">Selecione…</option>
              {conexoes.map((c) => (
                <option key={c.id} value={c.id}>{c.nome} {c.status === "conectado" ? "" : `(${c.status})`}</option>
              ))}
            </select>
          </Campo>

          <Campo label="O que enviar" className="sm:col-span-2 lg:col-span-3">
            <div className="flex flex-wrap gap-2">
              <BotaoTipo atual={form.conteudo.tipo} valor="template"
                onClick={() => setForm({ ...form, conteudo: { ...form.conteudo, tipo: "template" } })}>
                Modelo aprovado
              </BotaoTipo>
              <BotaoTipo atual={form.conteudo.tipo} valor="text"
                onClick={() => setForm({ ...form, conteudo: { ...form.conteudo, tipo: anexo ? "media" : "text" } })}>
                Texto livre
              </BotaoTipo>
            </div>
            <div className="text-[11px] text-ink-3 mt-2">
              {form.conteudo.tipo === "template"
                ? "Chega a qualquer contato da lista. O modelo precisa estar aprovado na conta da Meta."
                : "Só chega a quem falou com a empresa nas últimas 24 horas. Os demais ficam como ignorados, com o motivo."}
            </div>
          </Campo>

          {form.conteudo.tipo === "template" ? (
            <EscolhaDeModelo
              conexaoId={form.whatsapp_connection_id}
              template={form.conteudo.template}
              onChange={(t) => setForm({ ...form, conteudo: { ...form.conteudo, template: t } })}
            />
          ) : (
            <Campo label="Mensagem" className="sm:col-span-2 lg:col-span-3"
              hint="Variáveis: {nome_contato}, {primeiro_nome}, {numero}. Com anexo, o texto vira a legenda.">
              <textarea required rows={4} className="zz-input font-sans" data-testid="campaign-text"
                value={form.conteudo.texto}
                onChange={(e) => setForm({ ...form, conteudo: { ...form.conteudo, texto: e.target.value } })} />
            </Campo>
          )}

          <div className={`sm:col-span-2 lg:col-span-3 flex items-center gap-3 ${form.conteudo.tipo === "template" ? "hidden" : ""}`}>
            <input ref={arquivoRef} type="file" className="hidden" data-testid="campaign-file"
              onChange={(e) => enviarArquivo(e.target.files?.[0])} />
            <button type="button" onClick={() => arquivoRef.current?.click()} className="zz-btn zz-btn-secondary">
              <Paperclip size={14} weight="bold" /> Anexar arquivo
            </button>
            {anexo && (
              <span className="text-xs font-mono text-ink flex items-center gap-2">
                {anexo.filename}
                <button type="button" onClick={removerAnexo} className="text-danger hover:bg-danger-soft p-0.5">
                  <X size={12} weight="bold" />
                </button>
              </span>
            )}
          </div>

          <Campo label="Público" className="sm:col-span-2 lg:col-span-3">
            <div className="flex gap-2 mb-2">
              {[["todos", "Todos os contatos"], ["tags", "Por etiqueta"], ["selecionados", "Escolher contatos"]].map(([v, r]) => (
                <button key={v} type="button" data-testid={`campaign-audience-${v}`}
                  onClick={() => setForm({ ...form, publico: { ...form.publico, tipo: v } })}
                  className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border rounded-full ${
                    form.publico.tipo === v ? "bg-brand text-brand-fg border-brand" : "bg-surface border-line text-ink-2"
                  }`}>
                  {r}
                </button>
              ))}
            </div>
            {form.publico.tipo === "tags" && (
              tagsDisponiveis.length === 0 ? (
                <div className="text-xs text-ink-3">
                  Nenhuma etiqueta criada ainda — marque contatos na tela de Contatos.
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {tagsDisponiveis.map((t) => (
                    <button key={t} type="button" onClick={() => alternaTag(t)}
                      className={`px-2 py-1 text-xs font-semibold border rounded-full ${
                        form.publico.tags.includes(t) ? "bg-brand text-brand-fg border-brand" : "bg-surface border-line text-ink"
                      }`}>
                      {t}
                    </button>
                  ))}
                </div>
              )
            )}
            {form.publico.tipo === "selecionados" && (
              <SeletorContatos selecionados={form.publico.contact_ids}
                onChange={(ids) => setForm({ ...form, publico: { ...form.publico, contact_ids: ids } })} />
            )}
            {previa && (
              <div className="text-xs mt-2 font-semibold text-ink" data-testid="campaign-audience-preview">
                {previa.total.toLocaleString("pt-BR")} contato(s) vão receber
                {previa.total > previa.limite && (
                  <span className="text-danger"> — acima do limite de {previa.limite.toLocaleString("pt-BR")} por campanha</span>
                )}
              </div>
            )}
          </Campo>

          <Campo label="Ritmo (mensagens/min)" hint="Cadência do disparo. A vazão do número é bem maior; devagar deixa a conexão livre para quem está conversando.">
            <input required type="number" min="1" max="60" className="zz-input" data-testid="campaign-rate"
              value={form.cadencia.por_minuto}
              onChange={(e) => setForm({ ...form, cadencia: { por_minuto: Number(e.target.value) } })} />
          </Campo>
          <Campo label="Agendar para" hint="Vazio = dispara ao clicar em Iniciar.">
            <input type="datetime-local" className="zz-input" data-testid="campaign-schedule"
              value={form.agendada_para} onChange={(e) => setForm({ ...form, agendada_para: e.target.value })} />
          </Campo>
          <Campo label="Quando o contato responder">
            <select className="zz-input" data-testid="campaign-reply-mode" value={form.resposta_modo}
              onChange={(e) => setForm({ ...form, resposta_modo: e.target.value, bot_id: e.target.value === "bot" ? form.bot_id : null })}>
              <option value="aguardando">Vai para a fila de atendimento</option>
              <option value="bot">Um robô atende primeiro</option>
            </select>
          </Campo>

          {form.resposta_modo === "bot" && (
            <Campo label="Robô que atende">
              <select required className="zz-input" data-testid="campaign-bot" value={form.bot_id || ""}
                onChange={(e) => setForm({ ...form, bot_id: e.target.value || null })}>
                <option value="">Selecione…</option>
                {bots.map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
              </select>
            </Campo>
          )}
          <Campo label="Departamento das respostas">
            <select className="zz-input" data-testid="campaign-department" value={form.departamento_id || ""}
              onChange={(e) => setForm({ ...form, departamento_id: e.target.value || null })}>
              <option value="">Padrão da conexão</option>
              {departamentos.map((d) => <option key={d.id} value={d.id}>{d.nome}</option>)}
            </select>
          </Campo>

        </Modal>
      )}

      <div className="border border-line bg-surface rounded-lg">
        {campanhas.length === 0 && !editando && (
          <div className="p-16 text-center">
            <div className="w-12 h-12 bg-brand text-brand-fg flex items-center justify-center mx-auto mb-3">
              <Megaphone size={22} weight="bold" />
            </div>
            <div className="font-heading text-2xl font-black tracking-tighter mb-2">Nenhuma campanha ainda.</div>
            <div className="text-sm text-ink-2">Crie a primeira para começar a disparar.</div>
          </div>
        )}
        {campanhas.map((c) => {
          const meta = STATUS_META[c.status] || STATUS_META.rascunho;
          const expandida = aberta === c.id;
          return (
            <div key={c.id} className="border-b border-line" data-testid={`campaign-row-${c.id}`}>
              <div className="grid grid-cols-12 gap-3 px-4 py-3 items-center hover:bg-surface-2">
                <button onClick={() => setAberta(expandida ? null : c.id)} className="col-span-4 flex items-center gap-2 text-left">
                  {expandida ? <CaretDown size={12} weight="bold" /> : <CaretRight size={12} weight="bold" />}
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{c.nome}</div>
                    <div className="text-[11px] text-ink-3 truncate">
                      {c.conteudo?.tipo === "template"
                        ? (c.conteudo?.template?.corpo || `modelo ${c.conteudo?.template?.nome || ""}`)
                        : c.conteudo?.texto}
                    </div>
                  </div>
                </button>
                <div className="col-span-2">
                  <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 border rounded-full ${meta.classe}`}>
                    {meta.label}
                  </span>
                  {c.agendada_para && c.status === "agendada" && (
                    <div className="text-[10px] font-mono text-ink-3 mt-1">
                      {new Date(c.agendada_para).toLocaleString("pt-BR")}
                    </div>
                  )}
                </div>
                <div className="col-span-3"><Progresso campanha={c} /></div>
                <div className="col-span-3 flex gap-1 justify-end">
                  {["rascunho", "pausada", "agendada"].includes(c.status) && (
                    <button title="Iniciar" data-testid={`campaign-start-${c.id}`}
                      onClick={() => acao(c, c.status === "pausada" ? "resume" : "start",
                        (d) => d.status === "agendada" ? "Campanha agendada" : `Disparando para ${d.pendentes} contato(s)`,
                        c.status === "rascunho" ? `Disparar "${c.nome}" agora?` : null)}
                      className="p-1.5 hover:bg-success-soft text-success"><Play size={14} weight="bold" /></button>
                  )}
                  {["enviando", "agendada"].includes(c.status) && (
                    <button title="Pausar" data-testid={`campaign-pause-${c.id}`}
                      onClick={() => acao(c, "pause", () => "Campanha pausada")}
                      className="p-1.5 hover:bg-warning-soft text-warning"><Pause size={14} weight="bold" /></button>
                  )}
                  {!["concluida", "cancelada"].includes(c.status) && (
                    <button title="Cancelar" onClick={() => acao(c, "cancel",
                      (d) => `Campanha cancelada (${d.descartados} não enviados)`,
                      `Cancelar "${c.nome}"? Quem ainda não recebeu não vai receber.`)}
                      className="p-1.5 hover:bg-danger-soft text-danger"><X size={14} weight="bold" /></button>
                  )}
                  {["rascunho", "agendada", "pausada"].includes(c.status) && (
                    <button title="Editar" onClick={() => abrirEdicao(c)} className="p-1.5 hover:bg-surface-3">
                      <PencilSimple size={14} weight="bold" />
                    </button>
                  )}
                  {c.status !== "enviando" && (
                    <button title="Excluir" onClick={() => excluir(c)} className="p-1.5 hover:bg-danger-soft text-danger">
                      <Trash size={14} weight="bold" />
                    </button>
                  )}
                </div>
              </div>
              {expandida && <Detalhe campanha={c} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
