import { useCallback, useEffect, useRef, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import { formatBRL, parseBRLInput } from "@/lib/currency";
import Atividades from "@/components/activities/Atividades";
import {
  X, PaperPlaneRight, Trash, Prohibit, Check, ChatCircleDots, Megaphone,
  NotePencil, Warning, ArrowSquareOut, Funnel, Plus,
} from "@phosphor-icons/react";

const KANBAN_LABEL = {
  bot: "com o robô",
  aguardando: "aguardando",
  em_atendimento: "em atendimento",
  finalizado: "finalizado",
};

function Bloco({ titulo, children, acao }) {
  return (
    <div className="border-t border-slate-200 px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">{titulo}</div>
        {acao}
      </div>
      {children}
    </div>
  );
}

function Linha({ label, children }) {
  return (
    <div className="grid grid-cols-3 gap-2 items-center py-1">
      <label className="text-xs font-bold uppercase tracking-wider text-slate-500">{label}</label>
      <div className="col-span-2">{children}</div>
    </div>
  );
}

function CampoPersonalizado({ campo, valor, onChange }) {
  const comum = { className: "zz-input h-8 py-1 text-sm", value: valor ?? "" };
  if (campo.tipo === "selecao") {
    return (
      <select {...comum} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {(campo.opcoes || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  const tipo = campo.tipo === "numero" ? "number" : campo.tipo === "data" ? "date" : "text";
  return <input {...comum} type={tipo} onChange={(e) => onChange(e.target.value)} />;
}

export default function ContactPanel({ contactId, onClose, onSaved }) {
  const [ficha, setFicha] = useState(null);
  const [form, setForm] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [conexoes, setConexoes] = useState([]);
  const [nota, setNota] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [conexaoEnvio, setConexaoEnvio] = useState("");
  const [negocios, setNegocios] = useState([]);
  const [criandoNegocio, setCriandoNegocio] = useState(null);
  const [funis, setFunis] = useState([]);
  const [enviando, setEnviando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const areaRef = useRef(null);

  const carregar = useCallback(() => {
    api.get(`/contacts/${contactId}`).then((r) => {
      setFicha(r.data);
      const c = r.data.contact;
      setForm({
        nome: c.nome || "",
        email: c.email || "",
        empresa: c.empresa || "",
        cargo: c.cargo || "",
        origem: c.origem || "",
        responsavel_id: c.responsavel_id || "",
        tags: (c.tags || []).join(", "),
        campos: Object.fromEntries((r.data.campos || []).map((f) => [f.id, f.valor ?? ""])),
      });
    }).catch((ex) => {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
      onClose();
    });
  }, [contactId, onClose]);

  const carregarNegocios = useCallback(() => {
    api.get("/deals", { params: { contact_id: contactId } })
      .then((r) => setNegocios(r.data.items || [])).catch(() => {});
  }, [contactId]);

  useEffect(() => { carregar(); carregarNegocios(); }, [carregar, carregarNegocios]);

  useEffect(() => {
    api.get("/users").then((r) => setUsuarios(r.data)).catch(() => {});
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/pipelines").then((r) => setFunis(r.data)).catch(() => {});
  }, []);

  const salvar = async () => {
    setSalvando(true);
    try {
      await api.patch(`/contacts/${contactId}`, {
        ...form,
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
        responsavel_id: form.responsavel_id || null,
      });
      toast.success("Ficha salva");
      carregar();
      onSaved?.();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setSalvando(false);
    }
  };

  const alternarOptOut = async () => {
    const atual = ficha.contact.opt_out;
    if (!atual && !(await confirmToast(
      "Marcar como 'não receber campanhas'? Ele fica fora de todos os disparos.",
      { confirmLabel: "Marcar" }))) return;
    try {
      await api.patch(`/contacts/${contactId}`, { opt_out: !atual });
      carregar();
      onSaved?.();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const adicionarNota = async (e) => {
    e.preventDefault();
    if (!nota.trim()) return;
    try {
      await api.post(`/contacts/${contactId}/notes`, { texto: nota });
      setNota("");
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const removerNota = async (id) => {
    if (!(await confirmToast("Excluir esta anotação?", { confirmLabel: "Excluir" }))) return;
    await api.delete(`/contacts/${contactId}/notes/${id}`);
    carregar();
  };

  const criarNegocio = async (e) => {
    e.preventDefault();
    try {
      await api.post("/deals", {
        titulo: criandoNegocio.titulo,
        contact_id: contactId,
        pipeline_id: criandoNegocio.pipeline_id,
        valor: criandoNegocio.valor,
      });
      setCriandoNegocio(null);
      toast.success("Negócio criado no funil");
      carregarNegocios();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const enviar = async (e) => {
    e.preventDefault();
    if (!mensagem.trim() || enviando) return;
    setEnviando(true);
    try {
      const r = await api.post(`/contacts/${contactId}/send`, {
        texto: mensagem,
        whatsapp_connection_id: conexaoEnvio || null,
      });
      setMensagem("");
      toast.success(r.data.criada ? "Conversa iniciada e mensagem enviada" : "Mensagem enviada");
      carregar();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setEnviando(false);
    }
  };

  if (!ficha || !form) {
    return (
      <aside className="fixed right-0 top-0 h-screen w-[520px] bg-white border-l-2 border-slate-900 z-40 flex items-center justify-center">
        <div className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">Carregando ficha…</div>
      </aside>
    );
  }

  const c = ficha.contact;
  const r = ficha.resumo;
  const conectadas = conexoes.filter((x) => x.status === "conectado");

  return (
    <aside className="fixed right-0 top-0 h-screen w-[520px] bg-white border-l-2 border-slate-900 z-40 flex flex-col"
      data-testid="contact-panel">
      <div className="px-5 py-4 border-b border-slate-900 flex items-start gap-3">
        {c.foto_url
          ? <img src={c.foto_url} alt="" className="w-11 h-11 border border-slate-900 object-cover" />
          : <div className="w-11 h-11 bg-slate-900 text-white flex items-center justify-center font-heading font-black">
              {(c.nome || "?").charAt(0).toUpperCase()}
            </div>}
        <div className="flex-1 min-w-0">
          <div className="font-heading text-xl font-black tracking-tighter truncate">{c.nome}</div>
          <div className="font-mono text-xs text-slate-600">{c.numero_whatsapp}</div>
        </div>
        <button onClick={onClose} data-testid="contact-panel-close" className="p-1.5 hover:bg-slate-200">
          <X size={16} weight="bold" />
        </button>
      </div>

      {c.opt_out && (
        <div className="px-5 py-2 bg-red-50 border-b border-red-300 text-xs text-red-800 flex items-center gap-2">
          <Prohibit size={13} weight="bold" />
          Não recebe campanhas{c.opt_out_em ? ` desde ${new Date(c.opt_out_em).toLocaleDateString("pt-BR")}` : ""}.
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        <div className="grid grid-cols-4 border-b border-slate-200">
          {[["Conversas", r.conversas], ["Mensagens", r.mensagens],
            ["Campanhas", r.campanhas_recebidas], ["Respostas", r.campanhas_respondidas]].map(([k, v]) => (
            <div key={k} className="px-3 py-2.5 border-r border-slate-200 last:border-r-0">
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">{k}</div>
              <div className="font-heading text-lg font-black tracking-tighter">{v}</div>
            </div>
          ))}
        </div>

        <Bloco titulo="Dados" acao={
          <button onClick={salvar} disabled={salvando} className="zz-btn text-xs py-1 disabled:opacity-40"
            data-testid="contact-save">{salvando ? "Salvando…" : "Salvar"}</button>
        }>
          <Linha label="Nome">
            <input className="zz-input h-8 py-1 text-sm" data-testid="contact-field-nome" value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })} />
          </Linha>
          <Linha label="E-mail">
            <input className="zz-input h-8 py-1 text-sm" type="email" data-testid="contact-field-email"
              value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Linha>
          <Linha label="Empresa">
            <input className="zz-input h-8 py-1 text-sm" value={form.empresa}
              onChange={(e) => setForm({ ...form, empresa: e.target.value })} />
          </Linha>
          <Linha label="Cargo">
            <input className="zz-input h-8 py-1 text-sm" value={form.cargo}
              onChange={(e) => setForm({ ...form, cargo: e.target.value })} />
          </Linha>
          <Linha label="Origem">
            <input className="zz-input h-8 py-1 text-sm" value={form.origem}
              placeholder="ex: indicação, site, feira"
              onChange={(e) => setForm({ ...form, origem: e.target.value })} />
          </Linha>
          <Linha label="Responsável">
            <select className="zz-input h-8 py-1 text-sm" data-testid="contact-field-responsavel"
              value={form.responsavel_id} onChange={(e) => setForm({ ...form, responsavel_id: e.target.value })}>
              <option value="">Sem responsável</option>
              {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
            </select>
          </Linha>
          <Linha label="Etiquetas">
            <input className="zz-input h-8 py-1 text-sm" data-testid="contact-field-tags" value={form.tags}
              placeholder="vip, cliente, lead frio"
              onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </Linha>
          <Linha label="Campanhas">
            <button onClick={alternarOptOut} data-testid="contact-optout-toggle"
              className={`flex items-center gap-1.5 px-2 py-1 text-xs font-bold uppercase tracking-wider border ${
                c.opt_out ? "border-red-500 bg-red-50 text-red-700" : "border-green-500 bg-green-50 text-green-700"
              }`}>
              {c.opt_out ? <Prohibit size={12} weight="bold" /> : <Check size={12} weight="bold" />}
              {c.opt_out ? "não recebe" : "recebe"}
            </button>
          </Linha>
        </Bloco>

        {ficha.campos.length > 0 && (
          <Bloco titulo="Campos personalizados">
            {ficha.campos.map((campo) => (
              <Linha key={campo.id} label={campo.nome}>
                <CampoPersonalizado campo={campo} valor={form.campos[campo.id]}
                  onChange={(v) => setForm({ ...form, campos: { ...form.campos, [campo.id]: v } })} />
              </Linha>
            ))}
            <div className="text-[10px] text-slate-500 mt-2">Salve em "Dados" para gravar também estes campos.</div>
          </Bloco>
        )}

        <Bloco titulo={`Anotações (${ficha.notas.length})`}>
          <form onSubmit={adicionarNota} className="flex gap-2 mb-3">
            <input className="zz-input h-8 py-1 text-sm flex-1" data-testid="contact-note-input"
              placeholder="Ligou dia 12, quer proposta até sexta…"
              value={nota} onChange={(e) => setNota(e.target.value)} />
            <button type="submit" className="zz-btn text-xs py-1"><NotePencil size={13} weight="bold" /></button>
          </form>
          {ficha.notas.length === 0 && <div className="text-xs text-slate-400">Nenhuma anotação.</div>}
          <div className="space-y-2">
            {ficha.notas.map((n) => (
              <div key={n.id} className="border border-slate-200 bg-slate-50 px-3 py-2" data-testid={`note-${n.id}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm text-slate-800 whitespace-pre-wrap flex-1">{n.texto}</div>
                  <button onClick={() => removerNota(n.id)} className="p-0.5 hover:bg-red-100 text-red-600 shrink-0">
                    <Trash size={12} weight="bold" />
                  </button>
                </div>
                <div className="text-[10px] font-mono text-slate-500 mt-1">
                  {n.autor_nome} · {new Date(n.created_at).toLocaleString("pt-BR")}
                </div>
              </div>
            ))}
          </div>
        </Bloco>

        <Bloco titulo="Próximos passos">
          <Atividades vinculo={{ contact_id: contactId }} />
        </Bloco>

        <Bloco titulo={`Negócios (${negocios.length})`} acao={
          funis.length > 0 && (
            <button onClick={() => setCriandoNegocio({
              titulo: `Negócio — ${c.nome}`, valor: 0, pipeline_id: funis[0].id,
            })} className="zz-btn text-xs py-1" data-testid="contact-new-deal">
              <Plus size={12} weight="bold" /> Novo
            </button>
          )
        }>
          {criandoNegocio && (
            <form onSubmit={criarNegocio} className="border border-slate-300 bg-slate-50 p-2 mb-3 space-y-2"
              data-testid="contact-deal-form">
              <input required autoFocus className="zz-input h-8 py-1 text-sm" value={criandoNegocio.titulo}
                onChange={(e) => setCriandoNegocio({ ...criandoNegocio, titulo: e.target.value })} />
              <div className="flex gap-2">
                <input className="zz-input h-8 py-1 text-sm font-mono flex-1"
                  value={formatBRL(criandoNegocio.valor)}
                  onChange={(e) => setCriandoNegocio({
                    ...criandoNegocio, valor: parseBRLInput(e.target.value),
                  })} />
                {funis.length > 1 && (
                  <select className="zz-input h-8 py-1 text-sm" value={criandoNegocio.pipeline_id}
                    onChange={(e) => setCriandoNegocio({ ...criandoNegocio, pipeline_id: e.target.value })}>
                    {funis.map((f) => <option key={f.id} value={f.id}>{f.nome}</option>)}
                  </select>
                )}
                <button type="submit" className="zz-btn text-xs py-1">Criar</button>
                <button type="button" onClick={() => setCriandoNegocio(null)}
                  className="zz-btn zz-btn-secondary text-xs py-1">Cancelar</button>
              </div>
            </form>
          )}
          {negocios.length === 0 && !criandoNegocio && (
            <div className="text-xs text-slate-400">Nenhum negócio para este contato.</div>
          )}
          <div className="space-y-1.5">
            {negocios.map((n) => (
              <a key={n.id} href={`/app/funil?negocio=${n.id}`}
                className="flex items-center gap-2 border border-slate-200 px-3 py-2 hover:bg-slate-50"
                data-testid={`contact-deal-${n.id}`}>
                <Funnel size={14} weight="bold" className="text-slate-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold truncate">{n.titulo}</div>
                  <div className="text-[10px] font-mono text-slate-500">{formatBRL(n.valor)}</div>
                </div>
                <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 border shrink-0 ${
                  n.status === "ganho" ? "border-green-500 bg-green-50 text-green-700"
                    : n.status === "perdido" ? "border-red-500 bg-red-50 text-red-700"
                    : "border-slate-300 bg-slate-50 text-slate-600"
                }`}>
                  {n.status}
                </span>
              </a>
            ))}
          </div>
        </Bloco>

        <Bloco titulo={`Conversas (${ficha.conversas.length})`}>
          {ficha.conversas.length === 0 && <div className="text-xs text-slate-400">Nenhuma conversa ainda.</div>}
          <div className="space-y-1.5">
            {ficha.conversas.map((s) => (
              <a key={s.id} href={`/app/inbox?session=${s.id}`}
                className="flex items-center gap-2 border border-slate-200 px-3 py-2 hover:bg-slate-50">
                <ChatCircleDots size={14} weight="bold" className="text-slate-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs truncate text-slate-700">
                    {s.last_message?.content || "(sem mensagens)"}
                  </div>
                  <div className="text-[10px] font-mono text-slate-500">
                    {KANBAN_LABEL[s.status_atendimento] || s.status_atendimento}
                    {s.origem === "campanha" ? " · via campanha" : s.origem === "direta" ? " · iniciada por nós" : ""}
                    {" · "}{new Date(s.updated_at).toLocaleDateString("pt-BR")}
                  </div>
                </div>
                <ArrowSquareOut size={12} weight="bold" className="text-slate-400 shrink-0" />
              </a>
            ))}
          </div>
        </Bloco>

        {ficha.campanhas.length > 0 && (
          <Bloco titulo={`Campanhas recebidas (${ficha.campanhas.length})`}>
            <div className="space-y-1.5">
              {ficha.campanhas.map((k) => (
                <div key={`${k.campaign_id}-${k.sent_at}`} className="flex items-center gap-2 border border-slate-200 px-3 py-2">
                  <Megaphone size={14} weight="bold" className="text-slate-500 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold truncate">{k.nome}</div>
                    <div className="text-[10px] font-mono text-slate-500">
                      {k.status}{k.sent_at ? ` · ${new Date(k.sent_at).toLocaleDateString("pt-BR")}` : ""}
                      {k.erro ? ` · ${k.erro}` : ""}
                    </div>
                  </div>
                  {k.respondeu && (
                    <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 border border-green-500 bg-green-50 text-green-700 shrink-0">
                      respondeu
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Bloco>
        )}
      </div>

      <form onSubmit={enviar} className="border-t-2 border-slate-900 p-3 bg-slate-50" data-testid="contact-send-form">
        {conectadas.length === 0 ? (
          <div className="text-xs text-slate-600 flex items-center gap-2">
            <Warning size={14} weight="bold" className="text-amber-600" />
            Nenhuma conexão de WhatsApp conectada — não é possível enviar agora.
          </div>
        ) : (
          <>
            {c.opt_out && (
              <div className="text-[11px] text-amber-800 mb-2 flex items-start gap-1.5">
                <Warning size={12} weight="bold" className="mt-0.5 shrink-0" />
                Este contato pediu para não receber campanhas. Mensagem direta ainda é permitida —
                a recusa vale para disparo em massa, não para atendimento.
              </div>
            )}
            <div className="flex gap-2 items-end">
              <textarea ref={areaRef} rows={2} required data-testid="contact-send-text"
                className="zz-input flex-1 text-sm font-sans resize-none"
                placeholder="Escrever para este contato…"
                value={mensagem} onChange={(e) => setMensagem(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(e); }
                }} />
              <button type="submit" disabled={enviando || !mensagem.trim()}
                data-testid="contact-send-btn" className="zz-btn disabled:opacity-40">
                <PaperPlaneRight size={14} weight="bold" />
              </button>
            </div>
            {conectadas.length > 1 && (
              <select className="zz-input h-7 py-0 text-xs mt-2" data-testid="contact-send-connection"
                value={conexaoEnvio} onChange={(e) => setConexaoEnvio(e.target.value)}>
                <option value="">Número da última conversa</option>
                {conectadas.map((x) => <option key={x.id} value={x.id}>{x.nome}</option>)}
              </select>
            )}
          </>
        )}
      </form>
    </aside>
  );
}
