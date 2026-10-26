import { t, temVocabulario } from "./textos";

const comMarca = (marca) => { document.documentElement.dataset.marca = marca; };

describe("texto por marca", () => {
  afterEach(() => { delete document.documentElement.dataset.marca; });

  test("a ZappZen devolve a própria chave", () => {
    comMarca("zappzen");
    expect(t("Contatos")).toBe("Contatos");
    expect(t("Funil")).toBe("Funil");
    expect(t("qualquer frase")).toBe("qualquer frase");
  });

  test("a R3 não tem vocabulário próprio", () => {
    comMarca("r3");
    expect(temVocabulario("r3")).toBe(false);
    expect(t("contato")).toBe("contato");
  });

  test("a Nexa troca as palavras, e a maiúscula é derivada", () => {
    comMarca("nexa");
    expect(t("contato")).toBe("paciente");
    expect(t("Contatos")).toBe("Pacientes");
    expect(t("Agentes de IA")).toBe("Assistentes de IA");
    expect(t("Perdido")).toBe("Não aprovado");
  });

  test("forma maiúscula própria ganha da derivada", () => {
    comMarca("nexa");
    expect(t("Funil")).toBe("Orçamentos");
    expect(t("funil")).toBe("quadro de orçamentos");
  });

  test("chave fora do dicionário passa intacta na Nexa", () => {
    comMarca("nexa");
    expect(t("Profissional")).toBe("Profissional");
  });

  test("marca desconhecida no <html> cai na padrão", () => {
    comMarca("inventada");
    expect(t("Contatos")).toBe("Contatos");
  });
});
