/**
 * Tema claro/escuro.
 *
 * Três estados, não dois: `claro`, `escuro` e `sistema`. "Sistema" é o padrão —
 * quem já configurou o sistema operacional no escuro não deveria ter que
 * configurar de novo aqui, e uma escolha explícita tem que ganhar do sistema
 * depois, senão o botão não funcionaria para quem está no escuro e quer claro.
 *
 * `aplicar()` roda **antes do React montar** (chamada em `index.js`), não num
 * `useEffect`: no efeito, o primeiro quadro já teria sido pintado com o tema
 * claro e a tela daria um flash branco a cada carregamento no tema escuro.
 *
 * A preferência é local do navegador, não do usuário no banco: é configuração
 * de dispositivo — o mesmo atendente pode querer escuro no notebook à noite e
 * claro no desktop do escritório.
 */

const CHAVE = "zappzen:tema";
export const TEMAS = ["claro", "escuro", "sistema"];

const consulta = () =>
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

/** O que está guardado, ou `sistema` se não houver nada (ou valor estranho). */
export function preferencia() {
  try {
    const v = localStorage.getItem(CHAVE);
    return TEMAS.includes(v) ? v : "sistema";
  } catch {
    // Navegador com armazenamento bloqueado (janela privada, política de site):
    // o tema segue o sistema em vez de estourar antes de a tela abrir.
    return "sistema";
  }
}

/** O tema que está de fato pintado na tela: só `claro` ou `escuro`. */
export function efetivo(pref = preferencia()) {
  if (pref === "sistema") return consulta()?.matches ? "escuro" : "claro";
  return pref;
}

/** Põe (ou tira) a classe `dark` no `<html>`, que é onde o Tailwind a procura. */
export function aplicar(pref = preferencia()) {
  const tema = efetivo(pref);
  document.documentElement.classList.toggle("dark", tema === "escuro");
  return tema;
}

export function guardar(pref) {
  try {
    localStorage.setItem(CHAVE, pref);
  } catch {
    // Sem armazenamento a escolha vale só para esta aba — melhor que recusar
    // a troca de tema.
  }
  return aplicar(pref);
}

/**
 * Avisa quando o sistema troca de tema. Só tem efeito com a preferência em
 * `sistema`: com escolha explícita, o tema do sistema é irrelevante e reagir a
 * ele desfaria a escolha da pessoa.
 */
export function observarSistema(callback) {
  const mq = consulta();
  if (!mq) return () => {};
  const ouvinte = () => {
    if (preferencia() === "sistema") callback(aplicar("sistema"));
  };
  mq.addEventListener("change", ouvinte);
  return () => mq.removeEventListener("change", ouvinte);
}
