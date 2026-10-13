import { ChatCircleDots } from "@phosphor-icons/react";
import { MARCAS, valida } from "@/lib/marca";

// Ícone + nome da marca. `grande` é o da tela de login; o normal é o da barra
// lateral. A logo da R3 é uma arte quadrada com o fundo próprio, então ela
// ocupa o quadrado inteiro em vez de ir por cima de `bg-brand`.
export default function LogoMarca({ marca, grande = false, legenda = null }) {
  const m = MARCAS[valida(marca)];
  const caixa = grande ? "w-12 h-12 rounded-2xl" : "w-9 h-9 rounded-xl";
  return (
    <div className={`flex items-center ${grande ? "gap-3" : "gap-2"}`} data-testid="logo-marca" data-marca={m.id}>
      {m.logo ? (
        <img src={m.logo} alt="" className={`${caixa} object-cover shrink-0`} />
      ) : (
        <div className={`${caixa} bg-brand text-brand-fg flex items-center justify-center shrink-0`}>
          <ChatCircleDots size={grande ? 26 : 20} weight="bold" />
        </div>
      )}
      <div>
        <div className={`font-heading font-black tracking-tighter ${grande ? "text-2xl" : "text-lg leading-none"}`}>
          {m.nome}
        </div>
        {legenda && (
          <div className="text-[10px] uppercase tracking-[0.2em] text-ink-3 font-bold mt-0.5">{legenda}</div>
        )}
      </div>
    </div>
  );
}
