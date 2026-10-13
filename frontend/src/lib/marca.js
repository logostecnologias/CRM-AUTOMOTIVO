/**
 * Marca do painel: de quem é o produto que o cliente final está vendo.
 *
 * O sistema é um só, revendido por mais de um parceiro, cada um para a própria
 * carteira. O cliente que comprou da R3 tem de abrir um painel da R3 (cores,
 * logo, nome na aba), nunca o de outro parceiro. Quem decide é o super admin, na
 * criação da empresa (`tenants.marca`), e o backend devolve a marca no login e
 * no `/auth/me`.
 *
 * A marca é independente do tema claro/escuro: cada marca define os dois
 * (`html[data-marca=...]` e `html.dark[data-marca=...]` em `index.css`), e o
 * botão de tema continua valendo para todo mundo.
 *
 * A última marca vista fica guardada no navegador e é aplicada **antes do React
 * montar**, pelo mesmo motivo de `tema.js`: sem isso todo carregamento do
 * painel da R3 piscaria com as cores da ZappZen até o `/auth/me` responder. É
 * também o que faz a tela de login de quem já entrou aparecer com a marca certa,
 * já que antes do login o servidor não sabe de que empresa a pessoa é.
 *
 * Marca nova entra aqui, no `Marca` de `backend/routes/tenants.py` e nos tokens
 * de `index.css`.
 */

const CHAVE = "zappzen:marca";
const BASE = process.env.PUBLIC_URL || "";

export const MARCAS = {
  zappzen: {
    id: "zappzen",
    nome: "ZappZen",
    // Sem arquivo de logo: a ZappZen é o ícone de balão sobre `bg-brand`.
    logo: null,
    favicon: `${BASE}/favicon.svg`,
    descricao: "Marca padrão: azul-marinho, ícone de balão.",
    amostra: ["#0F172A", "#2563EB", "#F6F7F9"],
  },
  r3: {
    id: "r3",
    nome: "R3",
    logo: `${BASE}/marcas/r3.jpg`,
    favicon: `${BASE}/marcas/r3.jpg`,
    descricao: "Petróleo e lima, com a logo da R3.",
    amostra: ["#00333D", "#D6E30F", "#F1EEEE"],
  },
};

export const PADRAO = "zappzen";

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
  document.title = m.nome;
  const icone = document.querySelector("link[rel='icon']");
  if (icone && icone.getAttribute("href") !== m.favicon) {
    icone.setAttribute("href", m.favicon);
    icone.setAttribute("type", m.favicon.endsWith(".svg") ? "image/svg+xml" : "image/jpeg");
  }
  try {
    localStorage.setItem(CHAVE, m.id);
  } catch {
    // Sem armazenamento a marca vale só até recarregar, e o `/auth/me` a reaplica.
  }
  return m;
}

/** A marca pintada agora. Para quem precisa do nome ou da logo no JSX. */
export function atual() {
  return MARCAS[valida(document.documentElement.dataset.marca)];
}
