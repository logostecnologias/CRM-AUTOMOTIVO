import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { MagnifyingGlass, Plus, SquaresFour, Rows } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import FormVeiculo from "@/components/estoque/FormVeiculo";
import FichaVeiculo from "@/components/estoque/FichaVeiculo";
import { FotoCarro, Placa, SeloVeiculo, SilhuetaCarro } from "@/components/estoque/Visual";
import {
  OPCOES_PADRAO, deApi, diasNoPatio, formatAno, formatKm, formatPreco, nomeVeiculo, rotulo, temPromocao,
} from "@/components/estoque/estoque";

// Lembrar a vista (grade ou lista) é conveniência do aparelho, não dado.
const CHAVE_VISTA = "auto:estoque:vista";
const vistaGuardada = () => { try { return localStorage.getItem(CHAVE_VISTA) || "grade"; } catch { return "grade"; } };

const SITUACOES = [
  ["estoque", "No pátio"],
  ["reservado", "Reservados"],
  ["vendido", "Vendidos"],
  ["", "Todos"],
];

const ORDENS = [
  ["recentes", "Mais recentes"],
  ["preco_menor", "Menor preço"],
  ["preco_maior", "Maior preço"],
  ["km_menor", "Menor km"],
  ["ano_maior", "Mais novos"],
  ["mais_parados", "Mais tempo parados"],
];

function Numero({ rotulo: r, valor, unidade, detalhe, tom }) {
  return (
    <div className="zz-kpi">
      <div className="zz-sobre">{r}</div>
      <div className="flex items-baseline gap-1.5 mt-2">
        <span className="font-heading text-[1.9rem] font-medium tracking-tight num leading-none">{valor}</span>
        {unidade && <span className="text-sm text-ink-3">{unidade}</span>}
      </div>
      {detalhe && <div className={`text-xs mt-2 ${tom === "alerta" ? "text-warning" : "text-ink-3"}`}>{detalhe}</div>}
    </div>
  );
}

const reaisCurto = (n) => {
  if (!n) return ["R$ 0", ""];
  if (n >= 1_000_000) return [`R$ ${(n / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}`, "mi"];
  if (n >= 1_000) return [`R$ ${Math.round(n / 1_000).toLocaleString("pt-BR")}`, "mil"];
  return [formatPreco(n), ""];
};

function Cartao({ v, opcoes, onAbrir }) {
  const dados = [formatAno(v), formatKm(v.km), rotulo(opcoes, "cambio", v.cambio)].filter(Boolean);
  return (
    <button type="button" onClick={() => onAbrir(v)} className={`zz-carro-cartao text-left ${v.status === "vendido" ? "vendido" : ""}`}
      data-testid={`veiculo-${v.id}`}>
      <div className="relative">
        <FotoCarro id={v.fotos?.[0]} alt={nomeVeiculo(v)} className="aspect-[4/3] zz-foto-zoom" />
        <div className="absolute top-3 left-3"><SeloVeiculo v={v} /></div>
        {v.fotos?.length > 1 && <span className="absolute bottom-2.5 right-3 zz-selo-carro num">{v.fotos.length} fotos</span>}
      </div>
      <div className="p-4 sm:p-5 flex flex-col flex-1">
        <div className="font-heading text-[1.05rem] font-semibold tracking-tight truncate">{nomeVeiculo(v)}</div>
        <div className="text-[0.8rem] text-ink-3 truncate mt-0.5">{v.versao || " "}</div>
        <div className="text-xs text-ink-3 mt-3 mb-4 flex items-center gap-1.5 num flex-wrap">
          {dados.map((d, i) => (
            <span key={d} className="inline-flex items-center gap-1.5">{i > 0 && <span className="text-line-strong">·</span>}{d}</span>
          ))}
        </div>
        <div className="flex items-end justify-between gap-3 mt-auto pt-4 border-t border-line">
          <div className="min-w-0">
            {temPromocao(v) && <div className="text-[0.7rem] text-ink-3 line-through num mb-1">{formatPreco(v.preco_anterior)}</div>}
            <div className="font-heading text-[1.3rem] font-semibold tracking-tight num leading-none">{formatPreco(v.preco)}</div>
          </div>
          <div className={`text-[0.7rem] whitespace-nowrap ${v.parado ? "text-warning" : "text-ink-3"}`}>{diasNoPatio(v.dias_no_patio)}</div>
        </div>
      </div>
    </button>
  );
}

function Linha({ v, opcoes, onAbrir }) {
  return (
    <tr className="border-t border-line hover:bg-surface-2 cursor-pointer transition-colors" onClick={() => onAbrir(v)}
      data-testid={`veiculo-linha-${v.id}`}>
      <td className="py-3 pl-5 pr-3">
        <div className="flex items-center gap-4 min-w-0">
          <FotoCarro id={v.fotos?.[0]} className="w-28 aspect-[4/3] rounded-lg shrink-0" />
          <div className="min-w-0">
            <div className="font-heading font-semibold tracking-tight truncate">{nomeVeiculo(v)}</div>
            <div className="text-xs text-ink-3 truncate mt-0.5">{v.versao}</div>
            <div className="mt-1.5 flex items-center gap-2"><Placa placa={v.placa} /><SeloVeiculo v={v} /></div>
          </div>
        </div>
      </td>
      <td className="px-3 text-sm num">{formatAno(v)}</td>
      <td className="px-3 text-sm num">{formatKm(v.km)}</td>
      <td className="px-3 text-sm">{rotulo(opcoes, "categoria", v.categoria)}</td>
      <td className={`px-3 text-xs whitespace-nowrap ${v.parado ? "text-warning" : "text-ink-3"}`}>{diasNoPatio(v.dias_no_patio)}</td>
      <td className="pl-3 pr-5 text-right whitespace-nowrap">
        {temPromocao(v) && <div className="text-[0.7rem] text-ink-3 line-through num">{formatPreco(v.preco_anterior)}</div>}
        <div className="font-heading font-semibold num">{formatPreco(v.preco)}</div>
      </td>
    </tr>
  );
}

function Vazio({ filtrando, podeEditar, onCadastrar }) {
  return (
    <div className="zz-panel py-20 px-6 text-center flex flex-col items-center">
      <SilhuetaCarro className="w-56 text-ink-4 opacity-50" />
      <h2 className="font-heading text-2xl font-semibold tracking-tight mt-6">
        {filtrando ? "Nenhum carro com esse filtro." : "O pátio está vazio."}
      </h2>
      <p className="text-sm text-ink-3 mt-2 max-w-md">
        {filtrando
          ? "Tente outra busca ou volte para todos os veículos."
          : "Cadastre o primeiro carro com as fotos: ele aparece aqui na vitrine, pronto para mandar ao cliente."}
      </p>
      {!filtrando && podeEditar && (
        <button type="button" className="zz-btn mt-6 h-11" onClick={onCadastrar} data-testid="estoque-vazio-cadastrar">
          <Plus size={16} weight="bold" /> Cadastrar veículo
        </button>
      )}
    </div>
  );
}

export default function EstoquePage() {
  const { user } = useAuth();
  const podeEditar = user?.role === "tenant_admin";
  const [opcoes, setOpcoes] = useState(OPCOES_PADRAO);
  const [veiculos, setVeiculos] = useState(null);
  const [resumo, setResumo] = useState(null);
  const [busca, setBusca] = useState("");
  const [categoria, setCategoria] = useState("");
  const [situacao, setSituacao] = useState("estoque");
  const [ordem, setOrdem] = useState("recentes");
  const [vista, setVista] = useState(vistaGuardada);
  const [ficha, setFicha] = useState(null);
  const [form, setForm] = useState(null); // null fechado; {} novo; veículo para editar

  const carregar = useCallback(async () => {
    try {
      const [l, r] = await Promise.all([api.get("/estoque/veiculos"), api.get("/estoque/resumo")]);
      setVeiculos(l.data);
      setResumo(r.data);
    } catch (ex) {
      setVeiculos([]);
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);
  useEffect(() => {
    api.get("/estoque/opcoes").then((r) => setOpcoes(deApi(r.data))).catch(() => {});
  }, []);
  useEffect(() => { try { localStorage.setItem(CHAVE_VISTA, vista); } catch { /* conveniência */ } }, [vista]);

  // Filtro e ordem no cliente: o pátio inteiro já está aqui, e assim cada
  // clique responde na hora, sem esperar a rede.
  const semAcento = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const visiveis = useMemo(() => {
    if (!veiculos) return [];
    const termos = semAcento(busca).split(/\s+/).filter(Boolean);
    const lista = veiculos.filter((v) => {
      if (situacao === "estoque" && v.status === "vendido") return false;
      if (situacao && situacao !== "estoque" && v.status !== situacao) return false;
      if (categoria && v.categoria !== categoria) return false;
      if (termos.length) {
        const alvo = semAcento([v.marca, v.modelo, v.versao, v.placa, v.cor, v.ano_modelo].join(" "));
        return termos.every((t) => alvo.includes(t));
      }
      return true;
    });
    const chave = {
      recentes: [(v) => v.created_at || "", -1], preco_menor: [(v) => v.preco ?? Infinity, 1],
      preco_maior: [(v) => v.preco ?? -1, -1], km_menor: [(v) => v.km ?? Infinity, 1],
      ano_maior: [(v) => v.ano_modelo || 0, -1], mais_parados: [(v) => v.dias_no_patio || 0, -1],
    }[ordem];
    lista.sort((a, b) => {
      if (!!b.destaque !== !!a.destaque && ordem === "recentes") return b.destaque ? 1 : -1;
      const x = chave[0](a), y = chave[0](b);
      return (x < y ? -1 : x > y ? 1 : 0) * chave[1];
    });
    return lista;
  }, [veiculos, busca, categoria, situacao, ordem]);

  const contagemCategorias = useMemo(() => {
    const c = {};
    (veiculos || []).filter((v) => v.status !== "vendido").forEach((v) => { if (v.categoria) c[v.categoria] = (c[v.categoria] || 0) + 1; });
    return c;
  }, [veiculos]);
  const noPatio = (veiculos || []).filter((v) => v.status !== "vendido").length;

  const trocar = (novo) => {
    setVeiculos((l) => {
      const existe = l.some((v) => v.id === novo.id);
      return existe ? l.map((v) => (v.id === novo.id ? { ...v, ...novo } : v)) : [novo, ...l];
    });
    api.get("/estoque/resumo").then((r) => setResumo(r.data)).catch(() => {});
  };

  const [valorPatio, unidadePatio] = reaisCurto(resumo?.valor_patio);
  const filtrando = !!(busca || categoria || (situacao && situacao !== "estoque"));

  return (
    <div className="zz-page" data-testid="estoque-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-7">
        <div>
          <div className="zz-sobre">Estoque</div>
          <h1 className="font-heading text-4xl font-semibold tracking-tight mt-1.5">Vitrine</h1>
          <p className="text-ink-3 mt-2 text-sm">
            {veiculos === null ? " " : noPatio === 0 ? "Nenhum carro no pátio ainda." :
              `${noPatio} ${noPatio === 1 ? "veículo" : "veículos"} no pátio, prontos para encaminhar.`}
          </p>
        </div>
        {podeEditar && (
          <button type="button" className="zz-btn h-11" onClick={() => setForm({})} data-testid="estoque-cadastrar">
            <Plus size={16} weight="bold" /> Cadastrar veículo
          </button>
        )}
      </div>

      {resumo && resumo.em_estoque + (resumo.vendidos_mes || 0) > 0 && (
        <div className="zz-kpis mb-7">
          <Numero rotulo="No pátio" valor={resumo.em_estoque} unidade={resumo.em_estoque === 1 ? "veículo" : "veículos"}
            detalhe={`${resumo.entradas_mes} ${resumo.entradas_mes === 1 ? "entrada" : "entradas"} este mês${resumo.reservados ? ` · ${resumo.reservados} reservado${resumo.reservados > 1 ? "s" : ""}` : ""}`} />
          <Numero rotulo={resumo.giro_medio_dias !== null ? "Giro médio" : "Tempo médio no pátio"}
            valor={resumo.giro_medio_dias ?? resumo.dias_medio_patio ?? 0} unidade="dias"
            detalhe={`${resumo.vendidos_mes} ${resumo.vendidos_mes === 1 ? "vendido" : "vendidos"} este mês`} />
          <Numero rotulo={`Parados há +${resumo.parado_dias} dias`} valor={resumo.parados}
            unidade={resumo.parados === 1 ? "veículo" : "veículos"}
            detalhe={resumo.parados ? `${formatPreco(resumo.valor_parado)} imobilizados` : "Nenhum carro encalhado"}
            tom={resumo.parados ? "alerta" : null} />
          <Numero rotulo="Valor em pátio" valor={valorPatio} unidade={unidadePatio}
            detalhe={resumo.em_estoque ? `Ticket médio ${formatPreco(resumo.ticket_medio)}` : null} />
        </div>
      )}

      {veiculos && veiculos.length > 0 && (
        <div className="flex flex-col gap-3 mb-5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[16rem] max-w-md">
              <MagnifyingGlass size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-3" />
              <input className="zz-input pl-10 h-11" placeholder="Buscar por marca, modelo, versão ou placa"
                value={busca} onChange={(e) => setBusca(e.target.value)} data-testid="estoque-busca" />
            </div>
            <div className="zz-segmento" role="radiogroup" aria-label="Situação">
              {SITUACOES.map(([valor, r]) => (
                <button key={valor || "todos"} type="button" role="radio" aria-checked={situacao === valor}
                  className={situacao === valor ? "ativo" : ""} onClick={() => setSituacao(valor)}
                  data-testid={`estoque-situacao-${valor || "todos"}`}>{r}</button>
              ))}
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <select className="zz-input h-11 w-auto pr-9" value={ordem} onChange={(e) => setOrdem(e.target.value)}
                aria-label="Ordenar" data-testid="estoque-ordem">
                {ORDENS.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
              </select>
              <div className="zz-segmento" role="radiogroup" aria-label="Vista">
                <button type="button" role="radio" aria-checked={vista === "grade"} className={vista === "grade" ? "ativo" : ""}
                  onClick={() => setVista("grade")} aria-label="Grade" title="Grade"><SquaresFour size={16} /></button>
                <button type="button" role="radio" aria-checked={vista === "lista"} className={vista === "lista" ? "ativo" : ""}
                  onClick={() => setVista("lista")} aria-label="Lista" title="Lista"><Rows size={16} /></button>
              </div>
            </div>
          </div>
          {Object.keys(contagemCategorias).length > 1 && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={`zz-chip ${categoria === "" ? "ativo" : ""}`} onClick={() => setCategoria("")}>
                Todas <span className="num">· {noPatio}</span>
              </button>
              {(opcoes.categoria || []).filter(([v]) => contagemCategorias[v]).map(([v, r]) => (
                <button key={v} type="button" className={`zz-chip ${categoria === v ? "ativo" : ""}`}
                  onClick={() => setCategoria(categoria === v ? "" : v)} data-testid={`estoque-categoria-${v}`}>
                  {r} <span className="num">· {contagemCategorias[v]}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {veiculos === null ? (
        <div className="zz-vitrine">
          {Array.from({ length: 8 }).map((_, n) => (
            <div key={n} className="zz-carro-cartao pointer-events-none">
              <div className="aspect-[4/3] bg-surface-3 animate-pulse" />
              <div className="p-5 space-y-2"><div className="h-4 w-2/3 bg-surface-3 rounded animate-pulse" /><div className="h-3 w-1/2 bg-surface-3 rounded animate-pulse" /></div>
            </div>
          ))}
        </div>
      ) : visiveis.length === 0 ? (
        <Vazio filtrando={filtrando && veiculos.length > 0} podeEditar={podeEditar} onCadastrar={() => setForm({})} />
      ) : vista === "grade" ? (
        <div className="zz-vitrine">
          {visiveis.map((v) => <Cartao key={v.id} v={v} opcoes={opcoes} onAbrir={setFicha} />)}
        </div>
      ) : (
        <div className="zz-panel overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead>
              <tr className="zz-sobre !text-[0.6rem]">
                <th className="py-3.5 pl-5 pr-3 font-semibold">Veículo</th>
                <th className="px-3 font-semibold">Ano</th>
                <th className="px-3 font-semibold">Km</th>
                <th className="px-3 font-semibold">Categoria</th>
                <th className="px-3 font-semibold">No pátio</th>
                <th className="pl-3 pr-5 text-right font-semibold">Preço</th>
              </tr>
            </thead>
            <tbody>{visiveis.map((v) => <Linha key={v.id} v={v} opcoes={opcoes} onAbrir={setFicha} />)}</tbody>
          </table>
        </div>
      )}

      {ficha && (
        <FichaVeiculo
          veiculo={ficha} opcoes={opcoes} podeEditar={podeEditar}
          onFechar={() => setFicha(null)}
          onEditar={() => { setForm(ficha); setFicha(null); }}
          onMudou={(novo) => { trocar(novo); setFicha((f) => ({ ...f, ...novo })); }}
          onExcluido={(id) => { setVeiculos((l) => l.filter((v) => v.id !== id)); setFicha(null); carregar(); }}
        />
      )}
      {form && (
        <FormVeiculo
          veiculo={form.id ? form : null} opcoes={opcoes}
          onFechar={() => setForm(null)}
          onSalvo={(novo, { silencioso } = {}) => {
            trocar(novo);
            setForm(null);
            if (!silencioso) setFicha(novo);
          }}
        />
      )}
    </div>
  );
}
