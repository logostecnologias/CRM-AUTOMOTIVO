import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { CaretLeft, CaretRight, PencilSimple, Trash, X, MapPin, CalendarBlank } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { confirmToast } from "@/lib/confirm-toast";
import { FotoCarro, Placa } from "./Visual";
import FipeVeiculo from "./FipeVeiculo";
import { diasNoPatio, formatAno, formatKm, formatPreco, nomeVeiculo, rotulo, temPromocao } from "./estoque";

/**
 * A ficha do veículo: página de produto, não formulário. Galeria grande à
 * esquerda; à direita o nome, o preço, a ficha técnica em grade e as ações.
 * Quem não é admin vê a ficha sem as ações de escrita.
 */
export default function FichaVeiculo({ veiculo: v, opcoes, podeEditar, onFechar, onEditar, onMudou, onExcluido }) {
  const [i, setI] = useState(0);
  const [mudando, setMudando] = useState(false);
  const fotos = v.fotos || [];
  const atual = fotos[Math.min(i, Math.max(0, fotos.length - 1))];

  useEffect(() => {
    const tecla = (e) => {
      if (e.key === "Escape") onFechar();
      if (e.key === "ArrowRight" && fotos.length > 1) setI((x) => (x + 1) % fotos.length);
      if (e.key === "ArrowLeft" && fotos.length > 1) setI((x) => (x - 1 + fotos.length) % fotos.length);
    };
    document.addEventListener("keydown", tecla);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", tecla); document.body.style.overflow = ""; };
  }, [fotos.length, onFechar]);

  const situacao = async (status) => {
    if (status === v.status) return;
    setMudando(true);
    try {
      const { data } = await api.patch(`/estoque/veiculos/${v.id}`, { status });
      onMudou(data);
      toast.success(status === "vendido" ? "Vendido! Mais um que girou." : `Marcado como ${rotulo(opcoes, "status", status).toLowerCase()}`);
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message);
    } finally { setMudando(false); }
  };

  const excluir = async () => {
    if (!(await confirmToast(`Excluir ${nomeVeiculo(v)} do estoque? As fotos vão junto.`, { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/estoque/veiculos/${v.id}`);
      toast.success("Veículo excluído");
      onExcluido(v.id);
    } catch (ex) { toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message); }
  };

  const specs = [
    ["Ano", formatAno(v)],
    ["Quilometragem", formatKm(v.km)],
    ["Câmbio", rotulo(opcoes, "cambio", v.cambio)],
    ["Combustível", rotulo(opcoes, "combustivel", v.combustivel)],
    ["Motor", v.motor],
    ["Portas", v.portas ? String(v.portas) : null],
    ["Cor", v.cor],
    ["Categoria", rotulo(opcoes, "categoria", v.categoria)],
    ["Condição", rotulo(opcoes, "condicao", v.condicao)],
  ].filter(([, val]) => val);

  return createPortal(
    <div className="fixed inset-0 z-[100] bg-black/55 backdrop-blur-[2px] flex items-center justify-center p-3 sm:p-6"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onFechar(); }} data-testid="ficha-veiculo">
      <div className="bg-surface border border-line rounded-3xl w-full max-w-6xl max-h-[92vh] overflow-hidden shadow-pop flex flex-col lg:flex-row zz-surge">
        {/* Galeria */}
        <div className="lg:w-[58%] p-3 sm:p-4 flex flex-col gap-3 bg-surface-2">
          <div className="relative rounded-2xl overflow-hidden">
            <FotoCarro key={atual || "sem"} id={atual} alt={nomeVeiculo(v)} className="aspect-[4/3]" />
            {fotos.length > 1 && (
              <>
                <button type="button" className="zz-galeria-seta left-3" onClick={() => setI((x) => (x - 1 + fotos.length) % fotos.length)} aria-label="Foto anterior"><CaretLeft size={18} weight="bold" /></button>
                <button type="button" className="zz-galeria-seta right-3" onClick={() => setI((x) => (x + 1) % fotos.length)} aria-label="Próxima foto"><CaretRight size={18} weight="bold" /></button>
                <span className="absolute top-3 left-3 zz-selo-carro num">{Math.min(i, fotos.length - 1) + 1} / {fotos.length}</span>
              </>
            )}
          </div>
          {fotos.length > 1 && (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {fotos.map((id, n) => (
                <button key={id} type="button" onClick={() => setI(n)} aria-label={`Foto ${n + 1}`}
                  className={`shrink-0 w-24 rounded-lg overflow-hidden transition-all ${n === i ? "ring-2 ring-[var(--brand)] ring-offset-2 ring-offset-[var(--surface-2)]" : "opacity-60 hover:opacity-100"}`}>
                  <FotoCarro id={id} className="aspect-[4/3]" />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Ficha */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6 sm:p-8 flex flex-col">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="zz-sobre">{rotulo(opcoes, "status", v.status) || "Disponível"}{v.destaque ? " · Destaque" : ""}</div>
              <h2 className="font-heading text-[1.7rem] font-semibold tracking-tight leading-tight mt-1.5">{nomeVeiculo(v)}</h2>
              {v.versao && <div className="text-sm text-ink-2 mt-1">{v.versao}</div>}
            </div>
            <button type="button" onClick={onFechar} className="zz-btn-icon shrink-0" aria-label="Fechar"><X size={18} weight="bold" /></button>
          </div>

          <div className="flex items-center gap-3 mt-4 flex-wrap">
            <Placa placa={v.placa} grande />
            {v.localizacao && <span className="inline-flex items-center gap-1 text-xs text-ink-3"><MapPin size={13} /> {v.localizacao}</span>}
            <span className="inline-flex items-center gap-1 text-xs text-ink-3"><CalendarBlank size={13} /> {diasNoPatio(v.dias_no_patio)}</span>
          </div>

          {temPromocao(v) && (
            <div className="text-sm text-ink-3 mt-5 num">de <span className="line-through">{formatPreco(v.preco_anterior)}</span> por</div>
          )}
          <div className={`font-heading text-[2.2rem] font-semibold tracking-tight num leading-none ${temPromocao(v) ? "mt-1.5" : "mt-5"}`}>{formatPreco(v.preco)}</div>

          <FipeVeiculo veiculo={v} podeEditar={podeEditar} onMudou={onMudou} />

          {specs.length > 0 && (
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-5 gap-y-4 py-5 mt-5 border-y border-line">
              {specs.map(([k, val]) => (
                <div key={k}>
                  <dt className="zz-sobre !text-[0.6rem]">{k}</dt>
                  <dd className="text-sm font-medium mt-1 num">{val}</dd>
                </div>
              ))}
            </dl>
          )}

          {v.opcionais?.length > 0 && (
            <div className="mt-5">
              <div className="zz-sobre mb-2.5">Opcionais</div>
              <div className="flex flex-wrap gap-1.5">
                {v.opcionais.map((o) => <span key={o} className="text-xs bg-surface-3 rounded-lg px-2.5 py-1">{o}</span>)}
              </div>
            </div>
          )}

          {v.observacoes && (
            <div className="mt-5">
              <div className="zz-sobre mb-2">Descrição</div>
              <p className="text-sm text-ink-2 leading-relaxed whitespace-pre-line">{v.observacoes}</p>
            </div>
          )}

          {podeEditar && (
            <div className="mt-auto pt-6 space-y-3">
              <div className="zz-segmento" role="radiogroup" aria-label="Situação">
                {(opcoes.status || []).map(([valor, r]) => (
                  <button key={valor} type="button" role="radio" aria-checked={v.status === valor}
                    disabled={mudando} onClick={() => situacao(valor)}
                    className={v.status === valor ? "ativo" : ""} data-testid={`ficha-status-${valor}`}>
                    {r}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <button type="button" className="zz-btn flex-1 justify-center h-11" onClick={onEditar} data-testid="ficha-editar">
                  <PencilSimple size={16} /> Editar
                </button>
                <button type="button" className="zz-btn zz-btn-secondary h-11" onClick={excluir} aria-label="Excluir" title="Excluir do estoque" data-testid="ficha-excluir">
                  <Trash size={16} />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
