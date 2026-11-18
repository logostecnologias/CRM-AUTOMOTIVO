/**
 * Marca do painel: as cores de quem vendeu o AUTO ao cliente.
 *
 * O produto é um só, o AUTO, revendido por mais de um parceiro, cada um para a
 * própria carteira. O cliente que comprou da R3 abre o AUTO nas cores da R3;
 * quem comprou da Logos, nas da Logos. Quem decide é o super admin, na criação
 * da empresa (`tenants.marca`), e o backend devolve a marca no login e no
 * `/auth/me`. Desde 18/11/2026 são só duas: Logos (a padrão) e R3. Valores
 * antigos (`zappzen`, `nexa`) caem na padrão, aqui e no backend.
 *
 * A marca é independente do tema claro/escuro: cada marca define os dois
 * (`html[data-marca=...]` e `html.dark[data-marca=...]` em `index.css`), e o
 * botão de tema continua valendo para todo mundo.
 *
 * A última marca vista fica guardada no navegador e é aplicada **antes do React
 * montar**, pelo mesmo motivo de `tema.js`: sem isso todo carregamento do
 * painel da R3 piscaria com as cores da Logos até o `/auth/me` responder. É
 * também o que faz a tela de login de quem já entrou aparecer com a marca certa,
 * já que antes do login o servidor não sabe de que empresa a pessoa é.
 *
 * Marca nova entra aqui, em `backend/marcas.py` e nos tokens de `index.css`.
 */

// A chave mantém o nome antigo de propósito: trocar faria todo navegador de
// cliente R3 abrir uma vez nas cores da Logos.
const CHAVE = "zappzen:marca";
const BASE = process.env.PUBLIC_URL || "";

/** O nome do produto, igual nas duas marcas. */
export const PRODUTO = "AUTO";

export const MARCAS = {
  logos: {
    id: "logos",
    nome: "Logos",
    favicon: `${BASE}/marcas/auto-logos.svg`,
    descricao: "Preto e laranja da Logos. Poppins nos títulos.",
    amostra: ["#0E0E10", "#F77C20", "#F5F4F2"],
  },
  r3: {
    id: "r3",
    nome: "R3",
    favicon: `${BASE}/marcas/auto-r3.svg`,
    descricao: "Petróleo, gelo e lima da R3. Manrope nos títulos.",
    amostra: ["#00333D", "#D6E30F", "#F1EEEE"],
    // Fonte dos títulos da R3. Buscada só quando a marca é aplicada: quem é
    // Logos não espera por ela.
    fontes: "https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700&display=swap",
  },
};

export const PADRAO = "logos";

export function valida(marca) {
  return Object.prototype.hasOwnProperty.call(MARCAS, marca) ? marca : PADRAO;
}

/** A última marca aplicada neste navegador, ou a padrão. */
export function guardada() {
  try {
    return valida(localStorage.getItem(CHAVE));
  } catch {
    // Armazenamento bloqueado: começa na padrão e o `/auth/me` corrige.
    return PADRAO;
  }
}

/** Pinta a marca: atributo no `<html>`, título da aba e favicon. */
export function aplicar(marca = guardada()) {
  const m = MARCAS[valida(marca)];
  document.documentElement.dataset.marca = m.id;
  document.title = PRODUTO;
  const icone = document.querySelector("link[rel='icon']");
  if (icone && icone.getAttribute("href") !== m.favicon) {
    icone.setAttribute("href", m.favicon);
    icone.setAttribute("type", "image/svg+xml");
  }
  if (m.fontes && !document.querySelector(`link[data-fontes-marca='${m.id}']`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = m.fontes;
    link.dataset.fontesMarca = m.id;
    document.head.appendChild(link);
  }
  try {
    localStorage.setItem(CHAVE, m.id);
  } catch {
    // Sem armazenamento a marca vale só até recarregar, e o `/auth/me` a reaplica.
  }
  return m;
}

/** A marca pintada agora. Para quem precisa do nome no JSX. */
export function atual() {
  return MARCAS[valida(document.documentElement.dataset.marca)];
}
