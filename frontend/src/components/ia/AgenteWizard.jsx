import { useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { ArrowLeft, ArrowRight, Check, FloppyDisk } from "@phosphor-icons/react";
import { toast } from "sonner";

// Assistente em três passos: tipo → empresa → comportamento.
//
// O prompt não é escrito num campo em branco de propósito. Ninguém sabe
// escrever um bom prompt de sistema, mas todo mundo sabe responder "é vendas
// ou é suporte?" — o backend (`ai_agents.montar_instrucoes`) costura as peças.
// É por isso que quase tudo aqui é escolha e não texto livre.

const PASSOS = ["Tipo de agente", "Sobre a empresa", "Comportamento"];

const VAZIO = {
  nome: "",
  tipo: "",
  objetivo: "",
  modo: "fallback",
  ativo: true,
  empresa_nome: "",
  empresa_site: "",
  empresa_segmento: "",
  empresa_descricao: "",
  tom: [],
  tamanho: "normais",
  nao_fazer: "",
  base_conhecimento: "",
  escalar_quando: "",
  max_respostas: "",
  conexoes: [],
  departamento_id: "",
};

function Rotulo({ children, obrigatorio }) {
  return (
    <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">
      {children}
      {obrigatorio && <span className="text-danger ml-0.5">*</span>}
    </label>
  );
}

export default function AgenteWizard({ catalogo, conexoes, departamentos, agente, onFechar, onSalvo }) {
  const [passo, setPasso] = useState(0);
  const [salvando, setSalvando] = useState(false);
  const [form, setForm] = useState(() =>
    agente ? { ...VAZIO, ...agente, max_respostas: agente.max_respostas ?? "" } : { ...VAZIO },
  );

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const editando = Boolean(agente);

  const alternarTom = (id) =>
    set({ tom: form.tom.includes(id) ? form.tom.filter((t) => t !== id) : [...form.tom, id] });

  const alternarConexao = (id) =>
    set({
      conexoes: form.conexoes.includes(id)
        ? form.conexoes.filter((c) => c !== id)
        : [...form.conexoes, id],
    });

  // O que impede o avanço em cada passo. Barrar aqui é melhor que deixar o
  // backend recusar depois de três telas preenchidas.
  const bloqueio = [
    !form.tipo
      ? "Escolha o tipo de agente"
      : form.tipo === "personalizado" && !form.objetivo.trim()
        ? "Descreva o objetivo do agente personalizado"
        : null,
    null, // sobre a empresa é todo opcional: dá para criar e completar depois
    !form.nome.trim() ? "Dê um nome ao agente" : null,
  ][passo];

  const salvar = async () => {
    setSalvando(true);
    try {
      const corpo = {
        ...form,
        max_respostas: form.max_respostas === "" ? null : Number(form.max_respostas),
        departamento_id: form.departamento_id || null,
      };
      delete corpo.id;
      delete corpo.tenant_id;
      delete corpo.created_at;
      delete corpo.updated_at;
      const { data } = editando
        ? await api.patch(`/ai/agents/${agente.id}`, corpo)
        : await api.post("/ai/agents", corpo);
      toast.success(editando ? "Agente atualizado." : "Agente criado.");
      onSalvo(data);
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto"
      onClick={onFechar}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-surface border border-line-strong w-full max-w-2xl my-8 zz-panel-hard rounded-lg"
        data-testid="agente-wizard"
      >
        {/* Cabeçalho e trilha */}
        <div className="border-b border-line p-5">
          <div className="font-heading text-2xl font-black tracking-tighter mb-4">
            {editando ? "Editar agente" : "Novo agente de IA"}
          </div>
          <div className="flex items-center gap-2">
            {PASSOS.map((p, i) => (
              <div key={p} className="flex items-center gap-2 flex-1 last:flex-none">
                <div
                  className={`w-6 h-6 shrink-0 flex items-center justify-center text-[11px] font-bold border rounded-full ${
                    i < passo
                      ? "bg-brand border-brand text-brand-fg"
                      : i === passo
                        ? "bg-surface border-line text-ink"
                        : "bg-surface border-line text-ink-4"
                  }`}
                >
                  {i < passo ? <Check size={12} weight="bold" /> : i + 1}
                </div>
                <div
                  className={`text-[11px] font-bold uppercase tracking-wider whitespace-nowrap ${
                    i === passo ? "text-ink" : "text-ink-4"
                  }`}
                >
                  {p}
                </div>
                {i < PASSOS.length - 1 && <div className="h-px bg-surface-3 flex-1 min-w-4" />}
              </div>
            ))}
          </div>
        </div>

        <div className="p-5 space-y-5">
          {/* ---------------- Passo 1 ---------------- */}
          {passo === 0 && (
            <>
              <div>
                <div className="font-heading text-lg font-black tracking-tight">
                  Qual o objetivo principal do agente?
                </div>
                <p className="text-xs text-ink-2 mt-0.5">
                  É isso que define a estratégia dele na conversa. Tudo o mais ajusta por cima.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {catalogo.tipos.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => set({ tipo: t.id })}
                    data-testid={`agente-tipo-${t.id}`}
                    className={`border rounded-lg p-3 text-left transition-colors ${
                      form.tipo === t.id
                        ? "border-info bg-info-soft ring-1 ring-info"
                        : "border-line hover:border-line-strong"
                    }`}
                  >
                    <div className="font-bold text-sm">{t.rotulo}</div>
                    <div className="text-xs text-ink-2 mt-0.5">{t.descricao}</div>
                  </button>
                ))}
              </div>
              {form.tipo === "personalizado" && (
                <div>
                  <Rotulo obrigatorio>Objetivo do agente</Rotulo>
                  <textarea
                    className="zz-input min-h-24"
                    autoFocus
                    data-testid="agente-objetivo"
                    placeholder="Ex: Receber pedidos de orçamento de frete, coletar origem, destino e peso, e passar para a equipe."
                    value={form.objetivo}
                    onChange={(e) => set({ objetivo: e.target.value })}
                  />
                </div>
              )}
            </>
          )}

          {/* ---------------- Passo 2 ---------------- */}
          {passo === 1 && (
            <>
              <div>
                <div className="font-heading text-lg font-black tracking-tight">
                  Conte sobre a empresa
                </div>
                <p className="text-xs text-ink-2 mt-0.5">
                  Tudo aqui é opcional, mas é o que o agente vai saber. Sem isso ele é instruído a
                  transferir sempre que perguntarem preço, horário ou endereço — em vez de inventar.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Rotulo>Nome da empresa</Rotulo>
                  <input
                    className="zz-input"
                    data-testid="agente-empresa-nome"
                    placeholder="Ex: Vubis Tecnologia"
                    value={form.empresa_nome}
                    onChange={(e) => set({ empresa_nome: e.target.value })}
                  />
                </div>
                <div>
                  <Rotulo>Segmento</Rotulo>
                  <select
                    className="zz-input"
                    data-testid="agente-segmento"
                    value={form.empresa_segmento}
                    onChange={(e) => set({ empresa_segmento: e.target.value })}
                  >
                    <option value="">Selecione…</option>
                    {catalogo.segmentos.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <Rotulo>Site</Rotulo>
                <input
                  className="zz-input"
                  data-testid="agente-site"
                  placeholder="https://www.suaempresa.com.br"
                  value={form.empresa_site}
                  onChange={(e) => set({ empresa_site: e.target.value })}
                />
              </div>
              <div>
                <Rotulo>O que o agente precisa saber</Rotulo>
                <textarea
                  className="zz-input min-h-32"
                  data-testid="agente-base"
                  placeholder={
                    "Horário de funcionamento, endereço, formas de pagamento, prazo de entrega, " +
                    "produtos e preços, perguntas frequentes…"
                  }
                  value={form.base_conhecimento}
                  onChange={(e) => set({ base_conhecimento: e.target.value })}
                />
                <p className="text-[11px] text-ink-3 mt-1.5">
                  Esta é a única fonte de fatos do agente — ele é instruído a não inventar nada que
                  não esteja aqui. Quanto mais completo, menos transferências.
                </p>
              </div>
            </>
          )}

          {/* ---------------- Passo 3 ---------------- */}
          {passo === 2 && (
            <>
              <div>
                <div className="font-heading text-lg font-black tracking-tight">
                  Como o agente deve se comportar?
                </div>
                <p className="text-xs text-ink-2 mt-0.5">Ajuste fino de tom, tamanho e limites.</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Rotulo obrigatorio>Nome do agente</Rotulo>
                  <input
                    className="zz-input"
                    autoFocus
                    data-testid="agente-nome"
                    placeholder="Ex: Bia"
                    value={form.nome}
                    onChange={(e) => set({ nome: e.target.value })}
                  />
                  <p className="text-[11px] text-ink-3 mt-1">
                    É assim que ele se apresenta ao contato.
                  </p>
                </div>
                <div>
                  <Rotulo>Transferir depois de</Rotulo>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    className="zz-input"
                    data-testid="agente-max-respostas"
                    placeholder="10 respostas"
                    value={form.max_respostas}
                    onChange={(e) => set({ max_respostas: e.target.value })}
                  />
                  <p className="text-[11px] text-ink-3 mt-1">
                    Freio contra conversa que não termina. Vazio = 10.
                  </p>
                </div>
              </div>

              <div>
                <Rotulo>Tom de voz</Rotulo>
                <div className="flex flex-wrap gap-2">
                  {catalogo.tons.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => alternarTom(t.id)}
                      data-testid={`agente-tom-${t.id}`}
                      className={`px-3 py-1.5 text-xs font-bold border rounded-full transition-colors ${
                        form.tom.includes(t.id)
                          ? "bg-brand border-brand text-brand-fg"
                          : "bg-surface border-line hover:border-line-strong"
                      }`}
                    >
                      {t.rotulo}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <Rotulo>Tamanho das respostas</Rotulo>
                <div className="grid grid-cols-3 gap-3">
                  {catalogo.tamanhos.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => set({ tamanho: t.id })}
                      data-testid={`agente-tamanho-${t.id}`}
                      className={`border rounded-lg p-3 text-left transition-colors ${
                        form.tamanho === t.id
                          ? "border-info bg-info-soft ring-1 ring-info"
                          : "border-line hover:border-line-strong"
                      }`}
                    >
                      <div className="font-bold text-sm">{t.rotulo}</div>
                      <div className="text-[11px] text-ink-3">~{t.palavras} palavras</div>
                      <div className="text-[11px] text-ink-2 mt-1">{t.nota}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <Rotulo>O que o agente NÃO deve fazer</Rotulo>
                <textarea
                  className="zz-input min-h-20"
                  data-testid="agente-nao-fazer"
                  placeholder={"Uma regra por linha.\nEx: Não dar desconto\nNão prometer prazo de entrega"}
                  value={form.nao_fazer}
                  onChange={(e) => set({ nao_fazer: e.target.value })}
                />
              </div>

              <div>
                <Rotulo>Transferir para uma pessoa também quando</Rotulo>
                <textarea
                  className="zz-input min-h-16"
                  data-testid="agente-escalar"
                  placeholder={"Uma situação por linha.\nEx: Pedirem segunda via de boleto"}
                  value={form.escalar_quando}
                  onChange={(e) => set({ escalar_quando: e.target.value })}
                />
                <p className="text-[11px] text-ink-3 mt-1.5">
                  Pedido explícito de atendente, reclamação, cancelamento e falta de informação já
                  transferem sozinhos — isto é só o que for específico da sua operação.
                </p>
              </div>

              <div className="border-t border-line pt-5 space-y-4">
                <div>
                  <Rotulo>Quando o agente entra</Rotulo>
                  <div className="space-y-2">
                    {catalogo.modos.map((m) => (
                      <label
                        key={m.id}
                        className={`flex items-start gap-3 border rounded-lg p-3 cursor-pointer transition-colors ${
                          form.modo === m.id
                            ? "border-info bg-info-soft"
                            : "border-line hover:border-line-strong"
                        }`}
                      >
                        <input
                          type="radio"
                          name="modo"
                          className="mt-1"
                          checked={form.modo === m.id}
                          onChange={() => set({ modo: m.id })}
                          data-testid={`agente-modo-${m.id}`}
                        />
                        <div>
                          <div className="font-bold text-sm">{m.rotulo}</div>
                          <div className="text-xs text-ink-2">{m.nota}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Rotulo>Em quais conexões</Rotulo>
                    <div className="border border-line p-3 max-h-32 overflow-y-auto space-y-1 rounded-lg">
                      {conexoes.length === 0 && (
                        <div className="text-xs text-ink-3 p-1">Nenhuma conexão cadastrada.</div>
                      )}
                      {conexoes.map((c) => (
                        <label key={c.id} className="flex items-center gap-2 text-sm p-1 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={form.conexoes.includes(c.id)}
                            onChange={() => alternarConexao(c.id)}
                            data-testid={`agente-conexao-${c.id}`}
                          />
                          {c.nome}
                        </label>
                      ))}
                    </div>
                    <p className="text-[11px] text-ink-3 mt-1">
                      Nenhuma marcada = todas, inclusive as que você criar depois.
                    </p>
                  </div>
                  <div>
                    <Rotulo>Transferir para o departamento</Rotulo>
                    <select
                      className="zz-input"
                      data-testid="agente-departamento"
                      value={form.departamento_id || ""}
                      onChange={(e) => set({ departamento_id: e.target.value })}
                    >
                      <option value="">Padrão da conexão</option>
                      {departamentos.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.nome}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Rodapé */}
        <div className="border-t border-line p-4 flex items-center justify-between gap-3">
          <button
            type="button"
            className="zz-btn zz-btn-secondary"
            onClick={passo === 0 ? onFechar : () => setPasso(passo - 1)}
            data-testid="agente-voltar"
          >
            <ArrowLeft size={14} weight="bold" /> {passo === 0 ? "Cancelar" : "Voltar"}
          </button>
          <div className="flex items-center gap-3">
            {bloqueio && <span className="text-xs text-ink-3">{bloqueio}</span>}
            {passo < PASSOS.length - 1 ? (
              <button
                type="button"
                className="zz-btn"
                disabled={Boolean(bloqueio)}
                onClick={() => setPasso(passo + 1)}
                data-testid="agente-proximo"
              >
                Próximo <ArrowRight size={14} weight="bold" />
              </button>
            ) : (
              <button
                type="button"
                className="zz-btn"
                disabled={Boolean(bloqueio) || salvando}
                onClick={salvar}
                data-testid="agente-salvar"
              >
                <FloppyDisk size={14} weight="bold" />
                {salvando ? "Salvando…" : editando ? "Salvar" : "Criar agente"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
