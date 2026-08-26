import { useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import {
  ArrowLeft, ArrowRight, Check, FloppyDisk, ArrowSquareOut, Key,
  ShoppingCart, Target, Headset, ChatCircleDots, CalendarBlank, Star,
  Lightning, TextAlignLeft, Article, Lifebuoy, Flag, Prohibit,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import FotosAgente from "./FotosAgente";

// Custo mensal estimado por modelo, para a empresa escolher com numero na
// frente em vez de pelo nome. A carga de referencia e a de um cliente medio:
// 50 atendimentos/dia x 6 respostas x 30 dias = 9.000 respostas, cada uma com
// ~1.800 tokens de entrada (dos quais ~1.500 vem do cache) e ~120 de saida.
//
// A conta e feita aqui, e nao no servidor, porque e uma projecao para a tela —
// o consumo real vem medido de `ai_usage`.
const RESPOSTAS_MES = 9000;
const ENTRADA_NAO_CACHEADA = 330;
const ENTRADA_CACHEADA = 1500;
const SAIDA = 120;
// Cambio so para dar ordem de grandeza. Nao e cotacao: o provedor cobra em
// dolar, direto na conta do cliente.
const USD_BRL = 5.5;

function custoMensal(m) {
  const cacheLeitura = m.cache_leitura ?? m.entrada * 0.1;
  const usd =
    (RESPOSTAS_MES *
      (ENTRADA_NAO_CACHEADA * m.entrada + ENTRADA_CACHEADA * cacheLeitura + SAIDA * m.saida)) /
    1_000_000;
  return (usd * USD_BRL).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 0,
  });
}

// Assistente em três passos: tipo → empresa → comportamento.
//
// O prompt não é escrito num campo em branco de propósito. Ninguém sabe
// escrever um bom prompt de sistema, mas todo mundo sabe responder "é vendas
// ou é suporte?" — o backend (`ai_agents.montar_instrucoes`) costura as peças.
// É por isso que quase tudo aqui é escolha e não texto livre.

// Ícone por tipo de agente. Mora aqui, e não no catálogo do backend, porque é
// decoração de tela: o servidor não deveria saber o nome de um componente de
// ícone. Tipo sem entrada cai no genérico em vez de sumir.
const ICONES = {
  vendas: ShoppingCart,
  sdr: Target,
  suporte: Headset,
  geral: ChatCircleDots,
  agendamento: CalendarBlank,
  personalizado: Star,
};

const ICONES_TAMANHO = {
  curtas: Lightning,
  normais: TextAlignLeft,
  detalhadas: Article,
};

const ICONES_MODO = {
  fallback: Lifebuoy,
  primeiro: Flag,
  desligado: Prohibit,
};

const PASSOS = ["Tipo de agente", "Sobre a empresa", "Comportamento", "Modelo e chave"];

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
  instrucoes: "",
  nao_fazer: "",
  base_conhecimento: "",
  escalar_quando: "",
  max_respostas: "",
  conexoes: [],
  departamento_id: "",
  provedor: "",
  modelo: "",
  chave_api: "",
};

function Rotulo({ children, obrigatorio }) {
  return (
    <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">
      {children}
      {obrigatorio && <span className="text-danger ml-0.5">*</span>}
    </label>
  );
}

export default function AgenteWizard({
  catalogo, provedores, plataformaDisponivel, conexoes, departamentos, agente, onFechar, onSalvo,
}) {
  const [passo, setPasso] = useState(0);
  const [salvando, setSalvando] = useState(false);
  const [form, setForm] = useState(() =>
    agente ? { ...VAZIO, ...agente, max_respostas: agente.max_respostas ?? "" } : { ...VAZIO },
  );

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const provedorAtual = (provedores || []).find((p) => p.id === form.provedor);
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
    // Sem provedor o agente cai na chave da plataforma. É um estado válido —
    // só não é, quando não existe chave da plataforma para cair.
    !form.provedor && !plataformaDisponivel
      ? "Escolha o provedor e informe a chave"
      : form.provedor && !form.chave_api.trim() && !(agente?.tem_chave && agente.provedor === form.provedor)
        ? "Cole a chave de API"
        : null,
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
        className="bg-surface w-full max-w-4xl my-8 zz-panel-hard overflow-hidden"
        data-testid="agente-wizard"
      >
        {/* Cabeçalho e trilha */}
        <div className="border-b border-line p-6">
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

        <div className="p-6 space-y-6">
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
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {catalogo.tipos.map((t) => {
                  const Icone = ICONES[t.id] || Star;
                  const escolhido = form.tipo === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => set({ tipo: t.id })}
                      data-testid={`agente-tipo-${t.id}`}
                      className={`border rounded-xl p-4 text-left transition-colors h-full ${
                        escolhido
                          ? "border-info bg-info-soft ring-1 ring-info"
                          : "border-line hover:border-line-strong hover:bg-surface-2"
                      }`}
                    >
                      <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3 ${
                        escolhido ? "bg-info text-brand-fg" : "bg-surface-3 text-ink-2"
                      }`}>
                        <Icone size={20} weight="bold" />
                      </div>
                      <div className="font-bold text-sm">{t.rotulo}</div>
                      <div className="text-xs text-ink-2 mt-1 leading-snug">{t.descricao}</div>
                    </button>
                  );
                })}
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

              <div>
                <Rotulo>Fotos que o agente pode enviar</Rotulo>
                <p className="text-xs text-ink-2 mb-3 -mt-1">
                  O agente manda a foto sozinho quando a conversa pedir — o cliente diz que gostou
                  do carro, ele mostra. Quem escolhe é ele, pela descrição de cada uma.
                </p>
                <FotosAgente agente={agente} />
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

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {catalogo.tamanhos.map((t) => {
                    const Icone = ICONES_TAMANHO[t.id] || TextAlignLeft;
                    const escolhido = form.tamanho === t.id;
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => set({ tamanho: t.id })}
                        data-testid={`agente-tamanho-${t.id}`}
                        className={`border rounded-xl p-4 text-left transition-colors h-full ${
                          escolhido
                            ? "border-info bg-info-soft ring-1 ring-info"
                            : "border-line hover:border-line-strong hover:bg-surface-2"
                        }`}
                      >
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center mb-2.5 ${
                          escolhido ? "bg-info text-brand-fg" : "bg-surface-3 text-ink-2"
                        }`}>
                          <Icone size={18} weight="bold" />
                        </div>
                        <div className="font-bold text-sm">{t.rotulo}</div>
                        <div className="text-[11px] text-ink-3">~{t.palavras} palavras</div>
                        <div className="text-[11px] text-ink-2 mt-1 leading-snug">{t.nota}</div>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <Rotulo>Instruções específicas</Rotulo>
                <textarea
                  className="zz-input min-h-32"
                  data-testid="agente-instrucoes"
                  placeholder={
                    "Escreva livremente o que o agente precisa seguir.\n\n" +
                    "Ex: Sempre pergunte a cidade antes de falar de frete.\n" +
                    "Trate quem já é cliente pelo primeiro nome.\n" +
                    "Se perguntarem de parcelamento, diga que vai até 12x sem juros."
                  }
                  value={form.instrucoes}
                  onChange={(e) => set({ instrucoes: e.target.value })}
                />
                <p className="text-[11px] text-ink-3 mt-1.5">
                  Fica guardado no agente e vai junto em <strong>toda</strong> mensagem que ele
                  responde. É onde entra o que as opções acima não cobrem.
                </p>
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
                    {catalogo.modos.map((m) => {
                      const Icone = ICONES_MODO[m.id] || Lifebuoy;
                      const escolhido = form.modo === m.id;
                      return (
                        <label
                          key={m.id}
                          className={`flex items-center gap-3 border rounded-xl p-3.5 cursor-pointer transition-colors ${
                            escolhido
                              ? "border-info bg-info-soft ring-1 ring-info"
                              : "border-line hover:border-line-strong hover:bg-surface-2"
                          }`}
                        >
                          {/* O radio nativo fica so para teclado e leitor de tela:
                              o cartao inteiro e o alvo de clique, e a selecao e
                              sinalizada pela borda de informacao + o icone cheio. */}
                          <input
                            type="radio"
                            name="modo"
                            className="sr-only"
                            checked={escolhido}
                            onChange={() => set({ modo: m.id })}
                            data-testid={`agente-modo-${m.id}`}
                          />
                          <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                            escolhido ? "bg-info text-brand-fg" : "bg-surface-3 text-ink-2"
                          }`}>
                            <Icone size={18} weight="bold" />
                          </div>
                          <div className="min-w-0">
                            <div className="font-bold text-sm">{m.rotulo}</div>
                            <div className="text-xs text-ink-2">{m.nota}</div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

          {/* ---------------- Passo 4 ---------------- */}
          {passo === 3 && (
            <>
              <div>
                <div className="font-heading text-lg font-bold tracking-tight">
                  Qual IA responde por este agente?
                </div>
                <p className="text-xs text-ink-2 mt-0.5">
                  A chave é deste agente, não da empresa — dá para ter um agente na Anthropic e
                  outro na OpenAI, com contas separadas.
                </p>
              </div>

              <div>
                <Rotulo>Provedor</Rotulo>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {(provedores || []).map((p) => (
                    <button key={p.id} type="button"
                      onClick={() => set({
                        provedor: p.id,
                        modelo: p.modelos[0]?.id || "",
                        chave_api: "",
                      })}
                      data-testid={`agente-provedor-${p.id}`}
                      className={`border rounded-lg p-3 text-left transition-colors ${
                        form.provedor === p.id
                          ? "border-info bg-info-soft ring-1 ring-info"
                          : "border-line hover:border-line-strong"
                      }`}>
                      <div className="font-bold text-sm">{p.rotulo}</div>
                    </button>
                  ))}
                  {plataformaDisponivel && (
                    <button type="button"
                      onClick={() => set({ provedor: "", modelo: "", chave_api: "" })}
                      data-testid="agente-provedor-plataforma"
                      className={`border rounded-lg p-3 text-left transition-colors sm:col-span-2 ${
                        !form.provedor
                          ? "border-info bg-info-soft ring-1 ring-info"
                          : "border-line hover:border-line-strong"
                      }`}>
                      <div className="font-bold text-sm">Usar a IA inclusa no plano</div>
                      <div className="text-xs text-ink-2 mt-0.5">
                        Sem chave própria. Vale o limite mensal de tokens do seu plano.
                      </div>
                    </button>
                  )}
                </div>
              </div>

              {provedorAtual && (
                <>
                  <div>
                    <Rotulo>Modelo</Rotulo>
                    <div className="space-y-2">
                      {provedorAtual.modelos.map((m) => (
                        <label key={m.id}
                          className={`flex items-start gap-3 border rounded-lg p-3 cursor-pointer transition-colors ${
                            form.modelo === m.id
                              ? "border-info bg-info-soft"
                              : "border-line hover:border-line-strong"
                          }`}>
                          <input type="radio" name="modelo" className="mt-1"
                            checked={form.modelo === m.id}
                            onChange={() => set({ modelo: m.id })}
                            data-testid={`agente-modelo-${m.id}`} />
                          <div className="flex-1 min-w-0">
                            <div className="font-bold text-sm">{m.rotulo}</div>
                            <div className="text-xs text-ink-2">{m.nota}</div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="font-heading font-bold text-sm">~{custoMensal(m)}</div>
                            <div className="text-[10px] text-ink-3">por mês</div>
                          </div>
                        </label>
                      ))}
                    </div>
                    <p className="text-[11px] text-ink-3 mt-2">
                      Estimativa para 50 atendimentos por dia (~9.000 respostas no mês). O provedor
                      cobra em dólar, direto na conta da empresa.
                    </p>
                  </div>

                  <div>
                    <div className="flex items-center justify-between gap-3 mb-1.5">
                      <Rotulo>Chave de API</Rotulo>
                      <a href={provedorAtual.console_url} target="_blank" rel="noreferrer"
                        className="zz-btn zz-btn-secondary text-xs py-1"
                        data-testid="agente-abrir-console">
                        <ArrowSquareOut size={13} weight="bold" /> Abrir o console
                      </a>
                    </div>
                    <div className="relative">
                      <Key size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
                      <input type="password" autoComplete="off"
                        className="zz-input pl-9 font-mono"
                        placeholder={
                          agente?.tem_chave && agente.provedor === form.provedor
                            ? `Chave atual ${agente.mascara} — deixe em branco para manter`
                            : `Cole a chave (começa com ${form.provedor === "anthropic" ? "sk-ant-" : "sk-"})`
                        }
                        value={form.chave_api}
                        onChange={(e) => set({ chave_api: e.target.value })}
                        data-testid="agente-chave" />
                    </div>
                    <p className="text-[11px] text-ink-3 mt-1.5">
                      Guardada cifrada e nunca exibida de volta — só os últimos dígitos. Ao salvar,
                      fazemos uma chamada de teste para confirmar que ela funciona neste modelo.
                    </p>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {/* Rodapé */}
        <div className="border-t border-line p-5 flex items-center justify-between gap-3">
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
                {salvando ? (form.provedor ? "Testando a chave…" : "Salvando…")
                  : editando ? "Salvar" : "Criar agente"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
