import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { formatBRL } from "@/lib/currency";
import { MARCAS, valida as validaMarca } from "@/lib/marca";
import { haQuanto, plural } from "@/components/painel/Indicadores";
import NovaEmpresa from "@/components/superadmin/NovaEmpresa";
import EmpresaDetalhe from "@/components/superadmin/EmpresaDetalhe";
import {
  BarraIA, EmDia, PontoSaude, SeloMarca, SeloProblema, nivelDaEmpresa, numero, useEntrar,
} from "@/components/superadmin/comum";
import {
  ArrowDown, ArrowUp, CaretRight, DownloadSimple, MagnifyingGlass, Plus, SignIn, WhatsappLogo,
} from "@phosphor-icons/react";

/**
 * Lista de empresas.
 *
 * Cada linha responde o que o suporte pergunta sem precisar entrar na
 * empresa: está saudável? quem administra? o WhatsApp está no ar? quanto usou
 * na semana, quantos leads entraram, vendeu? a equipe ainda entra no sistema?
 * quanto da IA paga pela plataforma já foi? Tudo de uma agregação só
 * (`plataforma.saude`). Mudar marca, teto de IA, suspender, trocar senha e
 * excluir ficam na ficha (`EmpresaDetalhe`), que abre no clique da linha.
 */

const FILTROS = [
  { id: "todas", rotulo: "Todas" },
  { id: "atencao", rotulo: "Precisam de atenção" },
  { id: "graves", rotulo: "Graves" },
  { id: "em_dia", rotulo: "Em dia" },
  { id: "suspensas", rotulo: "Suspensas" },
];

const ORDENS = [
  { id: "recentes", rotulo: "Mais recentes" },
  { id: "saude", rotulo: "Pior saúde primeiro" },
  { id: "movimento", rotulo: "Mais mensagens" },
  { id: "leads", rotulo: "Mais leads" },
  { id: "vendas", rotulo: "Mais vendas" },
  { id: "ia", rotulo: "Mais IA" },
  { id: "acesso", rotulo: "Sem acesso há mais tempo" },
  { id: "nome", rotulo: "Nome (A–Z)" },
];

const PESO_SAUDE = { alto: 0, medio: 1, ok: 2, suspensa: 3 };

function filtrar(t, filtro) {
  const n = nivelDaEmpresa(t);
  switch (filtro) {
    case "atencao": return n === "alto" || n === "medio";
    case "graves": return n === "alto";
    case "em_dia": return n === "ok";
    case "ativas": return t.status === "active";
    case "suspensas": return n === "suspensa";
    default: return true;
  }
}

function comparar(ordem) {
  const s = (t) => t.saude || {};
  switch (ordem) {
    case "saude": return (a, b) => PESO_SAUDE[nivelDaEmpresa(a)] - PESO_SAUDE[nivelDaEmpresa(b)];
    case "movimento": return (a, b) => (s(b).mensagens_7d || 0) - (s(a).mensagens_7d || 0);
    case "leads": return (a, b) => (s(b).leads_7d || 0) - (s(a).leads_7d || 0);
    case "vendas": return (a, b) => (s(b).vendas_30d || 0) - (s(a).vendas_30d || 0);
    case "ia": return (a, b) => (s(b).ia?.tokens_plataforma || 0) - (s(a).ia?.tokens_plataforma || 0);
    // Quem nunca entrou vai para o topo: é o caso mais grave de "não usa".
    case "acesso": return (a, b) => (s(a).ultimo_acesso || "").localeCompare(s(b).ultimo_acesso || "");
    case "nome": return (a, b) => a.name.localeCompare(b.name, "pt-BR");
    default: return (a, b) => (b.created_at || "").localeCompare(a.created_at || "");
  }
}

function normaliza(s) {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function Tendencia({ atual, anterior }) {
  const diff = atual - anterior;
  if (!anterior || diff === 0) return null;
  return (
    <span className={`inline-flex items-center text-[11px] ${diff > 0 ? "text-success" : "text-danger"}`}
      title={`${numero(anterior)} na semana anterior`}>
      {diff > 0 ? <ArrowUp size={10} weight="bold" /> : <ArrowDown size={10} weight="bold" />}
      {Math.round((Math.abs(diff) / anterior) * 100)}%
    </span>
  );
}

function Conexoes({ c }) {
  if (!c) return null;
  if (c.total === 0) return <span className="text-xs text-ink-3">nenhuma</span>;
  const todas = c.no_ar === c.total;
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm ${todas ? "text-success" : "text-danger"}`}>
      <WhatsappLogo size={15} weight={todas ? "fill" : "regular"} />
      {c.total === 1 ? (todas ? "no ar" : "fora do ar") : `${c.no_ar} de ${c.total} no ar`}
    </span>
  );
}

// Planilha da lista como está filtrada: é o que se cola numa conversa com o
// sócio ou num relatório mensal, sem precisar copiar linha a linha.
function exportarCSV(linhas) {
  const cab = ["Empresa", "Marca", "Situação", "Admin", "WhatsApp no ar", "Mensagens 7d", "Leads 7d",
    "Vendas 30d", "Valor vendas 30d", "Usuários", "Último acesso", "Tokens IA plataforma (mês)",
    "Limite IA", "Custo IA USD", "Problemas", "Criada em"];
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const corpo = linhas.map((t) => {
    const s = t.saude || {};
    return [
      t.name, MARCAS[validaMarca(t.marca)].nome, t.status === "active" ? "ativa" : "suspensa",
      s.admins?.[0]?.email, `${s.conexoes?.no_ar || 0}/${s.conexoes?.total || 0}`,
      s.mensagens_7d, s.leads_7d, s.vendas_30d, s.vendas_30d_valor, s.usuarios,
      s.ultimo_acesso ? new Date(s.ultimo_acesso).toLocaleString("pt-BR") : "",
      s.ia?.tokens_plataforma, s.ia?.teto ?? "", s.ia?.custo_usd,
      (s.problemas || []).map((p) => p.tipo).join(", "),
      t.created_at ? new Date(t.created_at).toLocaleDateString("pt-BR") : "",
    ].map(esc).join(";");
  });
  // BOM para o Excel abrir os acentos certos; `;` porque o Excel em pt-BR usa
  // vírgula como separador decimal.
  const blob = new Blob(["﻿" + [cab.join(";"), ...corpo].join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `empresas-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function TenantsPage() {
  const [tenants, setTenants] = useState(null);
  const [erro, setErro] = useState(false);
  const [params, setParams] = useSearchParams();
  const [busca, setBusca] = useState("");
  const [marca, setMarca] = useState("");
  const [entrar, entrando] = useEntrar();

  // Filtro, ordem, empresa aberta e o modal de criação ficam na URL: a visão
  // geral leva direto a "graves", a uma ficha numa aba, ou a "nova empresa".
  const filtro = params.get("filtro") || "todas";
  const ordem = params.get("ordem") || "recentes";
  const aberta = params.get("empresa");
  const aba = params.get("aba") || "resumo";
  const nova = params.get("nova") === "1";
  const setParam = (mudancas) => {
    const p = new URLSearchParams(params);
    Object.entries(mudancas).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
  };

  const load = () => api.get("/admin/tenants")
    .then((r) => { setTenants(r.data); setErro(false); })
    .catch(() => setErro(true));
  useEffect(() => { load(); }, []);

  const lista = useMemo(() => tenants || [], [tenants]);
  const contagem = useMemo(() => Object.fromEntries(
    FILTROS.map((f) => [f.id, lista.filter((t) => filtrar(t, f.id)).length])), [lista]);

  const visiveis = useMemo(() => {
    const q = normaliza(busca.trim());
    return lista.filter((t) => {
      if (!filtrar(t, filtro)) return false;
      if (marca && validaMarca(t.marca) !== marca) return false;
      if (!q) return true;
      // Busca também pelo email de quem administra: "qual empresa é a do
      // joao@...?" é tão comum quanto procurar pelo nome.
      return normaliza(t.name).includes(q)
        || (t.saude?.admins || []).some((a) => normaliza(a.email).includes(q));
    }).sort(comparar(ordem));
  }, [lista, filtro, marca, busca, ordem]);

  const ativas = lista.filter((t) => t.status === "active").length;

  return (
    <div className="zz-page" data-testid="admin-tenants-page">
      <div className="flex items-end justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Empresas</h1>
          <p className="text-ink-2 mt-2 text-sm">
            {lista.length === 0
              ? "Cada empresa é um ambiente isolado, com o próprio admin, equipe e conexões."
              : `${plural(ativas, "empresa ativa", "empresas ativas")}` +
                (contagem.atencao ? `, ${contagem.atencao} precisando de atenção.` : ", todas em dia.")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => exportarCSV(visiveis)} disabled={!visiveis.length}
            className="zz-btn zz-btn-secondary shrink-0" data-testid="exportar-empresas"
            title="Baixar a lista como está filtrada">
            <DownloadSimple size={16} weight="bold" /> Exportar
          </button>
          <button data-testid="new-tenant-btn" onClick={() => setParam({ nova: "1" })} className="zz-btn shrink-0">
            <Plus size={16} weight="bold" /> Nova empresa
          </button>
        </div>
      </div>

      {nova && (
        <NovaEmpresa
          onFechar={() => setParam({ nova: null })}
          onCriada={load}
          onEntrar={(t, destino) => entrar(t, destino)}
        />
      )}

      {aberta && (
        <EmpresaDetalhe id={aberta} aba={aba}
          onAba={(a) => setParam({ aba: a === "resumo" ? null : a })}
          onFechar={() => setParam({ empresa: null, aba: null })}
          onMudou={load} entrar={entrar} entrando={entrando} />
      )}

      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <div className="flex gap-1 p-1 bg-surface-2 border border-line rounded-lg overflow-x-auto max-w-full">
          {FILTROS.map((f) => (
            <button key={f.id} onClick={() => setParam({ filtro: f.id === "todas" ? null : f.id })}
              data-testid={`filtro-${f.id}`}
              className={`text-xs px-2.5 py-1.5 rounded-md flex items-center gap-1.5 whitespace-nowrap ${filtro === f.id
                ? "bg-surface text-ink font-semibold shadow-sm border border-line"
                : "text-ink-2 hover:text-ink border border-transparent"}`}>
              {f.rotulo}
              <span className={`font-mono text-[11px] ${
                (f.id === "graves" || f.id === "atencao") && contagem[f.id] ? "text-danger" : "text-ink-3"}`}>
                {contagem[f.id]}
              </span>
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input className="zz-input h-9 pl-8 text-sm" placeholder="Buscar por nome ou email do admin"
            value={busca} onChange={(e) => setBusca(e.target.value)} data-testid="busca-empresa" />
        </div>
        {Object.keys(MARCAS).length > 1 && (
          <select className="zz-input h-9 text-sm w-auto" value={marca} onChange={(e) => setMarca(e.target.value)}
            data-testid="filtro-marca">
            <option value="">Todas as marcas</option>
            {Object.values(MARCAS).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
          </select>
        )}
        <select className="zz-input h-9 text-sm w-auto" value={ordem} data-testid="ordem-empresas"
          onChange={(e) => setParam({ ordem: e.target.value === "recentes" ? null : e.target.value })}>
          {ORDENS.map((o) => <option key={o.id} value={o.id}>{o.rotulo}</option>)}
        </select>
      </div>

      <div className="border border-line bg-surface rounded-xl overflow-x-auto">
        <table className="w-full text-left min-w-[1080px]">
          <thead>
            <tr className="text-[11px] text-ink-3 border-b border-line">
              <th className="font-medium px-4 py-2.5">Empresa</th>
              <th className="font-medium px-3 py-2.5">Saúde</th>
              <th className="font-medium px-3 py-2.5">WhatsApp</th>
              <th className="font-medium px-3 py-2.5">Mensagens · 7d</th>
              <th className="font-medium px-3 py-2.5">Leads · 7d</th>
              <th className="font-medium px-3 py-2.5">Vendas · 30d</th>
              <th className="font-medium px-3 py-2.5">Equipe</th>
              <th className="font-medium px-3 py-2.5">IA · mês</th>
              <th className="px-3 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {tenants === null && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-sm text-ink-3">
                {erro ? (
                  <span>Não foi possível carregar. <button onClick={load} className="underline hover:text-ink">Tentar de novo</button></span>
                ) : "Carregando…"}
              </td></tr>
            )}
            {tenants !== null && visiveis.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-sm text-ink-3">
                {lista.length === 0 ? "Nenhuma empresa cadastrada." : "Nenhuma empresa com esses filtros."}
              </td></tr>
            )}
            {visiveis.map((t) => {
              const s = t.saude || {};
              const nivel = nivelDaEmpresa(t);
              const admin = s.admins?.[0];
              return (
                <tr key={t.id} onClick={() => setParam({ empresa: t.id, aba: null })}
                  className={`border-b border-line last:border-b-0 hover:bg-surface-2 cursor-pointer align-middle ${nivel === "suspensa" ? "opacity-60" : ""}`}
                  data-testid={`tenant-row-${t.id}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <PontoSaude nivel={nivel} />
                      <span className="font-semibold text-sm">{t.name}</span>
                      {nivel === "suspensa" && (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-danger-soft border border-danger text-danger">
                          suspensa
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-ink-3 mt-0.5 flex items-center gap-2 flex-wrap pl-[18px]">
                      <SeloMarca marca={t.marca} />
                      <span className="font-mono truncate max-w-[220px]">{admin ? admin.email : "sem admin"}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3 max-w-[200px]">
                    {nivel === "suspensa" ? <span className="text-xs text-ink-3">—</span>
                      : s.problemas?.length ? (
                        <div className="flex flex-wrap gap-1">
                          {s.problemas.map((p) => <SeloProblema key={p.tipo} p={p} pequeno />)}
                        </div>
                      ) : <EmDia />}
                  </td>
                  <td className="px-3 py-3"><Conexoes c={s.conexoes} /></td>
                  <td className="px-3 py-3">
                    <div className="text-sm font-mono flex items-center gap-1.5">
                      {numero(s.mensagens_7d)} <Tendencia atual={s.mensagens_7d || 0} anterior={s.mensagens_7d_anterior || 0} />
                    </div>
                    <div className="text-[11px] text-ink-3">
                      {s.ultima_mensagem ? `última ${haQuanto(s.ultima_mensagem)}` : "nada em 30 dias"}
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="text-sm font-mono flex items-center gap-1.5">
                      {numero(s.leads_7d)} <Tendencia atual={s.leads_7d || 0} anterior={s.leads_7d_anterior || 0} />
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="text-sm font-mono">{numero(s.vendas_30d)}</div>
                    {s.vendas_30d_valor > 0 && (
                      <div className="text-[11px] text-ink-3 font-mono">{formatBRL(s.vendas_30d_valor)}</div>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <div className="text-sm">{plural(s.usuarios || 0, "pessoa", "pessoas")}</div>
                    <div className={`text-[11px] ${s.ultimo_acesso ? "text-ink-3" : "text-warning"}`}>
                      {s.ultimo_acesso ? `entrou ${haQuanto(s.ultimo_acesso)}` : "sem acesso registrado"}
                    </div>
                  </td>
                  <td className="px-3 py-3 w-36"><BarraIA ia={s.ia} /></td>
                  <td className="px-3 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={(e) => { e.stopPropagation(); entrar(t); }} disabled={entrando}
                        className="text-xs font-medium px-2.5 py-1.5 rounded-md border border-line hover:border-line-strong hover:bg-surface flex items-center gap-1.5 whitespace-nowrap"
                        title="Entrar na empresa (modo suporte)" data-testid={`impersonate-${t.id}`}>
                        <SignIn size={13} weight="bold" /> Entrar
                      </button>
                      <CaretRight size={14} className="text-ink-3" />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {visiveis.length > 0 && (
        <p className="text-[11px] text-ink-3 mt-2 px-1">
          Último acesso conta a partir de 18/11/2026, quando o sistema começou a registrá-lo.
          Clique numa linha para abrir a ficha completa.
        </p>
      )}
    </div>
  );
}
