/**
 * Vocabulário da interface.
 *
 * O código veio de um produto genérico de atendimento (ZappZen), e o texto dele
 * continua sendo a chave: `t("Contatos")` diz no JSX o que a tela mostraria lá.
 * O AUTO é um CRM de revenda de veículos e fala a língua do lojista, então
 * algumas palavras trocam. O dicionário é um só, igual nas duas marcas (Logos e
 * R3): marca muda cor, não vocabulário.
 *
 * A troca é por palavra e só entra quando preserva o gênero (o contato → o
 * cliente), para `` `Novo ${t("contato")}` `` sair certo sem frase dupla. Onde
 * a troca de palavra não fecharia, a frase inteira entra no dicionário.
 *
 * Maiúscula é derivada: sem entrada para "Contato", vale a de "contato" com a
 * primeira letra maiúscula. Só escreva a forma maiúscula quando ela for
 * diferente de verdade.
 *
 * Texto não pode ser resolvido no import do módulo: chame `t` na renderização,
 * ou numa função.
 */

const AUTO = {
  // Na revenda, quem chega pelo WhatsApp é cliente (ou interessado), nunca
  // "contato".
  contato: "cliente",
  contatos: "clientes",
};

const maiuscula = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const minuscula = (s) => s.charAt(0).toLowerCase() + s.slice(1);

/** O texto `chave` (escrito como no produto de origem) no vocabulário do AUTO. */
export function t(chave) {
  const dic = AUTO;
  if (Object.prototype.hasOwnProperty.call(dic, chave)) return dic[chave];
  const base = minuscula(chave);
  if (base !== chave && Object.prototype.hasOwnProperty.call(dic, base)) return maiuscula(dic[base]);
  return chave;
}
