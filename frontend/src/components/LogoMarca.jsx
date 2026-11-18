import { PRODUTO, valida } from "@/lib/marca";

// "AUTO" em versalete espaçado, com o traço do acento da marca. É igual nas
// duas marcas: o que muda é a cor (o traço é laranja na Logos e lima na R3,
// vindo de `--acento` em index.css). `grande` é o da tela de login; o normal é
// o da barra lateral. A legenda é o papel de quem está logado.
export default function LogoMarca({ marca, grande = false, legenda = null }) {
  return (
    <div data-testid="logo-marca" data-marca={valida(marca)}>
      <div className={`zz-wordmark ${grande ? "text-[1.6rem]" : "text-[1.15rem]"}`}>
        {PRODUTO}
        <span className="zz-wordmark-traco" aria-hidden />
      </div>
      {legenda && <div className="zz-nav-legenda mt-2">{legenda}</div>}
    </div>
  );
}
