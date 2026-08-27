import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash, FloppyDisk } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { CampoDuracao, emHoras } from "./CampoHora";

// Preferências de agendamento da empresa.
//
// **O fuso saiu da tela a pedido do cliente**, e Brasília é o padrão. Ele
// continua existindo no banco e na API (`scheduling_settings.fuso`) porque é
// dele que a grade e o lembrete tiram a hora: o robô roda no servidor e não
// tem como descobrir isso sozinho. O que mudou é que ninguém escolhe: uma
// empresa fora do horário de Brasília é caso de suporte, não de um campo que
// todos os outros clientes precisam entender para ignorar.

const PASSOS = [10, 15, 20, 30, 60];

export default function Configuracao({ config, onSalvo }) {
  const [form, setForm] = useState(() => ({
    ...config,
    bloqueios: config.bloqueios || [],
    mensagem_lembrete: config.mensagem_lembrete || "",
    mensagem_confirmacao: config.mensagem_confirmacao || "",
    mensagem_cancelamento: config.mensagem_cancelamento || "",
    template_lembrete: config.template_lembrete || { nome: "", idioma: "pt_BR", variaveis: [] },
  }));
  const [salvando, setSalvando] = useState(false);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const salvar = async () => {
    setSalvando(true);
    try {
      await api.put("/agenda/config", {
        // `fuso` não é enviado: não há campo na tela, e omitir preserva o que
        // estiver gravado (Brasília, por padrão) em vez de sobrescrevê-lo com
        // o que quer que o formulário tenha carregado.
        passo_min: Number(form.passo_min),
        intervalo_min: Number(form.intervalo_min) || 0,
        antecedencia_min_horas: Number(form.antecedencia_min_horas) || 0,
        // Preso na tela também: o campo é livre e um 9999 digitado sem querer
        // voltaria do backend como um 422 do pydantic em inglês.
        antecedencia_max_dias: Math.min(365, Math.max(1, Number(form.antecedencia_max_dias) || 60)),
        cancelamento_min_horas: Number(form.cancelamento_min_horas) || 0,
        lembrete_ativo: !!form.lembrete_ativo,
        lembrete_horas: Number(form.lembrete_horas) || 24,
        bloqueios: (form.bloqueios || []).filter((b) => b.data),
        // String vazia volta ao texto padrão: `ConfigIn` descarta `None`, e é
        // por isso que o campo em branco é enviado como "" e não omitido.
        mensagem_lembrete: form.mensagem_lembrete || "",
        mensagem_confirmacao: form.mensagem_confirmacao || "",
        mensagem_cancelamento: form.mensagem_cancelamento || "",
        template_lembrete: {
          nome: (form.template_lembrete?.nome || "").trim(),
          idioma: form.template_lembrete?.idioma || "pt_BR",
          variaveis: (form.template_lembrete?.variaveis || []).filter((v) => v !== null),
        },
      });
      toast.success("Configuração salva");
      onSalvo();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl" data-testid="config-agenda">
      <Bloco titulo="Como os horários são oferecidos">
        {/* `items-start` + rótulo de altura fixa: os quatro campos ficam com o
            input na mesma linha mesmo quando um rótulo quebra em duas. Sem
            isso, "Antecedência mínima" empurrava o próprio campo para baixo e
            a fileira saía escadinha.

            As duas durações são campos `00:00`: o formato já diz a unidade, e
            some com as setinhas do `input[type=number]`, que ficavam por cima
            do que estivesse à direita. "Agenda aberta por" conta dias, não
            duração, então continua número, com a unidade como sufixo. */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-3 gap-y-5 items-start">
          <Campo label="Intervalo entre horários" alinhado
            nota="De 30 em 30 é o mais comum; 15 atende quem trabalha com encaixe.">
            <select className="zz-input" value={form.passo_min} data-testid="config-passo"
              onChange={(e) => set({ passo_min: e.target.value })}>
              {PASSOS.map((p) => <option key={p} value={p}>{p} minutos</option>)}
            </select>
          </Campo>
          <Campo label="Folga entre atendimentos" alinhado
            nota="Horas:minutos, no máximo 04:00. Limpeza, troca de sala, deslocamento: vale para os dois lados de cada horário.">
            <CampoDuracao minutos={form.intervalo_min} max={240}
              testid="config-intervalo"
              onChange={(m) => set({ intervalo_min: m })} />
          </Campo>
          <Campo label="Antecedência mínima" alinhado
            nota="Horas:minutos. Impede que alguém marque para daqui a dez minutos e não chegue a tempo.">
            <CampoDuracao minutos={Math.round(Number(form.antecedencia_min_horas || 0) * 60)}
              testid="config-antecedencia"
              onChange={(m) => set({ antecedencia_min_horas: emHoras(m) })} />
          </Campo>
          <Campo label="Agenda aberta por" alinhado sufixo="dias"
            nota="Até onde o contato consegue marcar. Longe demais enche a agenda de fantasmas.">
            <input type="number" min="1" max="365" className="zz-input font-mono pr-14"
              value={form.antecedencia_max_dias}
              onChange={(e) => set({ antecedencia_max_dias: e.target.value })} />
          </Campo>
        </div>
      </Bloco>

      <Bloco titulo="Lembrete automático"
        nota="Falta em horário marcado é o prejuízo de quem vive de agenda. O contato responde CONFIRMAR ou CANCELAR na própria conversa, e a agenda se ajusta sozinha.">
        <label className="flex items-center gap-2 text-sm cursor-pointer mb-3">
          <input type="checkbox" checked={!!form.lembrete_ativo} data-testid="config-lembrete-ativo"
            onChange={(e) => set({ lembrete_ativo: e.target.checked })} />
          <span>Mandar lembrete pelo WhatsApp antes do horário</span>
        </label>
        {form.lembrete_ativo && (
          <>
            <Campo label="Quanto tempo antes"
              nota="Horas:minutos, de 01:00 a 99:59. 24:00 é o mais comum, um dia antes.">
              <CampoDuracao minutos={Math.round(Number(form.lembrete_horas || 0) * 60)}
                min={60} testid="config-lembrete-horas"
                onChange={(m) => set({ lembrete_horas: emHoras(m) })} />
            </Campo>

            {/* O lembrete sai um dia antes, quando quase sempre já se passaram
                24h desde a última mensagem do contato. Nessa situação o
                WhatsApp só entrega modelo aprovado: sem um configurado aqui, o
                aviso simplesmente não sai, e o motivo fica no histórico da
                conversa. Com a janela aberta (o contato acabou de escrever), o
                texto livre acima continua sendo o que vale. */}
            <Campo label="Modelo aprovado do lembrete"
              nota="Nome exato do modelo na sua conta da Meta. Fora da janela de 24h, é ele que o WhatsApp entrega; sem modelo, o lembrete não sai.">
              <input className="zz-input" data-testid="config-template-lembrete"
                placeholder="ex: lembrete_agendamento"
                value={form.template_lembrete?.nome || ""}
                onChange={(e) => set({
                  template_lembrete: { ...form.template_lembrete, nome: e.target.value },
                })} />
            </Campo>
            <Campo label="Variáveis do modelo, na ordem"
              nota="Uma por linha, na ordem de {{1}}, {{2}}... Aceita {contato}, {servico}, {profissional}, {data}, {hora} e {data_completa}.">
              <textarea rows={3} className="zz-input font-mono text-xs"
                data-testid="config-template-variaveis"
                placeholder={"{contato}\n{servico}\n{data_completa}"}
                value={(form.template_lembrete?.variaveis || []).join("\n")}
                onChange={(e) => set({
                  template_lembrete: {
                    ...form.template_lembrete,
                    variaveis: e.target.value.split("\n"),
                  },
                })} />
            </Campo>
          </>
        )}
      </Bloco>

      <Bloco titulo="Feriados e fechamentos"
        nota="Fecham a agenda de toda a equipe naquele dia: ganham até das exceções de cada profissional. Férias de uma pessoa só ficam na ficha dela, em Profissionais.">
        <div className="space-y-2">
          {(form.bloqueios || []).map((b, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <input type="date" className="zz-input font-mono max-w-[170px]" value={b.data || ""}
                onChange={(e) => set({
                  bloqueios: form.bloqueios.map((x, k) =>
                    (k === i ? { ...x, data: e.target.value } : x)),
                })} />
              <input className="zz-input flex-1 min-w-[160px]" placeholder="Motivo (opcional)"
                value={b.motivo || ""}
                onChange={(e) => set({
                  bloqueios: form.bloqueios.map((x, k) =>
                    (k === i ? { ...x, motivo: e.target.value } : x)),
                })} />
              <button className="zz-btn-icon"
                onClick={() => set({ bloqueios: form.bloqueios.filter((_, k) => k !== i) })}>
                <Trash size={14} weight="bold" />
              </button>
            </div>
          ))}
          <button className="zz-btn zz-btn-secondary text-xs" data-testid="add-bloqueio"
            onClick={() => set({ bloqueios: [...(form.bloqueios || []), { data: "", motivo: "" }] })}>
            <Plus size={12} weight="bold" /> Adicionar data
          </button>
        </div>
      </Bloco>

      <Bloco titulo="Textos das mensagens"
        nota="Em branco, vale o texto padrão mostrado como sugestão. Use {contato}, {servico}, {profissional}, {data}, {hora} e {data_completa}.">
        <div className="space-y-4">
          {[
            ["mensagem_confirmacao", "Confirmação, na hora de marcar"],
            ["mensagem_lembrete", "Lembrete, antes do horário"],
            ["mensagem_cancelamento", "Aviso de cancelamento"],
          ].map(([campo, rotulo]) => (
            <Campo key={campo} label={rotulo}>
              <textarea rows={4} className="zz-input" value={form[campo] || ""}
                data-testid={`config-${campo}`}
                placeholder={config.mensagens_padrao?.[campo.replace("mensagem_", "")] || ""}
                onChange={(e) => set({ [campo]: e.target.value })} />
            </Campo>
          ))}
        </div>
      </Bloco>

      <div className="flex justify-end">
        <button className="zz-btn" onClick={salvar} disabled={salvando}
          data-testid="salvar-config-agenda">
          <FloppyDisk size={14} weight="bold" /> {salvando ? "Salvando…" : "Salvar configuração"}
        </button>
      </div>
    </div>
  );
}

function Bloco({ titulo, nota, children }) {
  return (
    <section className="border border-line rounded-xl p-5 bg-surface">
      <h3 className="font-heading text-lg font-black tracking-tight">{titulo}</h3>
      {nota && <p className="text-xs text-ink-2 mt-1 mb-4">{nota}</p>}
      {!nota && <div className="mb-4" />}
      {children}
    </section>
  );
}

function Campo({ label, nota, sufixo, alinhado, children }) {
  return (
    <div>
      {/* Com `alinhado`, o rótulo ocupa sempre a altura de duas linhas e o
          texto encosta embaixo. É o que mantém os campos de uma fileira com o
          input na mesma altura, independente de o rótulo caber em uma linha ou
          duas, e não depende de ninguém lembrar de manter os rótulos curtos. */}
      <label className={`text-xs font-bold uppercase tracking-wider text-ink-2 mb-1.5 ${
        alinhado ? "flex items-end min-h-[2.25rem]" : "block"}`}>
        {label}
      </label>
      {sufixo ? (
        <div className="relative">
          {children}
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-ink-3 pointer-events-none">
            {sufixo}
          </span>
        </div>
      ) : children}
      {nota && <p className="text-[11px] text-ink-3 mt-1">{nota}</p>}
    </div>
  );
}
