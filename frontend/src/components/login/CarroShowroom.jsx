import { useRef } from "react";

/**
 * O carro da tela de entrada: traço fino num salão escuro, sob um holofote que
 * segue o mouse. Ele reage ao formulário, sem pedir atenção:
 *
 *   - `farol`    campo em foco: os faróis acendem;
 *   - `giro`     cada tecla digitada gira as rodas um pouco;
 *   - `andando`  entrando: as rodas giram e o carro "arranca";
 *   - `erro`     senha errada: um tranco curto.
 *
 * Clicar no carro pisca o farol. Tudo é CSS (index.css, "Entrada"), e com
 * `prefers-reduced-motion` o carro fica parado e só o farol muda.
 *
 * Desenho original, em SVG, sem marca nem modelo real.
 */
const CORPO =
  "M58,164 L58,150 C58,134 66,124 82,120 L118,114 C150,108 176,92 206,78 " +
  "C236,64 270,58 312,57 L372,57 C410,58 436,68 466,90 L492,108 L556,116 " +
  "C578,119 590,130 592,146 L592,160 C592,166 588,170 582,170 L530,170 " +
  "A42,42 0 0 0 446,170 L212,170 A42,42 0 0 0 128,170 L64,170 C60,170 58,168 58,164 Z";

function Roda({ cx, giro }) {
  const raios = [0, 72, 144, 216, 288];
  return (
    <g className="zz-carro-roda" style={{ "--giro": `${giro}deg` }}>
      <circle cx={cx} cy={160} r={34} className="zz-carro-pneu" />
      <circle cx={cx} cy={160} r={24} className="zz-carro-traco" />
      {raios.map((a) => {
        const r = (a * Math.PI) / 180;
        return (
          <line key={a} className="zz-carro-traco fino"
            x1={cx + Math.cos(r) * 6} y1={160 + Math.sin(r) * 6}
            x2={cx + Math.cos(r) * 22} y2={160 + Math.sin(r) * 22} />
        );
      })}
      <circle cx={cx} cy={160} r={4} className="zz-carro-cubo" />
    </g>
  );
}

function Carro({ giro }) {
  return (
    <g>
      {/* Facho do farol: só aparece com o farol aceso. */}
      <path d="M588,134 L640,104 L640,176 Z" className="zz-carro-facho" />
      <path d={CORPO} className="zz-carro-corpo" />
      <path d="M214,84 C240,70 270,65 310,64 L336,64 L336,104 L176,104 C188,96 200,90 214,84 Z" className="zz-carro-vidro" />
      <path d="M348,64 L372,64 C404,65 428,74 452,94 L462,104 L348,104 Z" className="zz-carro-vidro" />
      <path d="M96,128 C200,120 400,116 556,122" className="zz-carro-traco fino" />
      <path d="M214,150 L444,150" className="zz-carro-traco fino suave" />
      <path d="M342,108 L346,166" className="zz-carro-traco fino suave" />
      <path d="M298,124 L320,124" className="zz-carro-traco" strokeLinecap="round" />
      <path d="M444,98 L458,95 L462,104 L448,104 Z" className="zz-carro-traco fino" />
      <path d="M558,124 L588,131 L586,138 L556,132 Z" className="zz-carro-farol" />
      <path d="M60,128 L86,124 L86,130 L60,134 Z" className="zz-carro-lanterna" />
      {/* O brilho que corre pelo contorno: o reflexo das luzes do salão. */}
      <path d={CORPO} pathLength="1000" className="zz-carro-brilho" />
      <Roda cx={170} giro={giro} />
      <Roda cx={488} giro={giro} />
    </g>
  );
}

export default function CarroShowroom({ farol = false, giro = 0, andando = false, erro = false, onPiscar }) {
  const palco = useRef(null);

  // Holofote e paralaxe seguem o mouse por variável CSS: nada de estado do
  // React a cada pixel.
  const mover = (e) => {
    const el = palco.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    el.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
    el.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
    el.style.setProperty("--px", (x - 0.5).toFixed(3));
  };

  const classes = ["zz-palco", farol && "farol", andando && "andando", erro && "erro"]
    .filter(Boolean).join(" ");

  return (
    <div ref={palco} className={classes} onMouseMove={mover} data-testid="login-showroom">
      <div className="zz-palco-luz" aria-hidden />
      <button type="button" className="zz-palco-carro" onClick={onPiscar}
        aria-label="Piscar o farol" title="Pisca o farol">
        <svg viewBox="0 0 640 240" role="img" aria-hidden>
          <defs>
            <linearGradient id="zz-facho" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="#FFF6E0" stopOpacity=".55" />
              <stop offset="1" stopColor="#FFF6E0" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="zz-chao" x1="0" x2="1">
              <stop offset="0" stopColor="currentColor" stopOpacity="0" />
              <stop offset=".5" stopColor="currentColor" stopOpacity=".35" />
              <stop offset="1" stopColor="currentColor" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="zz-reflexo-mascara" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#fff" stopOpacity=".5" />
              <stop offset=".6" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
            <mask id="zz-reflexo">
              <rect x="0" y="196" width="640" height="44" fill="url(#zz-reflexo-mascara)" />
            </mask>
            <radialGradient id="zz-sombra">
              <stop offset="0" stopColor="#000" stopOpacity=".55" />
              <stop offset="1" stopColor="#000" stopOpacity="0" />
            </radialGradient>
          </defs>

          <ellipse cx="325" cy="196" rx="270" ry="10" fill="url(#zz-sombra)" />
          <line x1="20" y1="196" x2="620" y2="196" stroke="url(#zz-chao)" strokeWidth="1" />

          {/* Linhas de velocidade, só quando está "andando". */}
          <g className="zz-carro-vento">
            <line x1="0" y1="110" x2="70" y2="110" />
            <line x1="10" y1="134" x2="60" y2="134" />
            <line x1="0" y1="152" x2="80" y2="152" />
          </g>

          <g className="zz-carro">
            <Carro giro={giro} />
          </g>
          <g mask="url(#zz-reflexo)" className="zz-carro-reflexo">
            <g transform="translate(0,392) scale(1,-1)">
              <Carro giro={giro} />
            </g>
          </g>
        </svg>
      </button>
    </div>
  );
}
