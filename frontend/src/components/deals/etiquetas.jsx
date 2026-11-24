import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { Car, X } from "@phosphor-icons/react";

// Os três dados do lead de revenda que aparecem em pílula: temperatura,
// forma de pagamento e o carro de interesse. As chaves são as do backend
// (`routes/deals.py`: TEMPERATURAS e PAGAMENTOS).
export const TEMPERATURAS = [
  { valor: "quente", rotulo: "Quente" },
  { valor: "morno", rotulo: "Morno" },
  { valor: "frio", rotulo: "Frio" },
];

export const PAGAMENTOS = [
  { valor: "a_vista", rotulo: "À vista" },
  { valor: "financiamento", rotulo: "Financiamento" },
  { valor: "troca", rotulo: "Troca" },
  { valor: "consorcio", rotulo: "Consórcio" },
];

const rotulo = (lista, v) => lista.find((x) => x.valor === v)?.rotulo || v;

export function Pilula({ classe = "", children, title }) {
  return <span className={`zz-pilula ${classe}`} title={title}>{children}</span>;
}

// Temperatura e pagamento em pílulas, na ordem fixa. Nada aparece quando não
// há dado: pílula "sem informação" é ruído.
export function PilulasDoNegocio({ deal }) {
  const pag = deal?.pagamento || [];
  if (!deal?.temperatura && !pag.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {deal.temperatura && (
        <Pilula classe={deal.temperatura}>{rotulo(TEMPERATURAS, deal.temperatura)}</Pilula>
      )}
      {pag.map((p) => <Pilula key={p} classe={p}>{rotulo(PAGAMENTOS, p)}</Pilula>)}
    </div>
  );
}

// Escolha por clique: uma temperatura só (clicar de novo limpa) e quantas
// formas de pagamento quiser ("financiamento + troca" é o caso comum).
export function EscolhaTemperatura({ valor, onChange }) {
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Temperatura">
      {TEMPERATURAS.map((t) => (
        <button key={t.valor} type="button" aria-pressed={valor === t.valor}
          className={`zz-pilula ${t.valor}`} data-testid={`deal-temp-${t.valor}`}
          onClick={() => onChange(valor === t.valor ? "" : t.valor)}>
          {t.rotulo}
        </button>
      ))}
    </div>
  );
}

export function EscolhaPagamento({ valor = [], onChange }) {
  const alterna = (v) => onChange(valor.includes(v) ? valor.filter((x) => x !== v) : [...valor, v]);
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Forma de pagamento">
      {PAGAMENTOS.map((p) => (
        <button key={p.valor} type="button" aria-pressed={valor.includes(p.valor)}
          className={`zz-pilula ${p.valor}`} data-testid={`deal-pag-${p.valor}`}
          onClick={() => alterna(p.valor)}>
          {p.rotulo}
        </button>
      ))}
    </div>
  );
}

const nomeVeiculo = (v) => v.nome
  || [v.marca, v.modelo, v.versao, v.ano_modelo].filter(Boolean).join(" ");

// Busca no estoque (o mesmo `/estoque/veiculos` da tela do pátio) para ligar o
// carro de interesse ao negócio. Vendido não é oferecido.
export function EscolhaVeiculo({ veiculo, onChange }) {
  const [q, setQ] = useState("");
  const [lista, setLista] = useState([]);
  const [aberto, setAberto] = useState(false);
  const caixa = useRef(null);

  useEffect(() => {
    if (!aberto) return undefined;
    const id = setTimeout(() => {
      api.get("/estoque/veiculos", { params: { q, status: "estoque" } })
        .then((r) => setLista((r.data || []).slice(0, 8)))
        .catch(() => setLista([]));
    }, 250);
    return () => clearTimeout(id);
  }, [q, aberto]);

  useEffect(() => {
    const fora = (e) => { if (caixa.current && !caixa.current.contains(e.target)) setAberto(false); };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, []);

  if (veiculo) {
    return (
      <div className="flex items-center gap-2 text-sm min-w-0" data-testid="deal-veiculo">
        <Car size={14} className="text-ink-3 shrink-0" />
        <span className="truncate">{nomeVeiculo(veiculo)}</span>
        {veiculo.placa && <span className="font-mono text-[11px] text-ink-3 shrink-0">{veiculo.placa}</span>}
        <button type="button" className="ml-auto p-1 hover:bg-surface-3 rounded-md" title="Tirar o carro"
          onClick={() => onChange(null)} data-testid="deal-veiculo-limpar">
          <X size={12} weight="bold" />
        </button>
      </div>
    );
  }
  return (
    <div className="relative" ref={caixa}>
      <input className="zz-input h-8 py-1 text-sm" placeholder="Buscar no estoque: modelo, placa…"
        value={q} onFocus={() => setAberto(true)} onChange={(e) => { setQ(e.target.value); setAberto(true); }}
        data-testid="deal-veiculo-busca" />
      {aberto && lista.length > 0 && (
        <div className="zz-busca-lista">
          {lista.map((v) => (
            <button key={v.id} type="button" className="zz-busca-item"
              onClick={() => { onChange({ ...v, nome: nomeVeiculo(v) }); setAberto(false); setQ(""); }}>
              <Car size={14} className="text-ink-3 shrink-0" />
              <span className="truncate flex-1">{nomeVeiculo(v)}</span>
              {v.placa && <span className="font-mono text-[11px] text-ink-3">{v.placa}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
