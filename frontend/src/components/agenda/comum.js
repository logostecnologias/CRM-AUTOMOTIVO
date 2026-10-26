import { t } from "@/lib/textos";
// Formatação de data e hora da agenda.
//
// **Tudo aqui é exibido no fuso da EMPRESA, não no do navegador**: e isso é o
// oposto do que Atividades e Relatórios fazem. Naquelas telas "hoje" é o dia de
// quem está olhando; aqui "segunda das 9h às 18h" é o horário de funcionamento
// da empresa, e o mesmo horário precisa aparecer igual para a recepção, para o
// dono viajando e para o bot, que roda no servidor. Por isso todas as funções
// recebem `fuso` (vem de `GET /agenda/config`) e passam por `timeZone` no
// `Intl`: nunca por `new Date().getHours()`, que usaria o relógio da máquina.

const SEMANA = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];
export const DIAS_GRADE = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];

function fmt(fuso, opcoes) {
  return new Intl.DateTimeFormat("pt-BR", { timeZone: fuso, ...opcoes });
}

export function hora(iso, fuso) {
  if (!iso) return "";
  return fmt(fuso, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function dataCurta(iso, fuso) {
  if (!iso) return "";
  return fmt(fuso, { day: "2-digit", month: "2-digit" }).format(new Date(iso));
}

export function dataCompleta(iso, fuso) {
  if (!iso) return "";
  const d = new Date(iso);
  const partes = fmt(fuso, {
    weekday: "long", day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  }).formatToParts(d);
  const p = Object.fromEntries(partes.map((x) => [x.type, x.value]));
  const diaSemana = (p.weekday || "").replace(/^./, (c) => c.toUpperCase()).replace("-feira", "");
  return `${diaSemana}, ${p.day}/${p.month} às ${p.hour}:${p.minute}`;
}

/** O dia (AAAA-MM-DD) em que este instante cai, no fuso da empresa.
 *
 * `toISOString().slice(0,10)` daria o dia em UTC: um atendimento das 22h em
 * São Paulo apareceria no dia seguinte. */
export function diaDe(iso, fuso) {
  const p = Object.fromEntries(
    fmt(fuso, { year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(new Date(iso))
      .map((x) => [x.type, x.value]),
  );
  return `${p.year}-${p.month}-${p.day}`;
}

/** Hoje, no fuso da empresa. */
export function hojeNaEmpresa(fuso) {
  return diaDe(new Date().toISOString(), fuso);
}

export function somaDias(dia, n) {
  // Meio-dia UTC para a soma nunca tropeçar numa virada de horário de verão:
  // o dia do calendário é o que importa aqui, não o instante.
  const d = new Date(`${dia}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function rotuloDia(dia) {
  const d = new Date(`${dia}T12:00:00Z`);
  return `${SEMANA[d.getUTCDay()]} ${String(d.getUTCDate()).padStart(2, "0")}/${
    String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** Quanto aquele fuso está deslocado do UTC **naquele instante** (em ms). */
function deslocamento(instante, fuso) {
  const p = Object.fromEntries(
    fmt(fuso, {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).formatToParts(instante).map((x) => [x.type, x.value]),
  );
  const comoSeFosseUtc = Date.UTC(
    Number(p.year), Number(p.month) - 1, Number(p.day),
    Number(p.hour) % 24, Number(p.minute), Number(p.second),
  );
  return comoSeFosseUtc - instante.getTime();
}

/** O instante ISO do começo (ou fim) de um dia do calendário, no fuso da empresa.
 *
 * É o que a listagem manda em `de`/`ate`. O deslocamento é medido naquela data
 * específica: um número fixo de horas erraria em todo fuso com horário de
 * verão, e o fuso do navegador erraria sempre que quem abriu a tela não
 * estivesse no mesmo lugar que a empresa.
 *
 * A segunda passada existe porque o deslocamento é medido num instante que
 * ainda é um chute: no dia exato da virada do horário de verão, o chute e o
 * resultado caem em lados diferentes da mudança, e uma passada só erraria a
 * janela em uma hora. */
export function instanteDoDia(dia, fuso, fimDoDia = false) {
  const chute = new Date(`${dia}T${fimDoDia ? "23:59:59" : "00:00:00"}Z`);
  const primeira = new Date(chute.getTime() - deslocamento(chute, fuso));
  return new Date(chute.getTime() - deslocamento(primeira, fuso)).toISOString();
}

export const STATUS = {
  agendado: { label: "Agendado", classe: "bg-info-soft text-info border-info" },
  confirmado: { label: "Confirmado", classe: "bg-success-soft text-success border-success" },
  concluido: { label: "Atendido", classe: "bg-surface-3 text-ink-2 border-line" },
  cancelado: { label: "Cancelado", classe: "bg-surface-2 text-ink-3 border-line" },
  faltou: { label: "Faltou", classe: "bg-danger-soft text-danger border-danger" },
};

// Função, não constante: o texto depende da marca, que só se sabe na renderização.
export function rotuloOrigem(origem) {
  const r = {
    manual: "Marcado na recepção",
    bot: `Marcado pelo ${t("robô")} no WhatsApp`,
    ia: `Marcado pelo ${t("agente de IA")}`,
  };
  return r[origem] || origem;
}

export function moeda(valor) {
  if (valor == null || valor === "") return "";
  return Number(valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
