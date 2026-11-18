import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, ImageSquare, Star, Trash, UploadSimple, X } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { parseBRLInput } from "@/lib/currency";
import Modal from "@/components/ui/Modal";
import { MARCAS_SUGERIDAS, fotoUrl, reduzirImagem } from "./estoque";

const hoje = () => new Date().toISOString().slice(0, 10);

const vazio = () => ({
  marca: "", modelo: "", versao: "", categoria: "", condicao: "seminovo",
  ano_fabricacao: "", ano_modelo: "", km: "", preco: null, preco_anterior: null,
  cambio: "", combustivel: "", motor: "", portas: "", cor: "",
  placa: "", localizacao: "", entrada_em: hoje(),
  opcionais: [], observacoes: "", destaque: false, status: "disponivel",
});

const doVeiculo = (v) => ({
  ...vazio(),
  ...Object.fromEntries(Object.entries(v).map(([k, val]) => [k, val ?? (k.startsWith("preco") ? null : "")])),
  opcionais: v.opcionais || [],
  destaque: !!v.destaque,
  entrada_em: (v.entrada_em || hoje()).slice(0, 10),
});

// O corpo que vai para a API: texto vazio vira null (apaga o campo), número
// digitado vira número.
function corpo(f) {
  const num = (x) => (x === "" || x === null || x === undefined ? null : Number(x));
  const txt = (x) => (x && String(x).trim()) || null;
  return {
    marca: f.marca.trim(), modelo: f.modelo.trim(), versao: txt(f.versao),
    categoria: f.categoria || null, condicao: f.condicao || null,
    ano_fabricacao: num(f.ano_fabricacao), ano_modelo: num(f.ano_modelo), km: num(f.km),
    preco: f.preco, preco_anterior: f.preco_anterior, cambio: f.cambio || null, combustivel: f.combustivel || null,
    motor: txt(f.motor), portas: num(f.portas), cor: txt(f.cor),
    placa: txt(f.placa), localizacao: txt(f.localizacao), entrada_em: f.entrada_em || null,
    opcionais: f.opcionais, observacoes: txt(f.observacoes), destaque: f.destaque, status: f.status,
  };
}

function Secao({ titulo, children, className = "" }) {
  return (
    <section className={className}>
      <div className="zz-sobre mb-3">{titulo}</div>
      {children}
    </section>
  );
}

function Campo({ rotulo, children, className = "", dica }) {
  return (
    <label className={`block ${className}`}>
      <span className="text-xs font-medium text-ink-2 block mb-1.5">{rotulo}</span>
      {children}
      {dica && <span className="text-[11px] text-ink-3 mt-1 block">{dica}</span>}
    </label>
  );
}

function Escolha({ valor, onChange, opcoes, vazioRotulo = "—", semVazio = false, testId }) {
  return (
    <select className="zz-input" value={valor || ""} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
      {!semVazio && <option value="">{vazioRotulo}</option>}
      {opcoes.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
    </select>
  );
}

/** Opcionais como etiquetas: digita e Enter (ou vírgula) acrescenta. */
function Opcionais({ lista, onChange }) {
  const [texto, setTexto] = useState("");
  const acrescentar = () => {
    const t = texto.trim();
    if (t && !lista.some((o) => o.toLowerCase() === t.toLowerCase())) onChange([...lista, t]);
    setTexto("");
  };
  return (
    <div className="zz-input flex flex-wrap gap-1.5 items-center min-h-[2.9rem] !py-1.5 cursor-text"
      onClick={(e) => e.currentTarget.querySelector("input")?.focus()}>
      {lista.map((o) => (
        <span key={o} className="inline-flex items-center gap-1 bg-surface-3 text-ink rounded-lg pl-2.5 pr-1 py-1 text-xs font-medium">
          {o}
          <button type="button" className="p-0.5 rounded hover:bg-line text-ink-3 hover:text-ink"
            onClick={() => onChange(lista.filter((x) => x !== o))} aria-label={`Tirar ${o}`}>
            <X size={11} weight="bold" />
          </button>
        </span>
      ))}
      <input className="flex-1 min-w-[10rem] bg-transparent outline-none text-sm py-1"
        value={texto} onChange={(e) => setTexto(e.target.value)} onBlur={acrescentar}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") { e.preventDefault(); acrescentar(); }
          if (e.key === "Backspace" && !texto && lista.length) onChange(lista.slice(0, -1));
        }}
        placeholder={lista.length ? "" : "Teto solar, bancos de couro, multimídia… (Enter acrescenta)"}
        data-testid="veiculo-opcionais" />
    </div>
  );
}

/**
 * As fotos do carro. A primeira é a capa. Reordenar é por setas e "tornar
 * capa", que funcionam igual no mouse, no toque e no teclado.
 *
 * Carro novo ainda não tem id, então as fotos ficam na fila (com prévia local)
 * e sobem logo depois de o carro ser criado. Carro existente sobe na hora.
 */
function Fotos({ fotos, fila, onEscolher, onMover, onCapa, onApagar, enviando }) {
  const input = useRef(null);
  const [arrastando, setArrastando] = useState(false);
  const itens = [...fotos.map((id) => ({ id, src: fotoUrl(id) })), ...fila.map((f) => ({ id: f.chave, src: f.previa, fila: true }))];
  return (
    <div>
      <div
        className={`zz-soltar ${arrastando ? "ativo" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
        onDragLeave={() => setArrastando(false)}
        onDrop={(e) => { e.preventDefault(); setArrastando(false); onEscolher([...e.dataTransfer.files]); }}
        onClick={() => input.current?.click()}
        role="button" tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
        data-testid="veiculo-fotos-soltar"
      >
        <UploadSimple size={22} className="text-ink-3" />
        <div className="text-sm font-medium mt-2">{enviando ? "Enviando fotos…" : "Arraste as fotos aqui ou clique para escolher"}</div>
        <div className="text-xs text-ink-3 mt-0.5">JPG, PNG ou WebP. Até 30 fotos; a primeira é a capa.</div>
        <input ref={input} type="file" accept="image/*" multiple hidden
          onChange={(e) => { onEscolher([...e.target.files]); e.target.value = ""; }} />
      </div>

      {itens.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2.5 mt-3">
          {itens.map((f, i) => (
            <div key={f.id} className="group relative aspect-[4/3] rounded-xl overflow-hidden bg-surface-3 border border-line">
              <img src={f.src} alt="" className={`w-full h-full object-cover ${f.fila ? "opacity-70" : ""}`} draggable={false} />
              {i === 0 && <span className="absolute top-1.5 left-1.5 zz-selo-carro destaque">Capa</span>}
              {f.fila && <span className="absolute bottom-1.5 left-1.5 zz-selo-carro">Na fila</span>}
              <div className="absolute inset-x-0 bottom-0 p-1.5 flex justify-end gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity bg-gradient-to-t from-black/50 to-transparent">
                {!f.fila && i > 0 && (
                  <>
                    <button type="button" className="zz-foto-acao" onClick={() => onCapa(f.id)} title="Tornar capa" aria-label="Tornar capa"><Star size={13} weight="fill" /></button>
                    <button type="button" className="zz-foto-acao" onClick={() => onMover(i, -1)} title="Mover para a esquerda" aria-label="Mover para a esquerda"><ArrowLeft size={13} weight="bold" /></button>
                  </>
                )}
                {!f.fila && i < fotos.length - 1 && (
                  <button type="button" className="zz-foto-acao" onClick={() => onMover(i, 1)} title="Mover para a direita" aria-label="Mover para a direita"><ArrowRight size={13} weight="bold" /></button>
                )}
                <button type="button" className="zz-foto-acao perigo" onClick={() => onApagar(f)} title="Tirar foto" aria-label="Tirar foto"><Trash size={13} weight="bold" /></button>
              </div>
            </div>
          ))}
        </div>
      )}
      {itens.length === 0 && (
        <div className="flex items-center gap-2 text-xs text-ink-3 mt-3">
          <ImageSquare size={14} /> Carro com foto vende mais: a capa é o que aparece na vitrine.
        </div>
      )}
    </div>
  );
}

/** Campo de reais: digita só números, os dois últimos são centavos. */
function CampoReais({ valor, onChange, testId, placeholder = "0,00" }) {
  const formata = (n) => (n || n === 0 ? Number(n).toLocaleString("pt-BR", { minimumFractionDigits: 2 }) : "");
  const [texto, setTexto] = useState(() => formata(valor));
  return (
    <div className="relative">
      <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-sm text-ink-3">R$</span>
      <input className="zz-input pl-10 num" inputMode="numeric" value={texto} placeholder={placeholder}
        data-testid={testId}
        onChange={(e) => {
          const tem = !!e.target.value.replace(/\D/g, "");
          const n = parseBRLInput(e.target.value);
          setTexto(tem ? formata(n) : "");
          onChange(tem ? n : null);
        }} />
    </div>
  );
}

export default function FormVeiculo({ veiculo, opcoes, onFechar, onSalvo }) {
  const editando = !!veiculo?.id;
  const [f, setF] = useState(() => (editando ? doVeiculo(veiculo) : vazio()));
  const [fotos, setFotos] = useState(veiculo?.fotos || []);
  const [fila, setFila] = useState([]);
  const [enviando, setEnviando] = useState(false);
  const mudou = useRef(false);
  const set = (campo) => (valor) => { mudou.current = true; setF((x) => ({ ...x, [campo]: valor })); };
  const ev = (campo) => (e) => set(campo)(e.target.value);

  useEffect(() => () => fila.forEach((x) => URL.revokeObjectURL(x.previa)), []); // eslint-disable-line react-hooks/exhaustive-deps

  const subir = async (id, arquivos) => {
    let lista = null;
    for (const arq of arquivos) {
      const reduzida = await reduzirImagem(arq);
      const dados = new FormData();
      dados.append("file", reduzida);
      try {
        const { data } = await api.post(`/estoque/veiculos/${id}/fotos`, dados);
        lista = data.fotos;
        setFotos(data.fotos);
      } catch (ex) {
        toast.error(`${arq.name}: ${formatApiErrorDetail(ex.response?.data?.detail) || ex.message}`);
      }
    }
    return lista;
  };

  const escolher = async (arquivos) => {
    const imagens = arquivos.filter((a) => a.type.startsWith("image/"));
    if (imagens.length < arquivos.length) toast.error("Só imagens entram como foto do veículo.");
    if (!imagens.length) return;
    if (!editando) {
      setFila((q) => [...q, ...imagens.map((a) => ({ chave: `${a.name}-${a.size}-${Math.random()}`, arquivo: a, previa: URL.createObjectURL(a) }))]);
      return;
    }
    setEnviando(true);
    await subir(veiculo.id, imagens);
    setEnviando(false);
    mudou.current = true;
  };

  const salvarOrdem = async (nova) => {
    setFotos(nova);
    try { await api.put(`/estoque/veiculos/${veiculo.id}/fotos/ordem`, { ids: nova }); mudou.current = true; }
    catch (ex) { toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message); }
  };
  const mover = (i, d) => {
    const nova = [...fotos];
    [nova[i], nova[i + d]] = [nova[i + d], nova[i]];
    salvarOrdem(nova);
  };
  const capa = (id) => salvarOrdem([id, ...fotos.filter((x) => x !== id)]);
  const apagar = async (item) => {
    if (item.fila) {
      setFila((q) => q.filter((x) => x.chave !== item.id));
      return;
    }
    try {
      const { data } = await api.delete(`/estoque/veiculos/${veiculo.id}/fotos/${item.id}`);
      setFotos(data.fotos);
      mudou.current = true;
    } catch (ex) { toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message); }
  };

  const salvar = async () => {
    try {
      let salvo;
      if (editando) {
        ({ data: salvo } = await api.patch(`/estoque/veiculos/${veiculo.id}`, corpo(f)));
      } else {
        ({ data: salvo } = await api.post("/estoque/veiculos", corpo(f)));
        if (fila.length) {
          setEnviando(true);
          const lista = await subir(salvo.id, fila.map((x) => x.arquivo));
          if (lista) salvo = { ...salvo, fotos: lista };
          setEnviando(false);
        }
      }
      toast.success(editando ? "Veículo atualizado" : "Veículo cadastrado no pátio");
      onSalvo({ ...salvo, fotos: editando ? fotos : salvo.fotos });
    } catch (ex) {
      setEnviando(false);
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message);
    }
  };

  // Fechar sem salvar ainda conta o que já mudou nas fotos, que salvam na hora.
  const fechar = () => (mudou.current && editando ? onSalvo({ ...veiculo, fotos }, { silencioso: true }) : onFechar());

  return (
    <Modal
      titulo={editando ? "Editar veículo" : "Cadastrar veículo"}
      descricao={editando ? undefined : "Só marca e modelo são obrigatórios. O resto pode ser completado depois."}
      largo onFechar={fechar} onSalvar={salvar}
      salvarLabel={editando ? "Salvar" : "Cadastrar"} salvandoLabel={enviando ? "Enviando fotos…" : "Salvando…"}
      corpoClasse="space-y-8" testId="form-veiculo"
    >
      <Secao titulo="Fotos">
        <Fotos fotos={fotos} fila={fila} onEscolher={escolher} onMover={mover} onCapa={capa} onApagar={apagar} enviando={enviando} />
      </Secao>

      <Secao titulo="O carro">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Campo rotulo="Marca *">
            <input className="zz-input" required value={f.marca} onChange={ev("marca")} list="zz-marcas"
              placeholder="Volkswagen" autoFocus={!editando} data-testid="veiculo-marca" />
            <datalist id="zz-marcas">{MARCAS_SUGERIDAS.map((m) => <option key={m} value={m} />)}</datalist>
          </Campo>
          <Campo rotulo="Modelo *">
            <input className="zz-input" required value={f.modelo} onChange={ev("modelo")} placeholder="Taos" data-testid="veiculo-modelo" />
          </Campo>
          <Campo rotulo="Versão" className="col-span-2">
            <input className="zz-input" value={f.versao} onChange={ev("versao")} placeholder="1.4 250 TSI Highline Flex Aut." data-testid="veiculo-versao" />
          </Campo>
          <Campo rotulo="Categoria"><Escolha valor={f.categoria} onChange={set("categoria")} opcoes={opcoes.categoria} testId="veiculo-categoria" /></Campo>
          <Campo rotulo="Condição"><Escolha valor={f.condicao} onChange={set("condicao")} opcoes={opcoes.condicao} /></Campo>
          <Campo rotulo="Ano de fabricação">
            <input className="zz-input" type="number" inputMode="numeric" value={f.ano_fabricacao} onChange={ev("ano_fabricacao")} placeholder="2024" />
          </Campo>
          <Campo rotulo="Ano do modelo">
            <input className="zz-input" type="number" inputMode="numeric" value={f.ano_modelo} onChange={ev("ano_modelo")} placeholder="2025" data-testid="veiculo-ano" />
          </Campo>
        </div>
      </Secao>

      <Secao titulo="Preço e quilometragem">
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 items-end">
          <Campo rotulo="Preço">
            <CampoReais valor={f.preco} onChange={set("preco")} testId="veiculo-preco" />
          </Campo>
          <Campo rotulo="Preço anterior (de)" dica="Aparece riscado, se for maior que o preço.">
            <CampoReais valor={f.preco_anterior} onChange={set("preco_anterior")} testId="veiculo-preco-anterior" placeholder="Opcional" />
          </Campo>
          <Campo rotulo="Quilometragem">
            <div className="relative">
              <input className="zz-input pr-10 num" type="number" inputMode="numeric" min="0" value={f.km} onChange={ev("km")} placeholder="0" data-testid="veiculo-km" />
              <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-sm text-ink-3">km</span>
            </div>
          </Campo>
          <Campo rotulo="Situação"><Escolha valor={f.status || "disponivel"} onChange={set("status")} opcoes={opcoes.status} semVazio testId="veiculo-status" /></Campo>
          <label className="flex items-center gap-3 h-[2.9rem] px-3.5 rounded-xl border border-line-strong cursor-pointer select-none hover:border-ink-4 transition-colors">
            <input type="checkbox" className="accent-[var(--brand)] w-4 h-4" checked={f.destaque}
              onChange={(e) => set("destaque")(e.target.checked)} data-testid="veiculo-destaque" />
            <span className="text-sm">Destaque na vitrine</span>
          </label>
        </div>
      </Secao>

      <Secao titulo="Ficha técnica">
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <Campo rotulo="Câmbio"><Escolha valor={f.cambio} onChange={set("cambio")} opcoes={opcoes.cambio} /></Campo>
          <Campo rotulo="Combustível"><Escolha valor={f.combustivel} onChange={set("combustivel")} opcoes={opcoes.combustivel} /></Campo>
          <Campo rotulo="Motor"><input className="zz-input" value={f.motor} onChange={ev("motor")} placeholder="1.4 Turbo" /></Campo>
          <Campo rotulo="Portas"><input className="zz-input" type="number" min="0" max="6" value={f.portas} onChange={ev("portas")} placeholder="4" /></Campo>
          <Campo rotulo="Cor"><input className="zz-input" value={f.cor} onChange={ev("cor")} placeholder="Preto" /></Campo>
        </div>
        <Campo rotulo="Opcionais" className="mt-4"><Opcionais lista={f.opcionais} onChange={set("opcionais")} /></Campo>
      </Secao>

      <Secao titulo="No pátio">
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          <Campo rotulo="Placa" dica="Fica só para a loja: não aparece no catálogo.">
            <input className="zz-input uppercase tracking-wider" value={f.placa} maxLength={8}
              onChange={(e) => set("placa")(e.target.value.toUpperCase())} placeholder="ABC1D23" data-testid="veiculo-placa" />
          </Campo>
          <Campo rotulo="Localização"><input className="zz-input" value={f.localizacao} onChange={ev("localizacao")} placeholder="Matriz, pátio 2…" /></Campo>
          <Campo rotulo="Entrada no pátio" dica="Conta os dias parados.">
            <input className="zz-input" type="date" value={f.entrada_em} max={hoje()} onChange={ev("entrada_em")} />
          </Campo>
        </div>
      </Secao>

      <Secao titulo="Descrição do anúncio">
        <textarea className="zz-input min-h-[7rem]" value={f.observacoes} onChange={ev("observacoes")} maxLength={4000}
          placeholder="Único dono, revisões na concessionária, laudo cautelar aprovado…" data-testid="veiculo-observacoes" />
      </Secao>
    </Modal>
  );
}
