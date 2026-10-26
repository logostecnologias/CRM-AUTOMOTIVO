import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp } from "@phosphor-icons/react";

// Peças de número dos dois painéis, o da empresa e o do super admin. Saíram de
// `TenantDashboard` quando o segundo painel nasceu: a regra da variação (seta
// + palavra, nunca só cor, leitura invertida quando cair é bom) tem de ser a
// mesma nos dois.

export function plural(n, um, varios) {
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? um : varios}`;
}

export function haQuanto(iso) {
  if (!iso) return null;
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 1) return "agora há pouco";
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  return `há ${plural(Math.floor(h / 24), "dia", "dias")}`;
}

/**
 * A variação contra a semana anterior. `menorMelhor` inverte a leitura (espera
 * na fila que cai é boa notícia). Seta + palavra, para não depender só da cor.
 */
export function Variacao({ atual, anterior, menorMelhor = false, formato }) {
  if (atual == null || anterior == null) {
    return <span className="text-ink-3">sem semana anterior para comparar</span>;
  }
  if (anterior === 0 && atual === 0) return <span className="text-ink-3">igual à semana anterior</span>;
  const diff = atual - anterior;
  if (diff === 0) return <span className="text-ink-3">igual à semana anterior</span>;
  const subiu = diff > 0;
  const bom = menorMelhor ? !subiu : subiu;
  const Seta = subiu ? ArrowUp : ArrowDown;
  const quanto = formato
    ? formato(Math.abs(diff))
    : anterior > 0
      ? `${Math.round((Math.abs(diff) / anterior) * 100)}%`
      : plural(Math.abs(diff), "", "").trim();
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`inline-flex items-center gap-0.5 font-semibold ${bom ? "text-success" : "text-danger"}`}>
        <Seta size={11} weight="bold" />
        {quanto}
      </span>
      <span className="text-ink-3">{subiu ? "a mais" : "a menos"} que a semana anterior</span>
    </span>
  );
}

export function Indicador({ rotulo, valor, rodape, para, testid }) {
  const corpo = (
    <>
      <div className="text-xs text-ink-3">{rotulo}</div>
      <div className="font-heading text-3xl font-black tracking-tight mt-1 truncate">{valor}</div>
      <div className="text-xs mt-1.5 min-h-[1rem]">{rodape}</div>
    </>
  );
  const classe = "block border border-line bg-surface rounded-xl p-4";
  return para ? (
    <Link to={para} className={`${classe} hover:border-line-strong`} data-testid={testid}>{corpo}</Link>
  ) : (
    <div className={classe} data-testid={testid}>{corpo}</div>
  );
}
