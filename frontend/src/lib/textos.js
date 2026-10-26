/**
 * Texto da interface por marca.
 *
 * A chave é o próprio texto da ZappZen, e a ZappZen não tem dicionário: sem
 * entrada, `t("Contatos")` devolve "Contatos". Assim o JSX continua legível
 * (`{t("Novo contato")}` diz o que aparece na tela) e marca sem vocabulário
 * próprio não precisa de arquivo nenhum. Hoje só a Nexa, a versão para
 * clínicas, tem o seu.
 *
 * A maior parte do vocabulário é por palavra, e funciona porque cada troca da
 * Nexa preserva o gênero: o contato → o paciente, o negócio → o orçamento, a
 * empresa → a clínica, a atividade → a tarefa, o serviço → o procedimento, o
 * robô → o fluxo automático, o agente de IA → o assistente de IA. Então
 * `` `Novo ${t("contato")}` `` sai certo nas duas marcas sem frase dupla. Onde a
 * troca de palavra não fecha (artigo, plural, "funil" que vira "orçamentos"),
 * a frase inteira entra no dicionário.
 *
 * Maiúscula é derivada: sem entrada para "Contato", vale a de "contato" com a
 * primeira letra maiúscula. Só escreva a forma maiúscula quando ela for
 * diferente de verdade (ex.: "Funil", título e menu, é "Orçamentos", enquanto
 * "funil" no meio da frase é "quadro de orçamentos").
 *
 * `t` lê a marca pintada no `<html>`, não um contexto: funciona em qualquer
 * lugar, inclusive fora de componente. Quem garante que a tela redesenha quando
 * a marca muda (login, modo suporte) é o `AuthProvider`, que remonta a árvore
 * na troca. Por isso texto não pode ser resolvido no import do módulo (uma
 * constante no topo do arquivo ficaria na marca de quando o arquivo carregou):
 * chame `t` na renderização, ou numa função.
 */
// Relativo, não "@/lib/marca": o Jest do `craco test` não resolve o alias, e
// este módulo tem teste próprio.
import { atual } from "./marca";

const NEXA = {
  // Pacientes
  contato: "paciente",
  contatos: "pacientes",
  "Clientes e vendas": "Pacientes",

  // Orçamentos (funil e negócio)
  negócio: "orçamento",
  negócios: "orçamentos",
  Funil: "Orçamentos",
  funil: "quadro de orçamentos",
  funis: "quadros de orçamentos",
  ganho: "aprovado",
  ganhos: "aprovados",
  perdido: "não aprovado",
  perdidos: "não aprovados",
  // "ganha/perdida" concordam com "venda", feminino; a troca não fecha por palavra.
  "Só para a frente, e nunca marca venda ganha nem perdida: isso fica com a equipe.":
    "Só para a frente, e nunca marca orçamento como aprovado ou não aprovado: isso fica com a equipe.",
  "Funil de negócios": "Orçamentos",
  "Funil salvo": "Quadro de orçamentos salvo",
  "CRM e funil": "CRM e orçamentos",
  "CRM com funil": "CRM com orçamentos",
  "Por que perdemos?": "Por que não foi aprovado?",
  "Por que perdemos": "Por que não foi aprovado",
  "da criação ao ganho": "da criação à aprovação",
  "Este negócio sai do funil como perdido.": "Este orçamento passa a constar como não aprovado.",
  // Venda, na clínica, é orçamento aprovado.
  Vendas: "Aprovados",
  Vendido: "Aprovado",
  "Vendido no mês": "Aprovado no mês",
  "A venda conta para a campanha que trouxe o lead, mesmo que tenha fechado depois.":
    "O orçamento aprovado conta para a campanha que trouxe o lead, mesmo que tenha sido aprovado depois.",
  // Na Central, quem espera atendimento é o paciente.
  cliente: "paciente",
  clientes: "pacientes",

  // Procedimentos
  serviço: "procedimento",
  serviços: "procedimentos",

  // Tarefas
  atividade: "tarefa",
  atividades: "tarefas",

  // Automação
  robô: "fluxo automático",
  robôs: "fluxos automáticos",
  "agente de IA": "assistente de IA",
  "agentes de IA": "assistentes de IA",
  agente: "assistente",
  agentes: "assistentes",
  // "bot" aparece no editor de fluxos e na Central como sinônimo de robô.
  Bot: "Automático",
  "Bot de destino": "Fluxo automático de destino",
  "A conversa continua no fluxo do bot selecionado.": "A conversa continua no fluxo automático selecionado.",
  "selecione um bot": "selecione um fluxo automático",
  "Sem bot de primeira mensagem.": "Sem fluxo automático de primeira mensagem.",
  "O robô é criado já com um fluxo em branco, e o editor abre em seguida.":
    "O fluxo automático é criado em branco, e o editor abre em seguida.",

  // Clínica
  empresa: "clínica",
  empresas: "clínicas",
  Multiempresa: "Multiclínica",
  "voce@empresa.com": "voce@clinica.com.br",
};

const DICIONARIOS = { nexa: NEXA };

const maiuscula = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const minuscula = (s) => s.charAt(0).toLowerCase() + s.slice(1);

/** O texto `chave` (escrito como na ZappZen) na marca atual. */
export function t(chave) {
  const dic = DICIONARIOS[atual().id];
  if (!dic) return chave;
  if (Object.prototype.hasOwnProperty.call(dic, chave)) return dic[chave];
  const base = minuscula(chave);
  if (base !== chave && Object.prototype.hasOwnProperty.call(dic, base)) return maiuscula(dic[base]);
  return chave;
}

/** Para teste e para quem precisa saber se a marca tem vocabulário próprio. */
export function temVocabulario(marca = atual().id) {
  return Object.prototype.hasOwnProperty.call(DICIONARIOS, marca);
}
