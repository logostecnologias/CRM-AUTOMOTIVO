import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ArrowsClockwise, Table, X } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { formatPreco } from "./estoque";

// Tabela FIPE na ficha do veículo (ver backend/fipe.py).
//
// A loja liga o carro ao modelo FIPE uma vez, escolhendo marca → modelo →
// ano; a ficha passa a mostrar o valor de referência e a diferença para o
// preço, e a IA usa esse valor ("abaixo da FIPE"). A tabela muda todo mês, e
// "Atualizar" busca o valor do mês com o mesmo vínculo.
//
// A marca e o ano vêm pré-escolhidos a partir da ficha, e o modelo é filtrado
// pelo que está escrito nela: a lista da Fiat tem quase 600 modelos.

const sem = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const erro = (ex) => formatApiErrorDetail(ex.response?.data?.detail) || ex.message;

function Seletor({ v, onSalvo, onCancelar }) {
  const tipo = v.categoria === "moto" ? "moto" : "carro";
  const [marcas, setMarcas] = useState([]);
  const [marca, setMarca] = useState("");
  const [modelos, setModelos] = useState([]);
  const [filtro, setFiltro] = useState(v.modelo || "");
  const [modelo, setModelo] = useState("");
  const [anos, setAnos] = useState([]);
  const [ano, setAno] = useState("");
  const [preco, setPreco] = useState(null);
  const [carregando, setCarregando] = useState("");

  const buscar = async (rotulo, url, params, fn) => {
    setCarregando(rotulo);
    try { fn((await api.get(url, { params: { tipo, ...params } })).data); }
    catch (ex) { toast.error(erro(ex)); }
    finally { setCarregando(""); }
  };

  useEffect(() => {
    buscar("marcas", "/fipe/marcas", {}, (lista) => {
      setMarcas(lista);
      const alvo = sem(v.marca);
      const achada = lista.find((m) => sem(m.nome) === alvo)
        || lista.find((m) => alvo && sem(m.nome).includes(alvo));
      if (achada) setMarca(achada.id);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setModelos([]); setModelo(""); setAnos([]); setAno(""); setPreco(null);
    if (marca) buscar("modelos", "/fipe/modelos", { marca }, setModelos);
  }, [marca]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setAnos([]); setAno(""); setPreco(null);
    if (!modelo) return;
    buscar("anos", "/fipe/anos", { marca, modelo }, (lista) => {
      setAnos(lista);
      const alvo = String(v.ano_modelo || v.ano_fabricacao || "");
      const achado = lista.find((a) => alvo && String(a.id).startsWith(`${alvo}-`));
      if (achado) setAno(achado.id);
    });
  }, [modelo]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setPreco(null);
    if (ano) buscar("preço", "/fipe/preco", { marca, modelo, ano }, setPreco);
  }, [ano]); // eslint-disable-line react-hooks/exhaustive-deps

  const visiveis = useMemo(() => {
    const termos = sem(filtro).split(/\s+/).filter(Boolean);
    return modelos.filter((m) => termos.every((t) => sem(m.nome).includes(t)));
  }, [modelos, filtro]);

  const [salvar, salvando] = useAcao(async () => {
    try {
      const { data } = await api.put(`/estoque/veiculos/${v.id}/fipe`,
        { tipo, marca_id: marca, modelo_id: modelo, ano_id: ano });
      toast.success("Veículo ligado à tabela FIPE");
      onSalvo(data);
    } catch (ex) { toast.error(erro(ex)); }
  });

  return (
    <div className="space-y-2.5 mt-2.5" data-testid="fipe-seletor">
      <select className="zz-input h-9 w-full" value={marca} onChange={(e) => setMarca(e.target.value)} data-testid="fipe-marca">
        <option value="">{carregando === "marcas" ? "Carregando marcas…" : "Marca"}</option>
        {marcas.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
      </select>
      {marca && (
        <>
          <input className="zz-input h-9 w-full" value={filtro} onChange={(e) => setFiltro(e.target.value)}
            placeholder="Filtrar modelo (ex.: strada freedom 1.3)" data-testid="fipe-filtro" />
          <select className="zz-input h-9 w-full" value={modelo} onChange={(e) => setModelo(e.target.value)} data-testid="fipe-modelo">
            <option value="">
              {carregando === "modelos" ? "Carregando modelos…" : `Modelo (${visiveis.length} de ${modelos.length})`}
            </option>
            {visiveis.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
          </select>
        </>
      )}
      {modelo && (
        <select className="zz-input h-9 w-full" value={ano} onChange={(e) => setAno(e.target.value)} data-testid="fipe-ano">
          <option value="">{carregando === "anos" ? "Carregando anos…" : "Ano do modelo"}</option>
          {anos.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
        </select>
      )}
      {carregando === "preço" && <div className="text-xs text-ink-3">Consultando o valor…</div>}
      {preco && (
        <div className="text-sm num">FIPE <strong>{formatPreco(preco.valor)}</strong>
          <span className="text-ink-3 text-xs"> · {preco.referencia}</span></div>
      )}
      <div className="flex gap-2 justify-end">
        <button type="button" className="zz-btn zz-btn-secondary h-9" onClick={onCancelar}>Cancelar</button>
        <button type="button" className="zz-btn h-9" disabled={!preco || salvando} onClick={salvar} data-testid="fipe-salvar">
          {salvando ? "Salvando…" : "Usar este"}
        </button>
      </div>
    </div>
  );
}

export default function FipeVeiculo({ veiculo: v, podeEditar, onMudou }) {
  const [escolhendo, setEscolhendo] = useState(false);
  const f = v.fipe;

  const [atualizar, atualizando] = useAcao(async () => {
    try {
      const { data } = await api.put(`/estoque/veiculos/${v.id}/fipe`,
        { tipo: f.tipo, marca_id: f.marca_id, modelo_id: f.modelo_id, ano_id: f.ano_id });
      onMudou({ ...v, fipe: data });
      toast.success(data.valor === f.valor ? "Sem mudança na tabela" : "Valor FIPE atualizado");
    } catch (ex) { toast.error(erro(ex)); }
  });

  const [remover, removendo] = useAcao(async () => {
    try {
      await api.delete(`/estoque/veiculos/${v.id}/fipe`);
      onMudou({ ...v, fipe: null });
    } catch (ex) { toast.error(erro(ex)); }
  });

  if (!f && !podeEditar) return null;

  const diferenca = f && v.preco ? v.preco - f.valor : null;
  const pct = diferenca != null && f.valor ? Math.abs(diferenca / f.valor) * 100 : null;

  return (
    <div className="mt-5 rounded-2xl border border-line p-4" data-testid="fipe-bloco">
      <div className="flex items-center justify-between gap-2">
        <div className="zz-sobre flex items-center gap-1.5"><Table size={13} /> Tabela FIPE</div>
        {f && podeEditar && !escolhendo && (
          <div className="flex gap-1">
            <button type="button" className="zz-btn-icon" onClick={atualizar} disabled={atualizando}
              title="Buscar o valor do mês" aria-label="Atualizar"><ArrowsClockwise size={14} /></button>
            <button type="button" className="zz-btn-icon" onClick={() => setEscolhendo(true)}
              title="Trocar o modelo FIPE" aria-label="Trocar"><Table size={14} /></button>
            <button type="button" className="zz-btn-icon" onClick={remover} disabled={removendo}
              title="Desligar da tabela FIPE" aria-label="Remover"><X size={14} /></button>
          </div>
        )}
      </div>
      {f && !escolhendo && (
        <>
          <div className="flex items-baseline gap-3 mt-2 flex-wrap">
            <span className="font-heading text-xl font-semibold num">{formatPreco(f.valor)}</span>
            {diferenca != null && Math.round(diferenca) !== 0 && (
              <span className={`text-xs font-semibold num ${diferenca < 0 ? "text-success" : "text-warning"}`}>
                {formatPreco(Math.abs(diferenca))} {diferenca < 0 ? "abaixo" : "acima"} da FIPE ({pct.toFixed(1).replace(".", ",")}%)
              </span>
            )}
          </div>
          <div className="text-xs text-ink-3 mt-1">
            {f.modelo} · {f.ano} · referência {f.referencia}{f.codigo ? ` · código ${f.codigo}` : ""}
          </div>
        </>
      )}
      {!f && !escolhendo && (
        <div className="flex items-center justify-between gap-3 mt-2">
          <span className="text-xs text-ink-3">Ligue ao modelo da tabela para ver o valor de referência e a diferença para o preço.</span>
          <button type="button" className="zz-btn zz-btn-secondary h-9 shrink-0" onClick={() => setEscolhendo(true)} data-testid="fipe-ligar">
            Ligar à FIPE
          </button>
        </div>
      )}
      {escolhendo && (
        <Seletor v={v} onCancelar={() => setEscolhendo(false)}
          onSalvo={(fipe) => { setEscolhendo(false); onMudou({ ...v, fipe }); }} />
      )}
    </div>
  );
}
