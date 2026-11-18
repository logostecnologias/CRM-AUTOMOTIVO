import { useState } from "react";
import { fotoUrl, formatPlaca } from "./estoque";

/** Placa no padrão Mercosul: faixa azul fina em cima, letra condensada. */
export function Placa({ placa, grande = false }) {
  if (!placa) return null;
  return (
    <span className={`zz-placa ${grande ? "grande" : ""}`} title="Placa">
      <span className="zz-placa-faixa" aria-hidden />
      <span className="zz-placa-texto">{formatPlaca(placa)}</span>
    </span>
  );
}

/** Silhueta de carro em traço, para o veículo ainda sem foto. */
export function SilhuetaCarro({ className = "" }) {
  return (
    <svg viewBox="0 0 640 240" className={className} aria-hidden>
      <path
        d="M58,164 L58,150 C58,134 66,124 82,120 L118,114 C150,108 176,92 206,78 C236,64 270,58 312,57 L372,57 C410,58 436,68 466,90 L492,108 L556,116 C578,119 590,130 592,146 L592,160 C592,166 588,170 582,170 L530,170 A42,42 0 0 0 446,170 L212,170 A42,42 0 0 0 128,170 L64,170 C60,170 58,168 58,164 Z"
        fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
      <path d="M214,84 C240,70 270,65 310,64 L336,64 L336,104 L176,104 C188,96 200,90 214,84 Z M348,64 L372,64 C404,65 428,74 452,94 L462,104 L348,104 Z"
        fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
      <circle cx="170" cy="160" r="32" fill="none" stroke="currentColor" strokeWidth="3" />
      <circle cx="488" cy="160" r="32" fill="none" stroke="currentColor" strokeWidth="3" />
    </svg>
  );
}

/**
 * A foto do carro num fundo de estúdio. Enquanto carrega (ou se não houver
 * foto), aparece o fundo neutro com a silhueta: a grade nunca pula de altura
 * e nunca mostra ícone de imagem quebrada.
 */
export function FotoCarro({ id, alt = "", className = "", contain = false }) {
  const [estado, setEstado] = useState(id ? "carregando" : "sem");
  return (
    <div className={`zz-foto-carro ${className}`}>
      {estado !== "pronta" && (
        <div className="absolute inset-0 grid place-items-center">
          <SilhuetaCarro className={`w-1/2 text-ink-4 ${estado === "carregando" ? "opacity-30 animate-pulse" : "opacity-40"}`} />
        </div>
      )}
      {id && estado !== "erro" && (
        <img
          src={fotoUrl(id)} alt={alt} loading="lazy" draggable={false}
          onLoad={() => setEstado("pronta")} onError={() => setEstado("erro")}
          className={`absolute inset-0 w-full h-full ${contain ? "object-contain" : "object-cover"} transition-opacity duration-500 ${
            estado === "pronta" ? "opacity-100" : "opacity-0"}`}
        />
      )}
    </div>
  );
}

/** Selo discreto sobre a foto: destaque, reservado, vendido, parado. */
export function SeloVeiculo({ v }) {
  if (v.status === "vendido") return <span className="zz-selo-carro escuro">Vendido</span>;
  if (v.status === "reservado") return <span className="zz-selo-carro escuro">Reservado</span>;
  if (v.parado) return <span className="zz-selo-carro alerta">Parado · {v.dias_no_patio} dias</span>;
  if (v.destaque) return <span className="zz-selo-carro destaque">Destaque</span>;
  if (v.dias_no_patio !== null && v.dias_no_patio <= 7) return <span className="zz-selo-carro">Novo no pátio</span>;
  return null;
}
