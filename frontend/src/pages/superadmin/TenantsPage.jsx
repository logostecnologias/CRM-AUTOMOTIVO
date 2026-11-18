import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { formatBRL } from "@/lib/currency";
import { MARCAS, valida as validaMarca } from "@/lib/marca";
import { haQuanto, plural } from "@/components/painel/Indicadores";
import NovaEmpresa from "@/components/superadmin/NovaEmpresa";
import EmpresaDetalhe from "@/components/superadmin/EmpresaDetalhe";
import { SeloMarca, rotuloDoProblema, useEntrar } from "@/components/superadmin/comum";
import {
  ArrowDown, ArrowUp, CaretRight, MagnifyingGlass, Plus, SignIn, WhatsappLogo,
} from "@phosphor-icons/react";

/**
 * Lista de empresas.
 *
 * Era nome, plano, marca, status, robôs e data, com três selects e três
 * ícones por linha: dava para mudar tudo e não dava para saber nada. Agora cada
 * linha diz quem administra (o email que o suporte vive procurando), se o
 * WhatsApp está no ar, quanto a empresa usou na semana e o que precisa de
 * atenção. Mudar plano, marca, suspender e excluir foi para a ficha da empresa
 * (`EmpresaDetalhe`), que abre no clique da linha.
 */

const FILTROS = [
  { id: "todas", rotulo: "Todas" },
  { id: "atencao", rotulo: "Precisam de atenção" },
  { id: "ativas", rotulo: "Ativas" },
  { id: "suspensas", rotulo: "Suspensas" },
];

// Problema de nível baixo (sem plano, acima do plano) não põe a empresa em
// "precisam de atenção": é assunto comercial, não cliente sem atendimento.
function precisaAtencao(t) {
  return (t.saude?.problemas || []).some((p) => p.nivel !== "baixo");
}

function normaliza(s) {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function Movimento({ s }) {
  if (!s) return null;
  const atual = s.mensagens_7d;
  const ant = s.mensagens_7d_anterior;
  const diff = atual - ant;
  return (
    <div>
      <div className="text-sm font-mono flex items-center gap-1.5">
        {atual.toLocaleString("pt-BR")}
        {ant > 0 && diff !== 0 && (
          <span className={`inline-flex items-center text-[11px] ${diff > 0 ? "text-success" : "text-danger"}`}
            title={`${ant.toLocaleString("pt-BR")} na semana anterior`}>
            {diff > 0 ? <ArrowUp size={10} weight="bold" /> : <ArrowDown size={10} weight="bold" />}
            {Math.round((Math.abs(diff) / ant) * 100)}%
          </span>
        )}
      </div>
      <div className="text-[11px] text-ink-3">
        {s.ultima_mensagem ? `última ${haQuanto(s.ultima_mensagem)}` : "nada em 30 dias"}
      </div>
    </div>
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

function Problemas({ lista }) {
  if (!lista?.length) return <span className="text-xs text-ink-3">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {lista.map((p) => (
        <span key={p.tipo}
          className={`text-[11px] px-1.5 py-0.5 rounded-full border whitespace-nowrap ${p.nivel === "alto"
            ? "bg-danger-soft border-danger text-danger"
            : p.nivel === "medio" ? "bg-warning-soft border-warning text-warning" : "bg-surface-2 border-line text-ink-2"}`}>
          {rotuloDoProblema(p)}
        </span>
      ))}
    </div>
  );
}

export default function TenantsPage() {
  const [tenants, setTenants] = useState(null);
  const [plans, setPlans] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [params, setParams] = useSearchParams();
  const [busca, setBusca] = useState("");
  const [marca, setMarca] = useState("");
  const [entrar, entrando] = useEntrar();

  // Filtro e empresa aberta ficam na URL: o alerta da visão geral leva direto
  // a "precisam de atenção" ou à ficha de uma empresa.
  const filtro = params.get("filtro") || "todas";
  const aberta = params.get("empresa");
  const setParam = (chave, valor) => {
    const p = new URLSearchParams(params);
    if (valor) p.set(chave, valor); else p.delete(chave);
    setParams(p, { replace: true });
  };

  const load = () => api.get("/admin/tenants").then((r) => setTenants(r.data));
  useEffect(() => {
    load();
    api.get("/admin/plans").then((r) => setPlans(r.data));
  }, []);

  const lista = useMemo(() => tenants || [], [tenants]);
  const contagem = useMemo(() => ({
    todas: lista.length,
    atencao: lista.filter((t) => t.status === "active" && precisaAtencao(t)).length,
    ativas: lista.filter((t) => t.status === "active").length,
    suspensas: lista.filter((t) => t.status !== "active").length,
  }), [lista]);

  const visiveis = useMemo(() => {
    const q = normaliza(busca.trim());
    return lista.filter((t) => {
      if (filtro === "atencao" && !(t.status === "active" && precisaAtencao(t))) return false;
      if (filtro === "ativas" && t.status !== "active") return false;
      if (filtro === "suspensas" && t.status === "active") return false;
      if (marca && validaMarca(t.marca) !== marca) return false;
      if (!q) return true;
      // Busca também pelo email de quem administra: "qual empresa é a do
      // joao@...?" é tão comum quanto procurar pelo nome.
      return normaliza(t.name).includes(q)
        || (t.saude?.admins || []).some((a) => normaliza(a.email).includes(q));
    });
  }, [lista, filtro, marca, busca]);

  return (
    <div className="zz-page" data-testid="admin-tenants-page">
      <div className="flex items-end justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h1 className="font-heading text-4xl font-black tracking-tighter">Empresas</h1>
          <p className="text-ink-2 mt-2 text-sm">
            {lista.length === 0
              ? "Cada empresa é um ambiente isolado, com o próprio admin, plano e conexões."
              : `${plural(contagem.ativas, "empresa ativa", "empresas ativas")}` +
                (contagem.atencao ? `, ${contagem.atencao} precisando de atenção.` : ", todas em dia.")}
          </p>
        </div>
        <button data-testid="new-tenant-btn" onClick={() => setShowForm(true)} className="zz-btn shrink-0">
          <Plus size={16} weight="bold" /> Nova empresa
        </button>
      </div>

      {showForm && (
        <NovaEmpresa
          plans={plans}
          onFechar={() => setShowForm(false)}
          onCriada={load}
          onEntrar={(t, destino) => entrar(t, destino)}
        />
      )}

      {aberta && (
        <EmpresaDetalhe id={aberta} plans={plans} onFechar={() => setParam("empresa", null)}
          onMudou={load} entrar={entrar} entrando={entrando} />
      )}

      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <div className="flex gap-1 p-1 bg-surface-2 border border-line rounded-lg">
          {FILTROS.map((f) => (
            <button key={f.id} onClick={() => setParam("filtro", f.id === "todas" ? null : f.id)}
              data-testid={`filtro-${f.id}`}
              className={`text-xs px-2.5 py-1.5 rounded-md flex items-center gap-1.5 ${filtro === f.id
                ? "bg-surface text-ink font-semibold shadow-sm border border-line"
                : "text-ink-2 hover:text-ink border border-transparent"}`}>
              {f.rotulo}
              <span className={`font-mono text-[11px] ${f.id === "atencao" && contagem.atencao ? "text-danger" : "text-ink-3"}`}>
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
      </div>

      <div className="border border-line bg-surface rounded-xl overflow-x-auto">
        <table className="w-full text-left min-w-[900px]">
          <thead>
            <tr className="text-[11px] text-ink-3 border-b border-line">
              <th className="font-medium px-4 py-2.5">Empresa</th>
              <th className="font-medium px-3 py-2.5">Plano</th>
              <th className="font-medium px-3 py-2.5">WhatsApp</th>
              <th className="font-medium px-3 py-2.5">Mensagens · 7 dias</th>
              <th className="font-medium px-3 py-2.5">Atenção</th>
              <th className="px-3 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {tenants === null && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-ink-3">Carregando…</td></tr>
            )}
            {tenants !== null && visiveis.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-ink-3">
                {lista.length === 0 ? "Nenhuma empresa cadastrada." : "Nenhuma empresa com esses filtros."}
              </td></tr>
            )}
            {visiveis.map((t) => {
              const ativa = t.status === "active";
              const admin = t.saude?.admins?.[0];
              return (
                <tr key={t.id} onClick={() => setParam("empresa", t.id)}
                  className={`border-b border-line last:border-b-0 hover:bg-surface-2 cursor-pointer align-middle ${ativa ? "" : "opacity-60"}`}
                  data-testid={`tenant-row-${t.id}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{t.name}</span>
                      {!ativa && (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-danger-soft border border-danger text-danger">
                          suspensa
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-ink-3 mt-0.5 flex items-center gap-2 flex-wrap">
                      <SeloMarca marca={t.marca} />
                      <span className="font-mono truncate max-w-[260px]">{admin ? admin.email : "sem admin"}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    {t.plan ? (
                      <>
                        <div className="text-sm">{t.plan.nome}</div>
                        <div className="text-[11px] text-ink-3 font-mono">{formatBRL(t.plan.preco_mensal)}/mês</div>
                      </>
                    ) : <span className="text-xs text-ink-3">sem plano</span>}
                  </td>
                  <td className="px-3 py-3"><Conexoes c={t.saude?.conexoes} /></td>
                  <td className="px-3 py-3"><Movimento s={t.saude} /></td>
                  <td className="px-3 py-3 max-w-[240px]"><Problemas lista={t.saude?.problemas} /></td>
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
    </div>
  );
}
